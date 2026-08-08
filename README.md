# budget_app — 파일 기반 가계부 콘솔 프로그램

Python 표준 라이브러리만으로 만든 CLI 가계부입니다.
거래 CRUD, 검색, 월별 요약, 예산, 카테고리 관리, CSV import/export를 지원하며
데이터는 JSONL 파일로 저장합니다.

- **개발 환경**: Python 3.10 이상 / 외부 패키지 0개 (표준 라이브러리만)
- **실행 형태**: `python -m budget_app <command> [options]`

---

## 1. 빠른 시작

```bash
# 0) 클론
git clone https://github.com/KANGSIK-SEO/money-book.git
cd money-book

# 1) 파이썬 버전 확인 (3.10+)
python3 --version

# 2) 바로 실행 (설치·의존성 없음)
python3 -m budget_app info          # 최초 실행 시 ./data 폴더와 파일이 자동 생성됩니다

# 3) 샘플 데이터 넣고 둘러보기
python3 -m budget_app import --file examples/sample.csv
python3 -m budget_app summary --month 2026-08

# 4) 전체 기능 데모 (별도 폴더 ./demo-data 사용)
bash demo.sh
```

데이터 폴더는 기본값이 `./data` 이며, `--data-dir` 옵션이나 환경변수
`BUDGET_APP_DATA_DIR` 로 바꿀 수 있습니다.

```bash
python3 -m budget_app --data-dir ~/ledger list
export BUDGET_APP_DATA_DIR=~/ledger
```

---

## 2. 프로젝트 구조

```
money-book/
├── budget_app/
│   ├── __init__.py         버전 정보
│   ├── __main__.py         python -m budget_app 진입점
│   ├── cli.py              argparse 정의 + 서브커맨드 핸들러 (표현 계층)
│   ├── services.py         필터/요약/예산계산/CSV import·export (로직 계층)
│   ├── repositories.py     Transaction·Category·Budget·Recurring 리포지토리
│   ├── storage.py          JSONL 저장소 (스트리밍 읽기 + 원자적 쓰기)
│   ├── models.py           dataclass 도메인 모델
│   ├── validators.py       입력 검증 (날짜/금액/타입/카테고리/태그)
│   ├── decorators.py       handle_errors, timed, confirm, command
│   ├── tableview.py        한글 폭 계산 기반 표 렌더링 (외부 라이브러리 없음)
│   └── errors.py           원인+힌트를 담는 예외 계층
├── examples/sample.csv     import 예제 데이터
├── demo.sh                 전 기능 시연 스크립트
└── README.md
```

계층은 **CLI → services → repositories → storage** 한 방향으로만 의존합니다.
CLI는 파일 포맷을 모르고, storage는 도메인 모델을 모릅니다.

---

## 3. 명령어 레퍼런스

모든 명령은 `--help` 를 지원합니다. (`python3 -m budget_app search --help`)

### 전역 옵션

| 옵션 | 설명 |
|---|---|
| `--data-dir PATH` | 데이터 폴더 (기본 `./data`) |
| `--verbose` | 명령별 실행 시간을 stderr에 출력 |
| `--debug` | 예기치 못한 오류의 스택트레이스 표시 |
| `--version` | 버전 출력 |

### add — 거래 추가 (대화형)

```bash
python3 -m budget_app add
```

```
거래 추가 (Ctrl+C 로 취소)
  구분 (income/expense) [expense]: expense
  날짜 (YYYY-MM-DD) [today]: 2026-08-03
  금액 (원): 12,000
  사용 가능한 카테고리:
    1) 식비 - 밥, 카페, 배달
    2) 교통 - 대중교통, 택시, 주유
    ...
  카테고리(번호 또는 이름): 1
  메모 (선택): 점심 김치찌개
  태그 (선택, 쉼표 구분): 점심,회사

저장 완료: tx-00001
   ID        날짜     구분  카테고리    금액         메모         태그
--------  ----------  ----  --------  ---------  -------------  ---------
tx-00001  2026-08-03  지출  식비      -12,000원  점심 김치찌개  점심,회사
```

