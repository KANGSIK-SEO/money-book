"""JSONL 파일 저장소 계층.

설계 포인트
- 읽기는 항상 '한 줄 = 한 레코드' 제너레이터 스트리밍 (파일 전체를 메모리에 올리지 않음)
- 수정/삭제는 임시 파일에 쓰고 os.replace 로 교체 -> 중간에 죽어도 원본이 깨지지 않음
- 파싱 실패 시 줄 번호를 포함한 StorageError
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Iterator

from .errors import StorageError

DEFAULT_DATA_DIR = Path("./data")


class JsonlStore:
    """JSON Lines 파일 하나를 담당하는 저장소."""

    def __init__(self, path: Path, label: str):
        self.path = Path(path)
        self.label = label

    # ---- 준비 ---------------------------------------------------------
    def ensure(self, seed: Iterable[dict] | None = None) -> bool:
        """파일이 없으면 만든다. seed 가 있으면 초기 데이터를 넣는다.

        Returns: 새로 생성했으면 True
        """
        if self.path.exists():
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", encoding="utf-8") as fp:
                for record in seed or []:
                    fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            raise StorageError(
                f"{self.label} 파일을 만들 수 없습니다: {self.path}",
                f"상위 폴더 권한을 확인하세요. (원인: {exc.strerror})",
            ) from None
        return True

    # ---- 읽기 ---------------------------------------------------------
    def iter_raw(self) -> Iterator[dict]:
        """파일을 스트리밍하며 dict 를 하나씩 yield 한다."""
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as fp:
                for lineno, line in enumerate(fp, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise StorageError(
                            f"{self.label} 파일 {lineno}번째 줄을 읽을 수 없습니다: {exc.msg}",
                            f"{self.path} 의 해당 줄을 수정하거나 삭제한 뒤 다시 실행하세요.",
                        ) from None
                    if not isinstance(record, dict):
                        raise StorageError(
                            f"{self.label} 파일 {lineno}번째 줄이 객체(JSON object)가 아닙니다.",
                            "각 줄은 {\"...\": ...} 형태여야 합니다.",
                        )
                    yield record
        except UnicodeDecodeError:
            raise StorageError(
                f"{self.label} 파일 인코딩이 UTF-8 이 아닙니다: {self.path}",
                "UTF-8 로 저장한 뒤 다시 시도하세요.",
            ) from None

    def count(self) -> int:
        return sum(1 for _ in self.iter_raw())

    # ---- 쓰기 ---------------------------------------------------------
    def append(self, record: dict) -> None:
        self.ensure()
        try:
            with self.path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(record, ensure_ascii=False) + "\n")
                fp.flush()
                os.fsync(fp.fileno())
        except OSError as exc:
            raise StorageError(
                f"{self.label} 파일에 쓸 수 없습니다: {self.path}",
                f"디스크 여유 공간과 권한을 확인하세요. (원인: {exc.strerror})",
            ) from None

    def rewrite(self, transform: Callable[[Iterator[dict]], Iterator[dict]]) -> None:
        """전체 재작성(원자적).

        transform 은 '읽기 제너레이터'를 받아 '쓸 레코드 제너레이터'를 돌려주는 함수.
        임시 파일에 모두 쓴 뒤 os.replace 로 한 번에 교체한다.
        """
        self.ensure()
        tmp_path = self.path.with_name(self.path.name + ".tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as fp:
                for record in transform(self.iter_raw()):
                    fp.write(json.dumps(record, ensure_ascii=False) + "\n")
                fp.flush()
                os.fsync(fp.fileno())
            os.replace(tmp_path, self.path)   # 원자적 교체
        except OSError as exc:
            tmp_path.unlink(missing_ok=True)
            raise StorageError(
                f"{self.label} 파일을 갱신하지 못했습니다: {self.path}",
                f"원본은 그대로 보존되었습니다. (원인: {exc.strerror})",
            ) from None
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise

    def replace_all(self, records: Iterable[dict]) -> None:
        self.rewrite(lambda _existing: iter(list(records)))


class DataDir:
    """데이터 폴더와 그 안의 저장소 파일들을 묶어서 관리."""

    FILES = {
        "transactions": "transactions.jsonl",
        "categories": "categories.jsonl",
        "budgets": "budgets.jsonl",
        "recurring": "recurring.jsonl",
    }

    def __init__(self, root: str | Path = DEFAULT_DATA_DIR):
        self.root = Path(root).expanduser()
        self.transactions = JsonlStore(self.root / self.FILES["transactions"], "transactions")
        self.categories = JsonlStore(self.root / self.FILES["categories"], "categories")
        self.budgets = JsonlStore(self.root / self.FILES["budgets"], "budgets")
        self.recurring = JsonlStore(self.root / self.FILES["recurring"], "recurring")

    def all_stores(self) -> list[JsonlStore]:
        return [self.transactions, self.categories, self.budgets, self.recurring]

    def bootstrap(self, default_categories: Iterable[dict]) -> list[str]:
        """최초 실행 시 폴더와 파일을 자동 생성하고, 생성된 항목명을 돌려준다."""
        created: list[str] = []
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError(
                f"데이터 폴더를 만들 수 없습니다: {self.root}",
                f"경로와 권한을 확인하거나 --data-dir 로 다른 위치를 지정하세요. (원인: {exc.strerror})",
            ) from None

        if self.categories.ensure(default_categories):
            created.append(self.categories.path.name + " (기본 카테고리 포함)")
        for store in (self.transactions, self.budgets, self.recurring):
            if store.ensure():
                created.append(store.path.name)
        return created

    def backup(self, dest: str | Path | None = None) -> Path:
        """(보너스) 데이터 폴더 전체를 타임스탬프 폴더로 복사."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = Path(dest) if dest else self.root.parent / f"backup-{self.root.name}-{stamp}"
        try:
            target.mkdir(parents=True, exist_ok=True)
            for store in self.all_stores():
                if store.path.exists():
                    shutil.copy2(store.path, target / store.path.name)
        except OSError as exc:
            raise StorageError(
                f"백업을 만들지 못했습니다: {target}",
                f"대상 경로 권한을 확인하세요. (원인: {exc.strerror})",
            ) from None
        return target
