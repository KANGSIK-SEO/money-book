"""저장소(파일) 위에 도메인 연산을 얹은 리포지토리 계층.

CLI/서비스는 파일 포맷을 몰라도 되고, 여기만 Transaction/Category/Budget 를 안다.
"""

from __future__ import annotations

import re
from typing import Iterable, Iterator

from .errors import ConflictError, NotFoundError, ValidationError
from .models import Budget, Category, RecurringRule, Transaction
from .storage import DataDir

ID_PREFIX = "tx-"
ID_RE = re.compile(r"^tx-(\d+)$")

DEFAULT_CATEGORIES: list[dict] = [
    {"name": "식비", "scope": "expense", "description": "밥, 카페, 배달"},
    {"name": "교통", "scope": "expense", "description": "대중교통, 택시, 주유"},
    {"name": "주거", "scope": "expense", "description": "월세, 관리비, 공과금"},
    {"name": "통신", "scope": "expense", "description": "휴대폰, 인터넷"},
    {"name": "의료", "scope": "expense", "description": "병원, 약국"},
    {"name": "문화", "scope": "expense", "description": "영화, 도서, 취미"},
    {"name": "생활", "scope": "expense", "description": "생필품, 잡화"},
    {"name": "급여", "scope": "income", "description": "월급, 상여"},
    {"name": "부수입", "scope": "income", "description": "이자, 배당, 중고거래"},
    {"name": "기타", "scope": "both", "description": "분류되지 않은 항목"},
]


class TransactionRepository:
    def __init__(self, data: DataDir):
        self._store = data.transactions

    # ---- 조회 ---------------------------------------------------------
    def iter_all(self) -> Iterator[Transaction]:
        """제너레이터 스트리밍 조회."""
        for record in self._store.iter_raw():
            yield Transaction.from_dict(record)

    def count(self) -> int:
        return self._store.count()

    def find(self, id_or_prefix: str) -> Transaction:
        """전체 ID 또는 앞부분 일부(prefix)로 1건을 찾는다."""
        needle = (id_or_prefix or "").strip()
        if not needle:
            raise ValidationError("거래 ID가 비어 있습니다.", "예: update tx-00003")
        matches = [tx for tx in self.iter_all() if tx.id == needle or tx.id.startswith(needle)]
        if not matches:
            raise NotFoundError(
                f"거래를 찾을 수 없습니다: {needle}",
                "list 명령으로 ID를 먼저 확인하세요.",
            )
        if len(matches) > 1:
            sample = ", ".join(tx.id for tx in matches[:5])
            raise ConflictError(
                f"ID 앞자리 {needle!r} 에 해당하는 거래가 {len(matches)}건입니다.",
                f"더 길게 입력하세요. 후보: {sample}",
            )
        return matches[0]

    # ---- 생성 ---------------------------------------------------------
    def next_id(self) -> str:
        largest = 0
        for record in self._store.iter_raw():
            match = ID_RE.match(str(record.get("id", "")))
            if match:
                largest = max(largest, int(match.group(1)))
        return f"{ID_PREFIX}{largest + 1:05d}"

    def add(self, tx: Transaction) -> Transaction:
        self._store.append(tx.to_dict())
        return tx

    def add_many(self, transactions: Iterable[Transaction]) -> int:
        added = 0
        for tx in transactions:
            self._store.append(tx.to_dict())
            added += 1
        return added

    # ---- 수정/삭제 (임시파일 + rename 원자적 처리) ------------------------
    def update(self, tx_id: str, changes: dict) -> Transaction:
        target = self.find(tx_id)
        updated = Transaction.from_dict({**target.to_dict(), **changes})

        def transform(records):
            for record in records:
                if record.get("id") == target.id:
                    yield updated.to_dict()
                else:
                    yield record

        self._store.rewrite(transform)
        return updated

    def delete(self, tx_id: str) -> Transaction:
        target = self.find(tx_id)

        def transform(records):
            for record in records:
                if record.get("id") != target.id:
                    yield record

        self._store.rewrite(transform)
        return target

    # ---- 카테고리 연계 ---------------------------------------------------
    def usage_count(self, category: str) -> int:
        return sum(1 for tx in self.iter_all() if tx.category == category)

    def replace_category(self, old: str, new: str) -> int:
        moved = {"n": 0}

        def transform(records):
            for record in records:
                if record.get("category") == old:
                    record = {**record, "category": new}
                    moved["n"] += 1
                yield record

        self._store.rewrite(transform)
        return moved["n"]