- 잘못 입력하면 그 항목만 다시 묻습니다 (`12,000`, `12000원`, `today` 모두 허용).
- `--type`, `--amount`, `--category` 를 모두 옵션으로 주면 질문 없이 바로 저장합니다(배치용).
- 저장 후 해당 월 예산 소진율이 70% 이상이면 경고를 함께 출력합니다.

### list — 목록 (최신순)

```bash
python3 -m budget_app list --limit 5
python3 -m budget_app list --month 2026-08
```

### search — 조건 검색

```bash
python3 -m budget_app search --from 2026-08-01 --to 2026-08-31 --type expense --q 식
python3 -m budget_app search --tag 고정 --limit 10
```

| 옵션 | 설명 |
|---|---|
| `--from`, `--to` | 기간 (YYYY-MM-DD) |
| `--category` | 카테고리 |
| `--type` | income / expense |
| `--q` | 메모·카테고리·태그 키워드 |
| `--tag` | 태그 |
| `--limit` | 출력 개수 |

### summary — 월별 요약

```bash
python3 -m budget_app summary --month 2026-08 --top 5
```

```
== 2026-08 월별 요약 =====================================
  거래 건수 : 10건
  수입      : 3,320,000원
  지출      : 1,047,650원
  잔액      : +2,272,350원

== 지출 TOP 4 ============================================
카테고리    금액      비중        그래프
--------  ---------  ------  ----------------
주거      850,000원   81.1%  █████████████░░░
생활       76,000원    7.3%  █░░░░░░░░░░░░░░░
통신       55,000원    5.2%  █░░░░░░░░░░░░░░░
식비       46,300원    4.4%  █░░░░░░░░░░░░░░░

== 예산 대비 =============================================
대상     예산         사용         남음     소진율  상태      그래프
----  -----------  -----------  ----------  ------  ----  --------------
전체  1,500,000원  1,047,650원  +452,350원   69.8%  양호  ██████████░░░░
식비    200,000원     46,300원  +153,700원   23.2%  양호  ███░░░░░░░░░░░

  지출이 가장 많았던 날: 2026-08-01 (850,000원)
```

### budget — 예산 설정/조회

```bash
python3 -m budget_app budget set --month 2026-08 --amount 1500000
python3 -m budget_app budget set --month 2026-08 --amount 200000 --category 식비
python3 -m budget_app budget show --month 2026-08     # 인자 없이 budget 만 써도 동일
python3 -m budget_app budget list
python3 -m budget_app budget delete --month 2026-08 --category 식비
```

전체 예산과 카테고리별 예산을 함께 관리하며, 소진율에 따라 `양호 / 주의(70%) / 위험(90%) / 초과` 상태를 표시합니다.

### category — 카테고리 관리

```bash
python3 -m budget_app category list
python3 -m budget_app category add --name 카페 --scope expense --description "커피 전용"
python3 -m budget_app category delete --name 문화 --replace-with 기타
```

- `scope` 는 `income` / `expense` / `both`. scope가 맞지 않는 거래에는 사용할 수 없습니다.
- **사용 중인 카테고리는 그냥 삭제되지 않습니다.** `--replace-with` 로 대체 카테고리를 지정하면
  해당 거래들을 옮긴 뒤 삭제합니다.

```
[오류] 카테고리 '식비' 는 거래 2건에서 사용 중이라 삭제할 수 없습니다.
  힌트: --replace-with <대체카테고리> 를 지정하면 거래를 옮긴 뒤 삭제합니다.
```

### update / delete — 수정·삭제

```bash
python3 -m budget_app update tx-00004 --amount 5500 --memo "라떼로 변경" --tags 카페,오전
python3 -m budget_app delete tx-00010            # y/N 확인
python3 -m budget_app delete tx-00010 --yes      # 확인 생략
```

ID는 앞자리만 입력해도 됩니다. 후보가 여러 개면 목록을 힌트로 보여줍니다.
`update` 는 변경 전/후를 나란히 출력합니다.

### import / export — CSV 주고받기

