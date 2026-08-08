"""도메인 모델 (dataclass 기반).

저장 포맷은 JSONL이므로, 각 모델은 dict <-> 객체 변환을 스스로 책임진다.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime

from .errors import StorageError

INCOME = "income"
EXPENSE = "expense"
TX_TYPES = (INCOME, EXPENSE)

CATEGORY_SCOPES = (INCOME, EXPENSE, "both")


def _require(d: dict, key: str, where: str):
    if key not in d:
        raise StorageError(
            f"{where} 레코드에 필수 필드 '{key}'가 없습니다.",
            "파일이 손상되었을 수 있습니다. backup 명령으로 백업본을 확인하세요.",
        )
    return d[key]


@dataclass
class Transaction:
    """거래 1건.

    필드: id, type, date, amount, category, memo, tags
    """

    id: str
    type: str          # income | expense
    date: str          # YYYY-MM-DD
    amount: int        # 원 단위 양의 정수
    category: str
    memo: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: str = ""

    # ---- 파생 속성 ---------------------------------------------------
    @property
    def month(self) -> str:
        return self.date[:7]

    @property
    def signed_amount(self) -> int:
        return self.amount if self.type == INCOME else -self.amount

    def matches_keyword(self, keyword: str) -> bool:
        kw = keyword.lower()
        haystack = " ".join([self.memo, self.category, " ".join(self.tags), self.id])
        return kw in haystack.lower()

    # ---- 직렬화 -------------------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Transaction":
        return cls(
            id=str(_require(d, "id", "transactions")),
            type=str(_require(d, "type", "transactions")),
            date=str(_require(d, "date", "transactions")),
            amount=int(_require(d, "amount", "transactions")),
            category=str(_require(d, "category", "transactions")),
            memo=str(d.get("memo", "")),
            tags=list(d.get("tags", []) or []),
            created_at=str(d.get("created_at", "")),
        )

    @classmethod
    def new(cls, *, tx_id: str, type_: str, date: str, amount: int,
            category: str, memo: str = "", tags: list[str] | None = None) -> "Transaction":
        return cls(
            id=tx_id,
            type=type_,
            date=date,
            amount=amount,
            category=category,
            memo=memo,
            tags=list(tags or []),
            created_at=datetime.now().isoformat(timespec="seconds"),
        )


@dataclass
class Category:
    """카테고리 1건. scope 로 수입/지출 전용 여부를 구분한다."""

    name: str
    scope: str = "both"     # income | expense | both
    description: str = ""

    def allows(self, tx_type: str) -> bool:
        return self.scope == "both" or self.scope == tx_type

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Category":
        return cls(
            name=str(_require(d, "name", "categories")),
            scope=str(d.get("scope", "both")),
            description=str(d.get("description", "")),
        )


@dataclass
class Budget:
    """월별 예산. category 가 None 이면 그 달의 전체 예산."""

    month: str                    # YYYY-MM
    amount: int
    category: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.month, self.category or "*")

    @property
    def is_total(self) -> bool:
        return self.category is None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Budget":
        cat = d.get("category")
        return cls(
            month=str(_require(d, "month", "budgets")),
            amount=int(_require(d, "amount", "budgets")),
            category=str(cat) if cat else None,
        )


@dataclass
class RecurringRule:
    """(보너스) 매월 반복되는 고정 수입/지출 규칙."""

    id: str
    type: str
    day: int          # 1~31, 말일 초과 시 해당 월 마지막 날로 보정
    amount: int
    category: str
    memo: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RecurringRule":
        return cls(
            id=str(_require(d, "id", "recurring")),
            type=str(_require(d, "type", "recurring")),
            day=int(_require(d, "day", "recurring")),
            amount=int(_require(d, "amount", "recurring")),
            category=str(_require(d, "category", "recurring")),
            memo=str(d.get("memo", "")),
            tags=list(d.get("tags", []) or []),
        )
