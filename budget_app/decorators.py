"""실제로 사용되는 데코레이터 모음.

- @handle_errors : 스택트레이스 대신 '원인 + 힌트'를 출력하고 종료코드를 반환
- @timed         : --verbose 일 때만 실행 시간을 stderr 에 출력
- @confirm       : 파괴적 명령 실행 전 y/N 확인 (--yes 로 생략)
- @command       : 서브커맨드 핸들러 등록(레지스트리)
"""

from __future__ import annotations

import functools
import sys
import time
from typing import Callable

from .errors import AbortError, AppError

#: 서브커맨드 이름 -> 핸들러 함수
REGISTRY: dict[str, Callable] = {}


def command(name: str):
    """핸들러를 서브커맨드 이름에 연결하는 레지스트리 데코레이터."""

    def decorator(func):
        REGISTRY[name] = func

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        REGISTRY[name] = wrapper
        return wrapper

    return decorator


def handle_errors(func):
    """예상된 오류는 사람이 읽는 메시지로, 예상 못 한 오류는 요약 + 힌트로 변환."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        debug = "--debug" in sys.argv
        try:
            return func(*args, **kwargs)
        except AbortError as exc:
            print(exc.message, file=sys.stderr)
            return exc.exit_code
        except AppError as exc:
            print(exc.render(), file=sys.stderr)
            return exc.exit_code
        except KeyboardInterrupt:
            print("\n[중단] 사용자가 Ctrl+C 로 종료했습니다.", file=sys.stderr)
            return 130
        except BrokenPipeError:
            return 0
        except FileNotFoundError as exc:
            print(f"[오류] 파일을 찾을 수 없습니다: {exc.filename}", file=sys.stderr)
            print("  힌트: --data-dir 경로가 맞는지, 파일이 삭제되지 않았는지 확인하세요.", file=sys.stderr)
            return 5
        except PermissionError as exc:
            print(f"[오류] 파일 접근 권한이 없습니다: {exc.filename}", file=sys.stderr)
            print("  힌트: 데이터 폴더의 읽기/쓰기 권한을 확인하세요.", file=sys.stderr)
            return 5
        except Exception as exc:  # noqa: BLE001 - 최후의 방어선
            if debug:
                raise
            print(f"[오류] 예상하지 못한 문제가 발생했습니다: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            print("  힌트: --debug 옵션을 붙이면 상세 스택트레이스를 볼 수 있습니다.",
                  file=sys.stderr)
            return 1

    return wrapper


def timed(func):
    """args.verbose 가 True 일 때만 실행 시간을 출력한다."""

    @functools.wraps(func)
    def wrapper(args, *rest, **kwargs):
        verbose = bool(getattr(args, "verbose", False))
        started = time.perf_counter()
        try:
            return func(args, *rest, **kwargs)
        finally:
            if verbose:
                elapsed = (time.perf_counter() - started) * 1000
                print(f"[verbose] {func.__name__} 완료: {elapsed:.1f} ms", file=sys.stderr)

    return wrapper


def confirm(question: str):
    """파괴적 명령 앞에 붙이는 확인 데코레이터. args.yes 가 True 면 건너뛴다."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(args, *rest, **kwargs):
            if not getattr(args, "yes", False):
                if not sys.stdin.isatty():
                    raise AbortError(
                        "확인 입력을 받을 수 없어 작업을 취소했습니다.",
                        "비대화형 환경에서는 --yes 옵션을 함께 사용하세요.",
                    )
                answer = input(f"{question} [y/N] ").strip().lower()
                if answer not in ("y", "yes"):
                    raise AbortError()
            return func(args, *rest, **kwargs)

        return wrapper

    return decorator
