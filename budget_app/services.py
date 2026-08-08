"""비즈니스 로직 계층.

- 필터링/정렬 (제너레이터 스트리밍 + heapq 로 메모리 상한 유지)
- 월별 요약 및 예산 대비 계산
- CSV import / export
- (보너스) 반복 거래 규칙 적용
"""

from __future__ import annotations

import calendar
import csv
import heapq
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from . import validators as V
from .errors import StorageError, ValidationError
from .models import EXPENSE, INCOME, RecurringRule, Transaction
from .repositories import Context

CSV_FIELDS = ["date", "type", "category", "amount", "memo", "tags"]
TAG_SEP = ";"


# ---------------------------------------------------------------------
# 필터 / 정렬
# ---------------------------------------------------------------------
@dataclass
class Filter:
    date_from: str | None = None
    date_to: str | None = None
    category: str | None = None
    type: str | None = None
    keyword: str | None = None
    tag: str | None = None

    def match(self, tx: Transaction) -> bool:
        if self.date_from and tx.date < self.date_from:
            return False
        if self.date_to and tx.date > self.date_to:
            return False
        if self.category and tx.category != self.category:
            return False
        if self.type and tx.type != self.type:
            return False
        if self.tag and self.tag not in tx.tags:
            return False
        if self.keyword and not tx.matches_keyword(self.keyword):
            return False
        return True

    def describe(self) -> str:
        parts = []
        if self.date_from:
            parts.append(f"from={self.date_from}")
        if self.date_to:
            parts.append(f"to={self.date_to}")
        if self.type:
            parts.append(f"type={self.type}")
        if self.category:
            parts.append(f"category={self.category}")
        if self.tag:
            parts.append(f"tag={self.tag}")
        if self.keyword:
            parts.append(f"q={self.keyword}")
        return ", ".join(parts) if parts else "(조건 없음)"


def _sort_key(tx: Transaction):
    # 날짜 우선, 같은 날짜면 ID 순 -> 최신순 정렬에 사용
    return (tx.date, tx.id)


def stream_filtered(ctx: Context, flt: Filter) -> Iterator[Transaction]:
    """조건에 맞는 거래를 스트리밍으로 흘려보낸다."""
    for tx in ctx.transactions.iter_all():
        if flt.match(tx):
            yield tx


def latest(ctx: Context, flt: Filter, limit: int | None) -> list[Transaction]:
    """최신순 조회.

    limit 이 있으면 heapq.nlargest 로 상위 N개만 메모리에 유지한다
    (전체 파일을 리스트로 올리지 않음).
    """
    stream = stream_filtered(ctx, flt)
    if limit is None:
        return sorted(stream, key=_sort_key, reverse=True)
    return heapq.nlargest(limit, stream, key=_sort_key)


# ---------------------------------------------------------------------
# 요약
# ---------------------------------------------------------------------
@dataclass
class MonthlySummary:
    month: str
    income: int = 0
    expense: int = 0
    count: int = 0
    by_category: dict[str, int] = None          # 지출 카테고리별 합계
    by_income_category: dict[str, int] = None
    daily_expense: dict[str, int] = None

    @property
    def net(self) -> int:
        return self.income - self.expense

    def top_expense(self, top_n: int) -> list[tuple[str, int]]:
        items = sorted((self.by_category or {}).items(), key=lambda kv: kv[1], reverse=True)
        return items[:top_n]

    def top_income(self, top_n: int) -> list[tuple[str, int]]:
        items = sorted((self.by_income_category or {}).items(), key=lambda kv: kv[1], reverse=True)
        return items[:top_n]

    def busiest_day(self) -> tuple[str, int] | None:
        if not self.daily_expense:
            return None
        return max(self.daily_expense.items(), key=lambda kv: kv[1])


