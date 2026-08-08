"""CLI 계층: argparse 정의 + 서브커맨드 핸들러.

실행: python -m budget_app <command> [options]
모든 명령은 --help 를 지원한다.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from . import ai_advice as AI
from . import services as S
from . import validators as V
from .decorators import command, confirm, handle_errors, timed
from .errors import AbortError, AppError, ValidationError
from .models import Budget, Category, RecurringRule, Transaction
from .repositories import Context
from .tableview import (LEFT, RIGHT, bar, render_table, section, signed_won, won)

ENV_DATA_DIR = "BUDGET_APP_DATA_DIR"
DEFAULT_DATA_DIR = os.environ.get(ENV_DATA_DIR, "./data")


# =====================================================================
# 대화형 입력 헬퍼
# =====================================================================
def ask(label: str, *, default: str | None = None, validator=None, required: bool = True):
    """검증에 통과할 때까지 다시 묻는 입력 헬퍼."""
    if not sys.stdin.isatty() and default in (None, "") and required:
        raise AbortError(
            f"대화형 입력을 받을 수 없습니다: {label}",
            "비대화형 환경에서는 --type, --amount, --category 옵션을 모두 지정하세요.",
        )
    while True:
        suffix = f" [{default}]" if default not in (None, "") else ""
        try:
            raw = input(f"  {label}{suffix}: ").strip()
        except EOFError:
            raise AbortError("입력이 중단되었습니다.",
                             "비대화형 실행이라면 옵션으로 값을 지정하세요. (예: --amount 12000)") from None
        if not raw and default not in (None, ""):
            raw = str(default)
        if not raw and not required:
            return validator("") if validator else ""
        if not raw:
            print("    값을 입력해 주세요.")
            continue
        if validator is None:
            return raw
        try:
            return validator(raw)
        except ValidationError as exc:
            print(f"    {exc.message}")
            if exc.hint:
                print(f"    힌트: {exc.hint}")


def choose_category(ctx: Context, tx_type: str) -> str:
    categories = [c for c in ctx.categories.iter_all() if c.allows(tx_type)]
    if not categories:
        raise ValidationError(
            f"{tx_type} 에 사용할 수 있는 카테고리가 없습니다.",
            "category add --name <이름> --scope <income|expense|both> 로 먼저 등록하세요.",
        )
    print("  사용 가능한 카테고리:")
    for index, category in enumerate(categories, start=1):
        note = f" - {category.description}" if category.description else ""
        print(f"    {index}) {category.name}{note}")
    names = [c.name for c in categories]

    def validate(raw: str) -> str:
        if raw.isdigit() and 1 <= int(raw) <= len(names):
            return names[int(raw) - 1]
        name = V.validate_category_name(raw)
        if name not in names:
            raise ValidationError(
                f"목록에 없는 카테고리입니다: {name}",
                f"번호(1~{len(names)}) 또는 목록의 이름을 입력하세요.",
            )
        return name

    return ask("카테고리(번호 또는 이름)", validator=validate)


def transaction_rows(transactions: list[Transaction]) -> str:
    rows = []
    for tx in transactions:
        rows.append([
            tx.id,
            tx.date,
            "수입" if tx.type == "income" else "지출",
            tx.category,
            signed_won(tx.signed_amount),
            tx.memo or "-",
            ",".join(tx.tags) or "-",
        ])
    return render_table(
        ["ID", "날짜", "구분", "카테고리", "금액", "메모", "태그"],
        rows,
        aligns=[LEFT, LEFT, LEFT, LEFT, RIGHT, LEFT, LEFT],
        max_widths=[0, 0, 0, 14, 0, 28, 20],
    )


def print_transactions(transactions: list[Transaction], header: str) -> None:
    print(header)
    if not transactions:
        print("  조건에 맞는 거래가 없습니다.")
        return
    print(transaction_rows(transactions))
    income = sum(t.amount for t in transactions if t.type == "income")
    expense = sum(t.amount for t in transactions if t.type == "expense")
    print(f"\n  {len(transactions)}건 | 수입 {won(income)} / 지출 {won(expense)} / 합계 {signed_won(income - expense)}")


# =====================================================================
# 핸들러
# =====================================================================
@command("add")
@timed
def cmd_add(args, ctx: Context) -> int:
    """대화형(옵션이 주어지면 해당 항목은 건너뜀)으로 거래를 추가한다.

    type/amount/category 가 모두 옵션으로 주어지면 완전 비대화형으로 동작한다
    (스크립트·배치 입력용). 이때 date 는 오늘, memo/tags 는 빈 값이 기본이다.
    """
    batch = all([args.type, args.amount, args.category])
    if batch:
        args.date = args.date or "today"
        args.memo = args.memo if args.memo is not None else ""
        args.tags = args.tags if args.tags is not None else ""
    else:
        print("거래 추가 (Ctrl+C 로 취소)")

    tx_type = V.validate_type(args.type) if args.type else ask(
        "구분 (income/expense)", default="expense", validator=V.validate_type)
    date = V.validate_date(args.date) if args.date else ask(
        "날짜 (YYYY-MM-DD)", default="today", validator=V.validate_date)
    amount = V.validate_amount(args.amount) if args.amount else ask(
        "금액 (원)", validator=V.validate_amount)

    if args.category:
        category = V.validate_category_name(args.category)
    else:
        category = choose_category(ctx, tx_type)
    ctx.categories.assert_usable(category, tx_type)

    memo = V.validate_memo(args.memo) if args.memo is not None else ask(
        "메모 (선택)", validator=V.validate_memo, required=False)
    tags = V.parse_tags(args.tags) if args.tags is not None else V.parse_tags(
        ask("태그 (선택, 쉼표 구분)", validator=None, required=False))

    tx = Transaction.new(
        tx_id=ctx.transactions.next_id(),
        type_=tx_type, date=date, amount=amount,
        category=category, memo=memo, tags=tags,
    )
    ctx.transactions.add(tx)

    print(f"\n저장 완료: {tx.id}")
    print(transaction_rows([tx]))

    # 예산 경고
    summary = S.summarize_month(ctx, tx.month)
    for status in S.budget_statuses(ctx, tx.month, summary):
        if status.label in ("전체", tx.category) and status.ratio >= 0.7:
            print(f"  [예산 {status.state}] {status.label}: "
                  f"{won(status.used)} / {won(status.budget)} ({status.ratio * 100:.0f}%)")
    return 0


@command("list")
@timed
def cmd_list(args, ctx: Context) -> int:
    """최신순 목록. --limit 은 heapq 로 상위 N개만 메모리에 유지."""
    limit = V.validate_positive_int(args.limit, field_name="limit") if args.limit else None
    flt = S.build_filter(month=args.month, ctx=ctx)
    transactions = S.latest(ctx, flt, limit)
    suffix = f" (최근 {limit}건)" if limit else ""
    scope = f" / {args.month}" if args.month else ""
    print_transactions(transactions, f"거래 목록{suffix}{scope}")
    return 0


@command("search")
@timed
def cmd_search(args, ctx: Context) -> int:
    limit = V.validate_positive_int(args.limit, field_name="limit") if args.limit else None
    flt = S.build_filter(
        date_from=getattr(args, "from"), date_to=args.to, category=args.category,
        tx_type=args.type, keyword=args.q, tag=args.tag, ctx=ctx,
    )
    transactions = S.latest(ctx, flt, limit)
    print_transactions(transactions, f"검색 결과 — {flt.describe()}")
    return 0


@command("summary")
@timed
def cmd_summary(args, ctx: Context) -> int:
    month = V.validate_month(args.month) if args.month else V.validate_month("this")
    top_n = V.validate_positive_int(args.top, field_name="top", maximum=50) if args.top else 5
    summary = S.summarize_month(ctx, month)

    print(section(f"{month} 월별 요약"))
    print(f"  거래 건수 : {summary.count}건")
    print(f"  수입      : {won(summary.income)}")
    print(f"  지출      : {won(summary.expense)}")
    print(f"  잔액      : {signed_won(summary.net)}")

    if summary.count == 0:
        print("\n  해당 월 거래가 없습니다. add 명령으로 먼저 기록해 보세요.")
        return 0

    top_expense = summary.top_expense(top_n)
    if top_expense:
        print(section(f"지출 TOP {len(top_expense)}"))
        rows = []
        for name, amount in top_expense:
            ratio = amount / summary.expense if summary.expense else 0
            rows.append([name, won(amount), f"{ratio * 100:5.1f}%", bar(ratio, 16)])
        print(render_table(["카테고리", "금액", "비중", "그래프"], rows,
                           aligns=[LEFT, RIGHT, RIGHT, LEFT]))

    top_income = summary.top_income(top_n)
    if top_income:
        print(section(f"수입 TOP {len(top_income)}"))
        rows = [[name, won(amount)] for name, amount in top_income]
        print(render_table(["카테고리", "금액"], rows, aligns=[LEFT, RIGHT]))

    statuses = S.budget_statuses(ctx, month, summary)
    if statuses:
        print(section("예산 대비"))
        rows = []
        for status in statuses:
            rows.append([
                status.label, won(status.budget), won(status.used),
                signed_won(status.remaining), f"{status.ratio * 100:5.1f}%",
                status.state, bar(status.ratio, 14),
            ])
        print(render_table(["대상", "예산", "사용", "남음", "소진율", "상태", "그래프"], rows,
                           aligns=[LEFT, RIGHT, RIGHT, RIGHT, RIGHT, LEFT, LEFT]))
    else:
        print(f"\n  ({month} 예산 미설정 — budget set --month {month} --amount 500000)")

    busiest = summary.busiest_day()
    if busiest:
        print(f"\n  지출이 가장 많았던 날: {busiest[0]} ({won(busiest[1])})")
    return 0


@command("ai-advice")
@timed
def cmd_ai_advice(args, ctx: Context) -> int:
    """개별 거래 대신 월별 집계만 OpenAI에 보내 소비 조언을 생성한다."""
    month = V.validate_month(args.month) if args.month else V.validate_month("this")
    summary = S.summarize_month(ctx, month)
    if summary.count == 0:
        raise ValidationError(
            f"{month}에 분석할 거래가 없습니다.",
            "add 또는 import 명령으로 거래를 먼저 기록하세요.",
        )
    AI.load_env(Path(args.env_file).expanduser())
    max_tokens = V.validate_positive_int(
        args.max_output_tokens, field_name="max-output-tokens", maximum=4000)
    print(section(f"{month} AI 소비 조언"))
    print(AI.generate_advice(
        summary,
        S.budget_statuses(ctx, month, summary),
        model=args.model,
        max_output_tokens=max_tokens,
    ))
    print("\n  ※ 개인 거래 메모·날짜가 아닌 월별 집계만 전송되었습니다.")
    return 0


@command("budget")
@timed
def cmd_budget(args, ctx: Context) -> int:
    action = args.budget_action

    if action == "set":
        month = V.validate_month(args.month)
        amount = V.validate_amount(args.amount)
        category = None
        if args.category:
            category = V.validate_category_name(args.category)
            ctx.categories.get(category)
        budget, replaced = ctx.budgets.set(Budget(month=month, amount=amount, category=category))
        label = category or "전체"
        verb = "수정" if replaced else "설정"
        print(f"예산 {verb} 완료: {month} / {label} = {won(budget.amount)}")
        return 0

    if action == "delete":
        month = V.validate_month(args.month)
        category = V.validate_category_name(args.category) if args.category else None
        removed = ctx.budgets.delete(month, category)
        print(f"예산 삭제 완료: {removed.month} / {removed.category or '전체'}")
        return 0

    if action == "list":
        budgets = sorted(ctx.budgets.iter_all(), key=lambda b: (b.month, b.category or ""))
        if not budgets:
            print("설정된 예산이 없습니다. 예: budget set --month 2026-08 --amount 500000")
            return 0
        rows = [[b.month, b.category or "전체", won(b.amount)] for b in budgets]
        print(render_table(["월", "대상", "예산"], rows, aligns=[LEFT, LEFT, RIGHT]))
        return 0

    # show (기본)
    month = V.validate_month(args.month) if args.month else V.validate_month("this")
    summary = S.summarize_month(ctx, month)
    statuses = S.budget_statuses(ctx, month, summary)
    if not statuses:
        print(f"{month} 에 설정된 예산이 없습니다.")
        print(f"  힌트: budget set --month {month} --amount 500000")
        return 0
    rows = []
    for status in statuses:
        rows.append([status.label, won(status.budget), won(status.used),
                     signed_won(status.remaining), f"{status.ratio * 100:5.1f}%",
                     status.state, bar(status.ratio, 14)])
    print(f"{month} 예산 현황")
    print(render_table(["대상", "예산", "사용", "남음", "소진율", "상태", "그래프"], rows,
                       aligns=[LEFT, RIGHT, RIGHT, RIGHT, RIGHT, LEFT, LEFT]))
    return 0


@command("category")
@timed
def cmd_category(args, ctx: Context) -> int:
    action = args.category_action

    if action == "add":
        name = V.validate_category_name(args.name)
        scope = V.validate_scope(args.scope)
        description = V.validate_memo(args.description or "")
        ctx.categories.add(Category(name=name, scope=scope, description=description))
        print(f"카테고리 추가 완료: {name} (scope={scope})")
        return 0

    if action == "delete":
        name = V.validate_category_name(args.name)
        ctx.categories.get(name)
        used = ctx.transactions.usage_count(name)
        if used and not args.replace_with:
            raise AppError(
                f"카테고리 {name!r} 는 거래 {used}건에서 사용 중이라 삭제할 수 없습니다.",
                f"--replace-with <대체카테고리> 를 지정하면 거래를 옮긴 뒤 삭제합니다.",
            )
        if used:
            replacement = V.validate_category_name(args.replace_with)
            if replacement == name:
                raise ValidationError("대체 카테고리가 삭제 대상과 같습니다.", "다른 이름을 지정하세요.")
            ctx.categories.get(replacement)
            moved = ctx.transactions.replace_category(name, replacement)
            print(f"거래 {moved}건을 {name} -> {replacement} 로 이동했습니다.")
        ctx.categories.delete(name)
        print(f"카테고리 삭제 완료: {name}")
        return 0

    # list (기본)
    categories = list(ctx.categories.iter_all())
    if not categories:
        print("등록된 카테고리가 없습니다. 예: category add --name 식비 --scope expense")
        return 0
    usage: dict[str, int] = {}
    for tx in ctx.transactions.iter_all():
        usage[tx.category] = usage.get(tx.category, 0) + 1
    rows = [[c.name, c.scope, str(usage.get(c.name, 0)), c.description or "-"] for c in categories]
    print(render_table(["이름", "scope", "사용건수", "설명"], rows,
                       aligns=[LEFT, LEFT, RIGHT, LEFT], max_widths=[0, 0, 0, 30]))
    return 0


@command("update")
@timed
def cmd_update(args, ctx: Context) -> int:
    target = ctx.transactions.find(args.id)
    changes: dict = {}

    if args.type:
        changes["type"] = V.validate_type(args.type)
    if args.date:
        changes["date"] = V.validate_date(args.date)
    if args.amount:
        changes["amount"] = V.validate_amount(args.amount)
    if args.category:
        changes["category"] = V.validate_category_name(args.category)
    if args.memo is not None:
        changes["memo"] = V.validate_memo(args.memo)
    if args.tags is not None:
        changes["tags"] = V.parse_tags(args.tags)

    if not changes:
        raise ValidationError(
            "수정할 항목이 없습니다.",
            "--amount, --date, --category, --memo, --tags, --type 중 하나 이상을 지정하세요.",
        )

    final_type = changes.get("type", target.type)
    final_category = changes.get("category", target.category)
    ctx.categories.assert_usable(final_category, final_type)

    print("변경 전:")
    print(transaction_rows([target]))
    updated = ctx.transactions.update(target.id, changes)
    print("\n변경 후:")
    print(transaction_rows([updated]))
    return 0


@command("delete")
@timed
@confirm("이 거래를 삭제할까요?")
def cmd_delete(args, ctx: Context) -> int:
    target = ctx.transactions.find(args.id)
    removed = ctx.transactions.delete(target.id)
    print(f"삭제 완료: {removed.id} ({removed.date} {removed.category} {won(removed.amount)})")
    return 0


@command("export")
@timed
def cmd_export(args, ctx: Context) -> int:
    flt = S.build_filter(
        date_from=getattr(args, "from"), date_to=args.to,
        month=args.month, category=args.category, tx_type=args.type, ctx=ctx,
    )
    path = Path(args.file)
    written = S.export_csv(ctx, path, flt)
    print(f"CSV 내보내기 완료: {path} ({written}건)")
    print(f"  컬럼: {', '.join(S.CSV_FIELDS)} (tags 구분자 '{S.TAG_SEP}')")
    return 0


@command("import")
@timed
def cmd_import(args, ctx: Context) -> int:
    report = S.import_csv(ctx, Path(args.file),
                          dry_run=args.dry_run,
                          create_categories=args.create_categories)
    mode = "[미리보기] " if args.dry_run else ""
    print(f"{mode}가져오기 결과: 총 {report.total}행 / 성공 {report.imported}건 / 실패 {report.skipped}건")
    if report.created_categories:
        print(f"  자동 생성된 카테고리: {', '.join(report.created_categories)}")
    if report.errors:
        print("  건너뛴 행:")
        for message in report.errors[:20]:
            print(f"    - {message}")
        if len(report.errors) > 20:
            print(f"    ... 외 {len(report.errors) - 20}건")
    if args.dry_run:
        print("  실제로 저장하려면 --dry-run 없이 다시 실행하세요.")
    return 0


@command("backup")
@timed
def cmd_backup(args, ctx: Context) -> int:
    target = ctx.data.backup(args.dest)
    print(f"백업 완료: {target}")
    for path in sorted(target.iterdir()):
        print(f"  - {path.name} ({path.stat().st_size:,} bytes)")
    return 0


@command("recurring")
@timed
def cmd_recurring(args, ctx: Context) -> int:
    action = args.recurring_action

    if action == "add":
        tx_type = V.validate_type(args.type)
        category = V.validate_category_name(args.category)
        ctx.categories.assert_usable(category, tx_type)
        rule = RecurringRule(
            id=ctx.recurring.next_id(),
            type=tx_type,
            day=V.validate_positive_int(args.day, field_name="day", minimum=1, maximum=31),
            amount=V.validate_amount(args.amount),
            category=category,
            memo=V.validate_memo(args.memo or ""),
            tags=V.parse_tags(args.tags),
        )
        ctx.recurring.add(rule)
        print(f"반복 규칙 추가: {rule.id} (매월 {rule.day}일 {category} {won(rule.amount)})")
        return 0

    if action == "delete":
        removed = ctx.recurring.delete(args.id)
        print(f"반복 규칙 삭제: {removed.id}")
        return 0

    if action == "apply":
        month = V.validate_month(args.month) if args.month else V.validate_month("this")
        created = S.apply_recurring(ctx, month, dry_run=args.dry_run)
        if not created:
            print(f"{month} 에 새로 생성할 반복 거래가 없습니다. (이미 적용되었을 수 있습니다)")
            return 0
        prefix = "[미리보기] " if args.dry_run else ""
        print(f"{prefix}{month} 반복 거래 {len(created)}건")
        print(transaction_rows(created))
        return 0

    rules = list(ctx.recurring.iter_all())
    if not rules:
        print("등록된 반복 규칙이 없습니다.")
        print("  예: recurring add --type expense --day 25 --amount 55000 --category 통신 --memo 휴대폰")
        return 0
    rows = [[r.id, "수입" if r.type == "income" else "지출", f"매월 {r.day}일",
             r.category, won(r.amount), r.memo or "-"] for r in rules]
    print(render_table(["ID", "구분", "주기", "카테고리", "금액", "메모"], rows,
                       aligns=[LEFT, LEFT, LEFT, LEFT, RIGHT, LEFT]))
    return 0


@command("info")
@timed
def cmd_info(args, ctx: Context) -> int:
    print(f"budget_app v{__version__}")
    print(f"  데이터 폴더 : {ctx.data.root.resolve()}")
    for store in ctx.data.all_stores():
        exists = "O" if store.path.exists() else "X"
        size = store.path.stat().st_size if store.path.exists() else 0
        print(f"  [{exists}] {store.path.name:<22} {store.count():>5}건  {size:>8,} bytes")
    months = S.iter_months(ctx.transactions.iter_all())
    if months:
        print(f"  기록된 월    : {months[0]} ~ {months[-1]} ({len(months)}개월)")
    return 0


# =====================================================================
# 파서
# =====================================================================
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m budget_app",
        description="파일 기반 가계부 콘솔 프로그램 (표준 라이브러리만 사용)",
        epilog=(
            "예시:\n"
            "  python -m budget_app add\n"
            "  python -m budget_app list --limit 10\n"
            "  python -m budget_app search --from 2026-08-01 --to 2026-08-31 --category 식비\n"
            "  python -m budget_app summary --month 2026-08 --top 5\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR,
                        help=f"데이터 폴더 (기본: {DEFAULT_DATA_DIR}, 환경변수 {ENV_DATA_DIR})")
    parser.add_argument("--verbose", action="store_true", help="실행 시간 등 상세 로그 출력")
    parser.add_argument("--debug", action="store_true", help="예기치 못한 오류의 스택트레이스 표시")
    parser.add_argument("--version", action="version", version=f"budget_app {__version__}")

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # add
    p_add = sub.add_parser("add", help="거래 추가 (대화형)",
                           description="대화형으로 거래를 추가합니다. 옵션을 주면 해당 질문은 건너뜁니다.")
    p_add.add_argument("--type", help="income 또는 expense")
    p_add.add_argument("--date", help="YYYY-MM-DD (today 가능)")
    p_add.add_argument("--amount", help="금액(원)")
    p_add.add_argument("--category", help="카테고리명")
    p_add.add_argument("--memo", help="메모")
    p_add.add_argument("--tags", help="태그 (쉼표 구분)")

    # list
    p_list = sub.add_parser("list", help="거래 목록 (최신순)")
    p_list.add_argument("--limit", help="출력 개수 제한")
    p_list.add_argument("--month", help="특정 월만 보기 (YYYY-MM)")

    # search
    p_search = sub.add_parser("search", help="조건 검색")
    p_search.add_argument("--from", dest="from", help="시작일 YYYY-MM-DD")
    p_search.add_argument("--to", help="종료일 YYYY-MM-DD")
    p_search.add_argument("--category", help="카테고리")
    p_search.add_argument("--type", help="income / expense")
    p_search.add_argument("--q", help="메모·카테고리·태그 키워드")
    p_search.add_argument("--tag", help="태그")
    p_search.add_argument("--limit", help="출력 개수 제한")

    # summary
    p_summary = sub.add_parser("summary", help="월별 요약")
    p_summary.add_argument("--month", help="YYYY-MM (기본: 이번 달)")
    p_summary.add_argument("--top", help="카테고리 상위 N개 (기본 5)")

    # ai-advice
    p_ai = sub.add_parser("ai-advice", help="OpenAI 기반 월별 소비 분석")
    p_ai.add_argument("--month", help="YYYY-MM (기본: 이번 달)")
    p_ai.add_argument("--model", default=AI.DEFAULT_MODEL,
                      help=f"OpenAI 모델 (기본: {AI.DEFAULT_MODEL})")
    p_ai.add_argument("--max-output-tokens", default="700",
                      help="최대 출력 토큰 (기본: 700)")
    p_ai.add_argument("--env-file", default=".env",
                      help="API 키 환경변수 파일 (기본: .env)")

    # budget
    p_budget = sub.add_parser("budget", help="예산 설정/조회")
    budget_sub = p_budget.add_subparsers(dest="budget_action", metavar="<action>")
    b_set = budget_sub.add_parser("set", help="예산 설정")
    b_set.add_argument("--month", required=True, help="YYYY-MM")
    b_set.add_argument("--amount", required=True, help="예산 금액")
    b_set.add_argument("--category", help="카테고리별 예산 (생략 시 전체 예산)")
    b_show = budget_sub.add_parser("show", help="예산 현황")
    b_show.add_argument("--month", help="YYYY-MM (기본: 이번 달)")
    budget_sub.add_parser("list", help="전체 예산 목록")
    b_del = budget_sub.add_parser("delete", help="예산 삭제")
    b_del.add_argument("--month", required=True, help="YYYY-MM")
    b_del.add_argument("--category", help="카테고리별 예산 삭제")

    # category
    p_category = sub.add_parser("category", help="카테고리 관리")
    category_sub = p_category.add_subparsers(dest="category_action", metavar="<action>")
    category_sub.add_parser("list", help="카테고리 목록")
    c_add = category_sub.add_parser("add", help="카테고리 추가")
    c_add.add_argument("--name", required=True)
    c_add.add_argument("--scope", default="both", help="income / expense / both")
    c_add.add_argument("--description", help="설명")
    c_del = category_sub.add_parser("delete", help="카테고리 삭제")
    c_del.add_argument("--name", required=True)
    c_del.add_argument("--replace-with", dest="replace_with",
                       help="사용 중일 때 거래를 옮길 대체 카테고리")

    # update
    p_update = sub.add_parser("update", help="거래 수정")
    p_update.add_argument("id", help="거래 ID (앞자리만 입력해도 됨)")
    p_update.add_argument("--type")
    p_update.add_argument("--date")
    p_update.add_argument("--amount")
    p_update.add_argument("--category")
    p_update.add_argument("--memo")
    p_update.add_argument("--tags")

    # delete
    p_delete = sub.add_parser("delete", help="거래 삭제")
    p_delete.add_argument("id", help="거래 ID")
    p_delete.add_argument("--yes", action="store_true", help="확인 없이 삭제")

    # export
    p_export = sub.add_parser("export", help="CSV 내보내기")
    p_export.add_argument("--file", required=True, help="저장할 CSV 경로")
    p_export.add_argument("--from", dest="from")
    p_export.add_argument("--to")
    p_export.add_argument("--month")
    p_export.add_argument("--category")
    p_export.add_argument("--type")

    # import
    p_import = sub.add_parser("import", help="CSV 가져오기")
    p_import.add_argument("--file", required=True, help="읽을 CSV 경로")
    p_import.add_argument("--dry-run", dest="dry_run", action="store_true",
                          help="저장하지 않고 검증만")
    p_import.add_argument("--create-categories", dest="create_categories", action="store_true",
                          help="없는 카테고리를 자동 생성")

    # backup
    p_backup = sub.add_parser("backup", help="데이터 폴더 백업 (보너스)")
    p_backup.add_argument("--dest", help="백업 위치 (기본: backup-<data>-<타임스탬프>)")

    # recurring
    p_recurring = sub.add_parser("recurring", help="반복 거래 규칙 (보너스)")
    recurring_sub = p_recurring.add_subparsers(dest="recurring_action", metavar="<action>")
    recurring_sub.add_parser("list", help="규칙 목록")
    r_add = recurring_sub.add_parser("add", help="규칙 추가")
    r_add.add_argument("--type", required=True)
    r_add.add_argument("--day", required=True, help="매월 실행일 1~31")
    r_add.add_argument("--amount", required=True)
    r_add.add_argument("--category", required=True)
    r_add.add_argument("--memo")
    r_add.add_argument("--tags")
    r_del = recurring_sub.add_parser("delete", help="규칙 삭제")
    r_del.add_argument("id")
    r_apply = recurring_sub.add_parser("apply", help="해당 월에 규칙 적용")
    r_apply.add_argument("--month", help="YYYY-MM (기본: 이번 달)")
    r_apply.add_argument("--dry-run", dest="dry_run", action="store_true")

    # info
    sub.add_parser("info", help="데이터 파일 상태 확인")

    return parser


@handle_errors
def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    ctx = Context(args.data_dir, verbose=args.verbose)
    ctx.bootstrap()

    # 서브커맨드 기본 액션 보정
    if args.command == "budget" and not getattr(args, "budget_action", None):
        args.budget_action = "show"
        args.month = getattr(args, "month", None)
    if args.command == "category" and not getattr(args, "category_action", None):
        args.category_action = "list"
    if args.command == "recurring" and not getattr(args, "recurring_action", None):
        args.recurring_action = "list"

    handlers = {
        "add": cmd_add, "list": cmd_list, "search": cmd_search, "summary": cmd_summary,
        "ai-advice": cmd_ai_advice,
        "budget": cmd_budget, "category": cmd_category, "update": cmd_update,
        "delete": cmd_delete, "export": cmd_export, "import": cmd_import,
        "backup": cmd_backup, "recurring": cmd_recurring, "info": cmd_info,
    }
    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return 0
    return handler(args, ctx) or 0


if __name__ == "__main__":
    sys.exit(main())
