"""입력 검증 모듈.

CLI 인자든 대화형 입력이든 import CSV든, 값이 도메인에 들어가기 전에
반드시 이 모듈을 통과한다. 실패 시 ValidationError(원인, 힌트)를 던진다.
"""

from __future__ import annotations

import calendar
import re
from datetime import date as _date, datetime

from .errors import ValidationError
from .models import TX_TYPES, CATEGORY_SCOPES

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
AMOUNT_CLEAN_RE = re.compile(r"[,_\s원]")

MAX_AMOUNT = 1_000_000_000_000  # 1조. 오타 방어용 상한
MAX_MEMO_LEN = 200
MAX_TAGS = 10
MAX_TAG_LEN = 20

_TYPE_ALIASES = {
    "income": "income", "in": "income", "i": "income",
    "수입": "income", "+": "income",
    "expense": "expense", "exp": "expense", "out": "expense", "e": "expense",
    "지출": "expense", "-": "expense",
}


def validate_date(value: str, *, field_name: str = "date") -> str:
    """YYYY-MM-DD 형식 + 실제 존재하는 날짜인지 검증. 'today' 별칭 허용."""
    raw = (value or "").strip()
    if not raw:
        raise ValidationError(
            f"{field_name} 값이 비어 있습니다.",
            "YYYY-MM-DD 형식으로 입력하세요. 예: 2026-08-08 (또는 today)",
        )
    if raw.lower() in ("today", "오늘"):
        return _date.today().isoformat()
    if not DATE_RE.match(raw):
        raise ValidationError(
            f"{field_name} 형식이 올바르지 않습니다: {raw!r}",
            "YYYY-MM-DD 형식이어야 합니다. 예: 2026-08-08",
        )
    try:
        datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        raise ValidationError(
            f"존재하지 않는 날짜입니다: {raw!r}",
            "달의 마지막 날을 넘기지 않았는지 확인하세요. 예: 2026-02-30 은 없는 날짜입니다.",
        ) from None
    return raw


def validate_month(value: str, *, field_name: str = "month") -> str:
    """YYYY-MM 형식 검증. 'this'/'현재' 별칭 허용."""
    raw = (value or "").strip()
    if raw.lower() in ("this", "current", "이번달", "현재"):
        return _date.today().strftime("%Y-%m")
    if not MONTH_RE.match(raw):
        raise ValidationError(
            f"{field_name} 형식이 올바르지 않습니다: {raw!r}",
            "YYYY-MM 형식이어야 합니다. 예: --month 2026-08",
        )
    year, month = int(raw[:4]), int(raw[5:7])
    if not 1 <= month <= 12:
        raise ValidationError(
            f"월 범위를 벗어났습니다: {raw!r}",
            "월은 01~12 사이여야 합니다.",
        )
    if not 1900 <= year <= 2999:
        raise ValidationError(f"연도 범위를 벗어났습니다: {raw!r}", "1900~2999 사이여야 합니다.")
    return raw


def month_range(month: str) -> tuple[str, str]:
    """'2026-08' -> ('2026-08-01', '2026-08-31')"""
    month = validate_month(month)
    year, mon = int(month[:4]), int(month[5:7])
    last = calendar.monthrange(year, mon)[1]
    return f"{month}-01", f"{month}-{last:02d}"


def validate_amount(value) -> int:
    """금액: 0보다 큰 정수(원). '12,000', '12000원', '12_000' 허용."""
    if isinstance(value, bool):
        raise ValidationError("금액이 올바르지 않습니다.", "숫자를 입력하세요. 예: 12000")
    if isinstance(value, int):
        cleaned = str(value)
    else:
        cleaned = AMOUNT_CLEAN_RE.sub("", str(value or ""))
    if not cleaned:
        raise ValidationError("금액이 비어 있습니다.", "0보다 큰 정수를 입력하세요. 예: 12000")
    if cleaned.startswith("-"):
        raise ValidationError(
            f"금액은 음수가 될 수 없습니다: {value!r}",
            "지출도 양수로 입력하고 type 을 expense 로 지정하세요.",
        )
    if not cleaned.isdigit():
        raise ValidationError(
            f"금액에 숫자가 아닌 값이 있습니다: {value!r}",
            "소수점 없이 원 단위 정수로 입력하세요. 예: 12000 또는 12,000",
        )
    amount = int(cleaned)
    if amount <= 0:
        raise ValidationError("금액은 0보다 커야 합니다.", "예: --amount 12000")
    if amount > MAX_AMOUNT:
        raise ValidationError(
            f"금액이 너무 큽니다: {amount:,}",
            f"허용 최대치는 {MAX_AMOUNT:,} 입니다. 자릿수를 확인하세요.",
        )
    return amount