def summarize_month(ctx: Context, month: str) -> MonthlySummary:
    start, end = V.month_range(month)
    summary = MonthlySummary(month=month, by_category={}, by_income_category={}, daily_expense={})
    for tx in stream_filtered(ctx, Filter(date_from=start, date_to=end)):
        summary.count += 1
        if tx.type == INCOME:
            summary.income += tx.amount
            summary.by_income_category[tx.category] = \
                summary.by_income_category.get(tx.category, 0) + tx.amount
        else:
            summary.expense += tx.amount
            summary.by_category[tx.category] = summary.by_category.get(tx.category, 0) + tx.amount
            summary.daily_expense[tx.date] = summary.daily_expense.get(tx.date, 0) + tx.amount
    return summary


@dataclass
class BudgetStatus:
    label: str
    budget: int
    used: int

    @property
    def ratio(self) -> float:
        return self.used / self.budget if self.budget else 0.0

    @property
    def remaining(self) -> int:
        return self.budget - self.used

    @property
    def state(self) -> str:
        if self.ratio > 1.0:
            return "초과"
        if self.ratio >= 0.9:
            return "위험"
        if self.ratio >= 0.7:
            return "주의"
        return "양호"


def budget_statuses(ctx: Context, month: str, summary: MonthlySummary) -> list[BudgetStatus]:
    statuses: list[BudgetStatus] = []
    for budget in ctx.budgets.for_month(month):
        if budget.is_total:
            statuses.append(BudgetStatus("전체", budget.amount, summary.expense))
        else:
            used = (summary.by_category or {}).get(budget.category, 0)
            statuses.append(BudgetStatus(budget.category, budget.amount, used))
    statuses.sort(key=lambda s: (s.label != "전체", -s.ratio))
    return statuses


