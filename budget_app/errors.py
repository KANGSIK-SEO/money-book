"""사용자에게 '원인 + 힌트'를 보여주기 위한 예외 계층.

프로그램은 스택트레이스를 그대로 노출하지 않고, 이 예외들을 잡아
사람이 읽을 수 있는 메시지로 변환해서 출력한다. (cli.handle_errors 참고)
"""

from __future__ import annotations


class AppError(Exception):
    """가계부 앱에서 발생하는 모든 '예상된' 오류의 최상위 타입."""

    exit_code = 1

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint

    def render(self) -> str:
        lines = ["[오류] " + self.message]
        if self.hint:
            lines.append("  힌트: " + self.hint)
        return "\n".join(lines)


class ValidationError(AppError):
    """입력값(날짜/금액/타입/카테고리 등) 검증 실패."""

    exit_code = 2


class NotFoundError(AppError):
    """대상 데이터(거래, 카테고리, 예산)를 찾지 못함."""

    exit_code = 3


class ConflictError(AppError):
    """중복 생성, 사용 중인 카테고리 삭제 등 상태 충돌."""

    exit_code = 4


class StorageError(AppError):
    """파일 읽기/쓰기/파싱 실패."""

    exit_code = 5


class AbortError(AppError):
    """사용자가 확인 단계에서 취소함."""

    exit_code = 0

    def __init__(self, message: str = "사용자가 작업을 취소했습니다.", hint: str | None = None):
        super().__init__(message, hint)
