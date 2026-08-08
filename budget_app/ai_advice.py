"""OpenAI Responses API를 이용한 월별 소비 조언.

개별 거래의 메모나 날짜는 전송하지 않고 월별 집계만 전송한다.
외부 패키지 없이 Python 표준 라이브러리로 동작한다.
"""

from __future__ import annotations

import json
import os
import ssl
from pathlib import Path
from urllib import error, request

from .errors import AppError
from .services import BudgetStatus, MonthlySummary

API_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.6-luna"


class AIAdviceError(AppError):
    exit_code = 6


def _ssl_context() -> ssl.SSLContext:
    """Python CA 설정이 비어 있는 macOS 설치에서도 인증서 검증을 유지한다."""
    paths = ssl.get_default_verify_paths()
    if paths.cafile:
        return ssl.create_default_context()
    system_ca = Path("/etc/ssl/cert.pem")
    if system_ca.is_file():
        return ssl.create_default_context(cafile=str(system_ca))
    try:
        import certifi  # type: ignore[import-not-found]
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def load_env(path: Path) -> None:
    """간단한 KEY=VALUE 형식의 .env를 읽되 기존 환경변수는 덮어쓰지 않는다."""
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise AIAdviceError(f"환경변수 파일을 읽을 수 없습니다: {path}", str(exc)) from None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if value[:1] == value[-1:] and value[:1] in ('"', "'"):
            value = value[1:-1]
        if key and value:
            os.environ.setdefault(key, value)


def _analysis_input(summary: MonthlySummary, statuses: list[BudgetStatus]) -> str:
    expenses = sorted((summary.by_category or {}).items(), key=lambda item: item[1], reverse=True)
    incomes = sorted((summary.by_income_category or {}).items(), key=lambda item: item[1], reverse=True)
    budgets = [
        {"대상": item.label, "예산": item.budget, "사용": item.used,
         "소진율": round(item.ratio * 100, 1)}
        for item in statuses
    ]
    data = {
        "월": summary.month,
        "거래_건수": summary.count,
        "총수입": summary.income,
        "총지출": summary.expense,
        "잔액": summary.net,
        "지출_카테고리별_합계": dict(expenses),
        "수입_카테고리별_합계": dict(incomes),
        "예산_현황": budgets,
    }
    return json.dumps(data, ensure_ascii=False)


def _extract_text(response: dict) -> str:
    direct = response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    chunks: list[str] = []
    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                chunks.append(str(content["text"]))
    if not chunks:
        raise AIAdviceError("OpenAI 응답에서 조언 텍스트를 찾지 못했습니다.")
    return "\n".join(chunks).strip()


def generate_advice(summary: MonthlySummary, statuses: list[BudgetStatus], *,
                    model: str = DEFAULT_MODEL, max_output_tokens: int = 700,
                    timeout: int = 30) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise AIAdviceError(
            "OPENAI_API_KEY가 설정되지 않았습니다.",
            "프로젝트의 .env에 OPENAI_API_KEY=... 형식으로 입력하세요.",
        )

    payload = {
        "model": model,
        "instructions": (
            "당신은 신중한 한국어 가계부 코치입니다. 제공된 월별 집계만 근거로 분석하세요. "
            "금융상품 추천이나 확정적 투자 조언은 하지 마세요. 결과는 '한줄 진단', "
            "'주요 관찰', '다음 달 실천 3가지' 순서로 짧고 구체적으로 작성하세요. "
            "금액은 원 단위로 보기 쉽게 표시하고, 데이터가 부족하면 그 한계를 명시하세요."
        ),
        "input": _analysis_input(summary, statuses),
        "max_output_tokens": max_output_tokens,
        "reasoning": {"effort": "low"},
        "text": {"verbosity": "low"},
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        API_URL,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", "")
        except (json.JSONDecodeError, UnicodeDecodeError):
            detail = ""
        hints = {401: "API 키가 유효한지 확인하세요.", 429: "사용량 한도와 결제 설정을 확인하세요."}
        raise AIAdviceError(
            f"OpenAI API 요청이 실패했습니다. (HTTP {exc.code})",
            detail or hints.get(exc.code, "잠시 후 다시 시도하세요."),
        ) from None
    except (error.URLError, TimeoutError) as exc:
        raise AIAdviceError("OpenAI API에 연결하지 못했습니다.", str(exc.reason)) from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise AIAdviceError("OpenAI API 응답을 해석하지 못했습니다.") from None
    return _extract_text(result)
