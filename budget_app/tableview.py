"""(보너스) 외부 라이브러리 없이 표를 정렬해서 그리는 모듈.

한글은 터미널에서 2칸을 차지하므로 unicodedata.east_asian_width 로 실제 폭을 계산한다.
"""

from __future__ import annotations

import unicodedata

LEFT, RIGHT, CENTER = "left", "right", "center"


def display_width(text) -> int:
    """터미널에서 차지하는 실제 칸 수."""
    total = 0
    for char in str(text):
        if unicodedata.combining(char):
            continue
        total += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return total


def truncate(text, limit: int) -> str:
    """표시 폭 기준으로 자르고 말줄임표를 붙인다."""
    text = str(text)
    if display_width(text) <= limit:
        return text
    out, used = [], 0
    for char in text:
        char_width = display_width(char)
        if used + char_width > limit - 1:
            break
        out.append(char)
        used += char_width
    return "".join(out) + "…"


def pad(text, width: int, align: str = LEFT) -> str:
    text = str(text)
    gap = max(0, width - display_width(text))
    if align == RIGHT:
        return " " * gap + text
    if align == CENTER:
        left = gap // 2
        return " " * left + text + " " * (gap - left)
    return text + " " * gap


def render_table(headers: list[str], rows: list[list], aligns: list[str] | None = None,
                 max_widths: list[int] | None = None) -> str:
    """헤더/구분선/본문으로 구성된 표 문자열을 만든다."""
    if not rows:
        return "(표시할 데이터가 없습니다)"

    aligns = aligns or [LEFT] * len(headers)
    if max_widths:
        rows = [
            [truncate(cell, max_widths[i]) if max_widths[i] else cell for i, cell in enumerate(row)]
            for row in rows
        ]

    widths = [display_width(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], display_width(cell))

    lines = []
    lines.append("  ".join(pad(h, widths[i], CENTER) for i, h in enumerate(headers)))
    lines.append("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        lines.append("  ".join(pad(cell, widths[i], aligns[i]) for i, cell in enumerate(row)))
    return "\n".join(lines)


def bar(ratio: float, width: int = 20) -> str:
    """0.0~1.0(초과 가능) 비율을 막대로 표현."""
    ratio = max(0.0, ratio)
    filled = min(width, int(round(ratio * width)))
    over = ratio > 1.0
    return ("█" * filled).ljust(width, "░") + (" !" if over else "")


def won(amount: int) -> str:
    return f"{amount:,}원"


def signed_won(amount: int) -> str:
    sign = "+" if amount >= 0 else "-"
    return f"{sign}{abs(amount):,}원"


def section(title: str, width: int = 56) -> str:
    return f"\n== {title} " + "=" * max(0, width - display_width(title) - 4)