```bash
python3 -m budget_app export --file backup-2026-08.csv --month 2026-08
python3 -m budget_app import --file examples/sample.csv --dry-run
python3 -m budget_app import --file examples/sample.csv --create-categories
```

CSV 스키마(고정): `date,type,category,amount,memo,tags`
`tags` 는 `;` 로 구분합니다. 인코딩은 `UTF-8 with BOM`(엑셀 호환).

한 행이 잘못돼도 전체가 실패하지 않고, 유효한 행만 넣은 뒤 실패 행을 보고합니다.

```
가져오기 결과: 총 3행 / 성공 1건 / 실패 2건
  자동 생성된 카테고리: 커피
  건너뛴 행:
    - 3행: 존재하지 않는 날짜입니다: '2026-13-01'
    - 4행: date 형식이 올바르지 않습니다: 'bad'
```

### 그 밖의 명령

```bash
python3 -m budget_app info                      # 데이터 파일 상태
python3 -m budget_app backup --dest ./bk        # 데이터 폴더 백업
python3 -m budget_app recurring add --type expense --day 25 --amount 55000 --category 통신
python3 -m budget_app recurring apply --month 2026-09
```

`recurring apply` 는 생성된 거래에 `rr:<규칙ID>` 태그를 남겨, 같은 달에 두 번 실행해도
중복 생성되지 않습니다.

---

## 4. 데이터 파일

기본 폴더 `./data` 아래에 JSON Lines 파일 4개가 생성됩니다.

| 파일 | 내용 |
|---|---|
| `transactions.jsonl` | 거래 |
| `categories.jsonl` | 카테고리 (최초 실행 시 기본 10개 자동 생성) |
| `budgets.jsonl` | 월별/카테고리별 예산 |
| `recurring.jsonl` | 반복 거래 규칙 (보너스) |

```jsonl
{"id": "tx-00001", "type": "expense", "date": "2026-08-03", "amount": 12000, "category": "식비", "memo": "점심 김치찌개", "tags": ["점심", "회사"], "created_at": "2026-08-08T12:00:00"}
{"name": "식비", "scope": "expense", "description": "밥, 카페, 배달"}
{"month": "2026-08", "amount": 1500000, "category": null}
```

JSONL을 고른 이유: 한 줄이 한 레코드라 **추가는 append 한 줄**이면 되고,
읽기는 파일 전체를 메모리에 올리지 않고 스트리밍할 수 있으며,
중간 한 줄이 깨져도 몇 번째 줄인지 정확히 지적할 수 있습니다.

---

## 5. 설계 포인트

### 제너레이터 스트리밍
`JsonlStore.iter_raw()` 는 파일을 한 줄씩 읽어 `yield` 합니다.
`list --limit N` 은 `heapq.nlargest` 를 써서 **상위 N개만 메모리에 유지**하므로,
거래가 수십만 건이어도 사용 메모리는 N에 비례합니다.

```python
def latest(ctx, flt, limit):
    stream = stream_filtered(ctx, flt)          # 제너레이터
    if limit is None:
        return sorted(stream, key=_sort_key, reverse=True)
    return heapq.nlargest(limit, stream, key=_sort_key)
```

### 임시 파일 + rename 원자성
수정·삭제·예산 upsert는 `*.jsonl.tmp` 에 전부 쓴 뒤 `os.replace()` 로 한 번에 교체합니다.
쓰는 도중 프로세스가 죽어도 원본 파일은 손상되지 않습니다.

```python
def rewrite(self, transform):
    tmp = self.path.with_name(self.path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as fp:
        for record in transform(self.iter_raw()):
            fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        fp.flush(); os.fsync(fp.fileno())
    os.replace(tmp, self.path)     # 원자적 교체
```

### 데코레이터 (실제 적용)

| 데코레이터 | 위치 | 역할 |
|---|---|---|
| `@handle_errors` | `main()` | 스택트레이스 대신 원인+힌트 출력, 종료코드 매핑 |
| `@timed` | 모든 서브커맨드 핸들러 | `--verbose` 일 때만 실행 시간 측정 |
| `@confirm(...)` | `cmd_delete` | 파괴적 명령 실행 전 y/N 확인 (`--yes` 로 생략) |
| `@command(name)` | 각 핸들러 | 서브커맨드 이름 → 핸들러 레지스트리 |