def validate_type(value: str) -> str:
    """income / expense 로 정규화. 한글·약어 별칭 허용."""
    raw = (value or "").strip().lower()
    if raw in _TYPE_ALIASES:
        return _TYPE_ALIASES[raw]
    raise ValidationError(
        f"거래 타입이 올바르지 않습니다: {value!r}",
        "income(수입) 또는 expense(지출) 중 하나여야 합니다. 예: --type expense",
    )


def validate_category_name(value: str) -> str:
    name = (value or "").strip()
    if not name:
        raise ValidationError("카테고리명이 비어 있습니다.", "예: --category 식비")
    if len(name) > 30:
        raise ValidationError("카테고리명이 너무 깁니다(최대 30자).", "짧게 줄여 주세요.")
    if any(ch in name for ch in ',\t\n"'):
        raise ValidationError(
            f"카테고리명에 사용할 수 없는 문자가 있습니다: {name!r}",
            "쉼표, 따옴표, 탭, 줄바꿈은 사용할 수 없습니다(CSV 호환).",
        )
    return name


def validate_scope(value: str) -> str:
    raw = (value or "both").strip().lower()
    if raw in ("both", "all", "공용"):
        return "both"
    if raw in _TYPE_ALIASES:
        return _TYPE_ALIASES[raw]
    raise ValidationError(
        f"카테고리 scope 가 올바르지 않습니다: {value!r}",
        f"{'/'.join(CATEGORY_SCOPES)} 중 하나여야 합니다.",
    )


def validate_memo(value: str) -> str:
    memo = (value or "").strip().replace("\n", " ").replace("\r", " ")
    if len(memo) > MAX_MEMO_LEN:
        raise ValidationError(
            f"메모가 너무 깁니다({len(memo)}자).",
            f"최대 {MAX_MEMO_LEN}자까지 입력할 수 있습니다.",
        )
    return memo


def parse_tags(value) -> list[str]:
    """'점심;회사' 또는 '점심,회사' 또는 리스트 -> ['점심', '회사']"""
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        raw_items = [str(v) for v in value]
    else:
        raw_items = re.split(r"[;,]", str(value))

    tags: list[str] = []
    for item in raw_items:
        tag = item.strip().lstrip("#")
        if not tag:
            continue
        if len(tag) > MAX_TAG_LEN:
            raise ValidationError(
                f"태그가 너무 깁니다: {tag!r}",
                f"태그 하나는 최대 {MAX_TAG_LEN}자입니다.",
            )
        if tag not in tags:
            tags.append(tag)
    if len(tags) > MAX_TAGS:
        raise ValidationError(
            f"태그가 너무 많습니다({len(tags)}개).",
            f"최대 {MAX_TAGS}개까지 지정할 수 있습니다.",
        )
    return tags


def validate_positive_int(value, *, field_name: str, minimum: int = 1, maximum: int | None = None) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValidationError(
            f"{field_name} 값은 정수여야 합니다: {value!r}",
            f"예: --{field_name} 10",
        ) from None
    if number < minimum:
        raise ValidationError(f"{field_name} 값은 {minimum} 이상이어야 합니다.", f"입력값: {number}")
    if maximum is not None and number > maximum:
        raise ValidationError(f"{field_name} 값은 {maximum} 이하여야 합니다.", f"입력값: {number}")
    return number


def validate_date_range(date_from: str | None, date_to: str | None) -> tuple[str | None, str | None]:
    start = validate_date(date_from, field_name="--from") if date_from else None
    end = validate_date(date_to, field_name="--to") if date_to else None
    if start and end and start > end:
        raise ValidationError(
            f"기간이 뒤집혔습니다: --from {start} > --to {end}",
            "--from 은 --to 보다 이전이거나 같아야 합니다.",
        )
    return start, end


def assert_known_type(value: str) -> str:
    if value not in TX_TYPES:
        raise ValidationError(f"알 수 없는 거래 타입: {value!r}", "income 또는 expense")
    return value
