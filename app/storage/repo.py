"""存储：内存实现（骨架/测试）与 JSON 文件实现（跨进程持久化，供进度查询）。

后续替换为 PostgreSQL / MySQL 时，只需实现 save_case / get_case / list_cases。
"""
import json
from pathlib import Path

from ..models.schema import CaseRecord


class InMemoryRepo:
    def __init__(self):
        self._cases = {}

    def save_case(self, case):
        self._cases[case.case_id] = case

    def get_case(self, case_id):
        return self._cases.get(case_id)

    def list_cases(self):
        return list(self._cases.values())


class JsonFileRepo:
    """把办理单（含流程进度与并联状态）落盘为 JSON，支持跨进程按单号查询进度。"""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._cases = {}
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                raw = {}
            self._cases = {key: CaseRecord.from_dict(value) for key, value in raw.items()}

    def _flush(self):
        payload = {key: case.to_dict() for key, case in self._cases.items()}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_case(self, case):
        self._cases[case.case_id] = case
        self._flush()

    def get_case(self, case_id):
        return self._cases.get(case_id)

    def list_cases(self):
        return list(self._cases.values())