### 오류 처리
모든 예상된 오류는 `AppError(message, hint)` 계층으로 던지고, `@handle_errors` 가
사람이 읽는 형태로 변환합니다. 종료 코드도 원인별로 구분됩니다.

| 코드 | 의미 |
|---|---|
| 0 | 성공 (또는 사용자가 확인 단계에서 취소) |
| 1 | 일반 오류 |
| 2 | 입력 검증 실패 |
| 3 | 대상을 찾을 수 없음 |
| 4 | 상태 충돌 (중복, 사용 중 삭제, ID 모호) |
| 5 | 파일 입출력/파싱 실패 |
| 130 | Ctrl+C 중단 |

```
[오류] month 형식이 올바르지 않습니다: '2026-8'
  힌트: YYYY-MM 형식이어야 합니다. 예: --month 2026-08
```

### 한글 표 정렬
`unicodedata.east_asian_width` 로 글자별 실제 표시 폭(한글 2칸)을 계산해
외부 라이브러리 없이 열을 맞춥니다. 긴 메모는 폭 기준으로 잘라 `…` 를 붙입니다.

---

## 6. 요구사항 대응표

| 요구사항 | 구현 |
|---|---|
| `python -m budget_app <command>` | `budget_app/__main__.py` |
| 모든 명령 `--help` | argparse 서브파서 |
| `add` 대화형 입력 | `cli.ask()` / `cli.choose_category()` |
| 옵션 표기 `--` 통일 | 전 명령 동일 |
| Transaction 필드 7종 | `models.Transaction` (dataclass) |
| dataclass, 클래스 2개 이상 | Transaction, Category, Budget, RecurringRule, JsonlStore, DataDir, 리포지토리 4종, Context, Filter, MonthlySummary, BudgetStatus |
| 날짜·금액·type·category 검증 | `validators.py` |
| JSONL 저장 | `storage.JsonlStore` |
| 저장 파일 3개 이상 | transactions / categories / budgets / recurring |
| 기본 저장 폴더 `./data` | `storage.DEFAULT_DATA_DIR` |
| 최초 실행 시 파일 자동 생성 | `DataDir.bootstrap()` |
| 기본 카테고리 자동 생성 | `repositories.DEFAULT_CATEGORIES` (10개) |
| `list` 최신순·`--limit`·제너레이터 | `services.latest()` + `heapq.nlargest` |
| `search` 6개 필터 | `--from/--to/--category/--type/--q/--tag` |
| `summary --month --top` | `services.summarize_month()` |
| `budget set --month --amount` | `cmd_budget` |
| 사용 중 카테고리 삭제 차단/대체 | `cmd_category` + `replace_category()` |
| import/export CSV 스키마 | `services.CSV_FIELDS` |
| 데코레이터 실제 적용 | `decorators.py` 4종 |
| 스택트레이스 대신 원인+힌트 | `errors.py` + `@handle_errors` |
| 모듈 3개 이상 분리 | 10개 모듈 |

### 보너스 구현

- `backup` — 데이터 폴더 타임스탬프 백업
- `recurring` — 매월 반복되는 고정 수입/지출 규칙, 중복 방지 적용
- `tableview.py` — 외부 라이브러리 없는 표 정렬 + 막대그래프
- update/delete 임시 파일 + `os.replace` 원자성 강화
- `import --dry-run`, `--create-categories`
- ID 접두사 부분 입력(`tx-000` 처럼) 지원

---

## 7. 알려진 제약

- 동시에 여러 프로세스가 같은 데이터 폴더에 쓰는 상황은 가정하지 않았습니다(파일 잠금 없음).
- 금액은 원 단위 정수만 지원합니다(소수점·외화 없음).
- 거래 건수가 매우 많아지면 `summary` 는 해당 월 전체를 훑으므로 파일 크기에 비례해 느려집니다.
