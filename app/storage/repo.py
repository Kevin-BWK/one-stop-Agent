"""存储：内存实现（骨架/测试）与 JSON 文件实现（跨进程持久化，供进度查询）。

接口定义见 `app/storage/base.py`；生产替换为 PostgreSQL / MySQL 时，
只需实现 `CaseRepo` 的三个方法（`save_case` / `get_case` / `list_cases`），
再经 `build_storage` 注入（其余组件也要一并注入，见 `app/storage/factory.py`）：

    storage = build_storage("sql", cases=SqlCaseRepo(dsn), sessions=...,
                            users=..., ids=..., materials=...)
    app = create_app(storage=storage)
"""
from pathlib import Path
from typing import Any, List, Optional

from ..models.schema import CaseRecord
from .atomic import read_json, write_json
from .base import CaseRepo


class InMemoryRepo(CaseRepo):
    """进程内办理单表（测试 / 单进程演示用）。"""

    def __init__(self):
        self._cases = {}

    def save_case(self, case) -> None:
        self._cases[case.case_id] = case

    def get_case(self, case_id: str) -> Optional[CaseRecord]:
        return self._cases.get(case_id)

    def list_cases(self, owner_id: Optional[str] = None) -> List[CaseRecord]:
        cases = list(self._cases.values())
        if owner_id:
            return [case for case in cases if case.owner_id == owner_id]
        return cases


class JsonFileRepo(CaseRepo):
    """把办理单（含流程进度与并联状态）落盘为 JSON，支持跨进程按单号查询进度。

    写盘用原子替换（见 `app/storage/atomic.py`）：读方不会读到半截 JSON。
    多进程**并发写**仍会丢更新，生产请换数据库（见 `docs/10` 第 4 条）。
    """

    def __init__(self, path):
        self.path = Path(path)
        self._cases = {}
        for key, value in (read_json(self.path, {}) or {}).items():
            try:
                self._cases[key] = CaseRecord.from_dict(value)
            except (KeyError, TypeError, ValueError):
                continue

    def _flush(self) -> None:
        write_json(self.path, {key: case.to_dict() for key, case in self._cases.items()})

    def save_case(self, case) -> None:
        self._cases[case.case_id] = case
        self._flush()

    def get_case(self, case_id: str) -> Optional[CaseRecord]:
        return self._cases.get(case_id)

    def list_cases(self, owner_id: Optional[str] = None) -> List[CaseRecord]:
        cases = list(self._cases.values())
        if owner_id:
            return [case for case in cases if case.owner_id == owner_id]
        return cases