# ---------------------------------------------------------------------
# CSV import / export
# ---------------------------------------------------------------------
def export_csv(ctx: Context, path: Path, flt: Filter) -> int:
    path = Path(path)
    if path.parent and not path.parent.exists():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError(
                f"내보내기 폴더를 만들 수 없습니다: {path.parent}",
                f"경로/권한을 확인하세요. (원인: {exc.strerror})",
            ) from None

    tmp = path.with_name(path.name + ".tmp")
    written = 0
    try:
        with tmp.open("w", encoding="utf-8-sig", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for tx in sorted(stream_filtered(ctx, flt), key=_sort_key):
                writer.writerow({
                    "date": tx.date,
                    "type": tx.type,
                    "category": tx.category,
                    "amount": tx.amount,
                    "memo": tx.memo,
                    "tags": TAG_SEP.join(tx.tags),
                })
                written += 1
        tmp.replace(path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise StorageError(
            f"CSV 를 저장하지 못했습니다: {path}",
            f"디스크 공간/권한을 확인하세요. (원인: {exc.strerror})",
        ) from None
    return written


@dataclass
class ImportReport:
    total: int = 0
    imported: int = 0
    skipped: int = 0
    errors: list[str] = None
    created_categories: list[str] = None


def import_csv(ctx: Context, path: Path, *, dry_run: bool = False,
               create_categories: bool = False) -> ImportReport:
    from .models import Category  # 지역 import: 순환 참조 방지

    path = Path(path)
    if not path.exists():
        raise StorageError(
            f"가져올 CSV 파일이 없습니다: {path}",
            "경로를 확인하거나 export 로 만든 파일을 지정하세요.",
        )

    report = ImportReport(errors=[], created_categories=[])
    known = ctx.categories.as_map()
    pending: list[Transaction] = []
    next_number = int(ctx.transactions.next_id().split("-")[1])

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fp:
            reader = csv.DictReader(fp)
            missing = [c for c in CSV_FIELDS if c not in (reader.fieldnames or [])]
            if missing:
                raise ValidationError(
                    f"CSV 헤더에 필수 컬럼이 없습니다: {', '.join(missing)}",
                    f"헤더는 {','.join(CSV_FIELDS)} 여야 합니다.",
                )
            for lineno, row in enumerate(reader, start=2):
                report.total += 1
                try:
                    tx_type = V.validate_type(row.get("type", ""))
                    category = V.validate_category_name(row.get("category", ""))
                    if category not in known:
                        if not create_categories:
                            raise ValidationError(
                                f"등록되지 않은 카테고리: {category}",
                                "--create-categories 옵션을 쓰면 자동 등록합니다.",
                            )
                        new_category = Category(name=category, scope="both",
                                                description="CSV import 자동 생성")
                        known[category] = new_category
                        report.created_categories.append(category)
                        if not dry_run:
                            ctx.categories.add(new_category)
                    elif not known[category].allows(tx_type):
                        raise ValidationError(
                            f"카테고리 {category!r} 는 {tx_type} 거래에 사용할 수 없습니다.",
                            "category list 로 scope 를 확인하세요.",
                        )

                    tx = Transaction.new(
                        tx_id=f"tx-{next_number:05d}",
                        type_=tx_type,
                        date=V.validate_date(row.get("date", "")),
                        amount=V.validate_amount(row.get("amount", "")),
                        category=category,
                        memo=V.validate_memo(row.get("memo", "")),
                        tags=V.parse_tags(row.get("tags", "")),
                    )
                    pending.append(tx)
                    next_number += 1
                except ValidationError as exc:
                    report.skipped += 1
                    report.errors.append(f"{lineno}행: {exc.message}")
    except UnicodeDecodeError:
        raise StorageError(
            f"CSV 인코딩을 읽을 수 없습니다: {path}",
            "UTF-8 로 저장한 뒤 다시 시도하세요.",
        ) from None

    if not dry_run and pending:
        report.imported = ctx.transactions.add_many(pending)
    elif dry_run:
        report.imported = len(pending)
    return report


# ---------------------------------------------------------------------
# (보너스) 반복 거래
# ---------------------------------------------------------------------
def apply_recurring(ctx: Context, month: str, *, dry_run: bool = False) -> list[Transaction]:
    month = V.validate_month(month)
    year, mon = int(month[:4]), int(month[5:7])
    last_day = calendar.monthrange(year, mon)[1]

    start, end = V.month_range(month)
    existing_marks = {
        tag for tx in stream_filtered(ctx, Filter(date_from=start, date_to=end))
        for tag in tx.tags if tag.startswith("rr:")
    }

    created: list[Transaction] = []
    next_number = int(ctx.transactions.next_id().split("-")[1])
    for rule in ctx.recurring.iter_all():
        mark = f"rr:{rule.id}"
        if mark in existing_marks:
            continue
        day = min(rule.day, last_day)
        tx = Transaction.new(
            tx_id=f"tx-{next_number:05d}",
            type_=rule.type,
            date=f"{month}-{day:02d}",
            amount=rule.amount,
            category=rule.category,
            memo=rule.memo or f"반복 거래 {rule.id}",
            tags=list(dict.fromkeys([*rule.tags, mark])),
        )
        created.append(tx)
        next_number += 1

    if created and not dry_run:
        ctx.transactions.add_many(created)
    return created


def build_filter(*, date_from=None, date_to=None, month=None, category=None,
                 tx_type=None, keyword=None, tag=None, ctx: Context | None = None) -> Filter:
    """CLI 인자 -> 검증된 Filter."""
    if month:
        start, end = V.month_range(month)
        date_from, date_to = start, end
    date_from, date_to = V.validate_date_range(date_from, date_to)
    if category:
        category = V.validate_category_name(category)
        if ctx:
            ctx.categories.get(category)   # 없으면 힌트와 함께 오류
    if tx_type:
        tx_type = V.validate_type(tx_type)
    tags = V.parse_tags(tag) if tag else []
    return Filter(
        date_from=date_from,
        date_to=date_to,
        category=category,
        type=tx_type,
        keyword=(keyword or "").strip() or None,
        tag=tags[0] if tags else None,
    )


def iter_months(transactions: Iterable[Transaction]) -> list[str]:
    seen: dict[str, int] = {}
    for tx in transactions:
        seen[tx.month] = seen.get(tx.month, 0) + 1
    return sorted(seen)