class CategoryRepository:
    def __init__(self, data: DataDir):
        self._store = data.categories

    def iter_all(self) -> Iterator[Category]:
        for record in self._store.iter_raw():
            yield Category.from_dict(record)

    def as_map(self) -> dict[str, Category]:
        return {c.name: c for c in self.iter_all()}

    def names(self) -> list[str]:
        return [c.name for c in self.iter_all()]

    def get(self, name: str) -> Category:
        found = self.as_map().get(name)
        if not found:
            available = ", ".join(self.names()) or "(없음)"
            raise NotFoundError(
                f"등록되지 않은 카테고리입니다: {name!r}",
                f"category add --name {name} 로 먼저 등록하세요. 현재 목록: {available}",
            )
        return found

    def assert_usable(self, name: str, tx_type: str) -> Category:
        category = self.get(name)
        if not category.allows(tx_type):
            raise ValidationError(
                f"카테고리 {name!r} 는 {category.scope} 전용이라 {tx_type} 거래에 쓸 수 없습니다.",
                "category list 로 scope 를 확인하거나 다른 카테고리를 지정하세요.",
            )
        return category

    def add(self, category: Category) -> Category:
        if category.name in self.as_map():
            raise ConflictError(
                f"이미 존재하는 카테고리입니다: {category.name}",
                "category list 로 확인하세요.",
            )
        self._store.append(category.to_dict())
        return category

    def delete(self, name: str) -> Category:
        target = self.get(name)

        def transform(records):
            for record in records:
                if record.get("name") != name:
                    yield record

        self._store.rewrite(transform)
        return target


class BudgetRepository:
    def __init__(self, data: DataDir):
        self._store = data.budgets

    def iter_all(self) -> Iterator[Budget]:
        for record in self._store.iter_raw():
            yield Budget.from_dict(record)

    def set(self, budget: Budget) -> tuple[Budget, bool]:
        """upsert. (예산, 기존값_덮어썼는지) 반환."""
        replaced = {"hit": False}

        def transform(records):
            for record in records:
                existing = Budget.from_dict(record)
                if existing.key == budget.key:
                    replaced["hit"] = True
                    continue
                yield record
            yield budget.to_dict()

        self._store.rewrite(transform)
        return budget, replaced["hit"]

    def get(self, month: str, category: str | None = None) -> Budget | None:
        wanted = (month, category or "*")
        for budget in self.iter_all():
            if budget.key == wanted:
                return budget
        return None

    def for_month(self, month: str) -> list[Budget]:
        return [b for b in self.iter_all() if b.month == month]

    def delete(self, month: str, category: str | None = None) -> Budget:
        target = self.get(month, category)
        if not target:
            label = f"{month}" + (f" / {category}" if category else " 전체")
            raise NotFoundError(f"설정된 예산이 없습니다: {label}", "budget list 로 확인하세요.")

        def transform(records):
            for record in records:
                if Budget.from_dict(record).key != target.key:
                    yield record

        self._store.rewrite(transform)
        return target


class RecurringRepository:
    def __init__(self, data: DataDir):
        self._store = data.recurring

    def iter_all(self) -> Iterator[RecurringRule]:
        for record in self._store.iter_raw():
            yield RecurringRule.from_dict(record)

    def next_id(self) -> str:
        largest = 0
        for record in self._store.iter_raw():
            match = re.match(r"^rr-(\d+)$", str(record.get("id", "")))
            if match:
                largest = max(largest, int(match.group(1)))
        return f"rr-{largest + 1:03d}"

    def add(self, rule: RecurringRule) -> RecurringRule:
        self._store.append(rule.to_dict())
        return rule

    def delete(self, rule_id: str) -> RecurringRule:
        matches = [r for r in self.iter_all() if r.id == rule_id]
        if not matches:
            raise NotFoundError(f"반복 규칙을 찾을 수 없습니다: {rule_id}", "recurring list 로 확인하세요.")

        def transform(records):
            for record in records:
                if record.get("id") != rule_id:
                    yield record

        self._store.rewrite(transform)
        return matches[0]


class Context:
    """CLI 핸들러가 사용하는 리포지토리 묶음."""

    def __init__(self, data_dir: str, verbose: bool = False):
        self.data = DataDir(data_dir)
        self.verbose = verbose
        self.transactions = TransactionRepository(self.data)
        self.categories = CategoryRepository(self.data)
        self.budgets = BudgetRepository(self.data)
        self.recurring = RecurringRepository(self.data)

    def bootstrap(self, announce: bool = True) -> list[str]:
        created = self.data.bootstrap(DEFAULT_CATEGORIES)
        if created and announce:
            print(f"데이터 폴더를 초기화했습니다: {self.data.root}")
            for name in created:
                print(f"  + {name}")
            print()
        return created
