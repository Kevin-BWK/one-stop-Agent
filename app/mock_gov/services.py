"""政务系统 Mock：模拟市场监管/税务/消防/城管/卫健等并联办理。

事项状态由对应部门子 Agent 的办理结果驱动：
提交 -> 受理 -> 部门子 Agent 开始办理 -> 办结后回调主 Agent 更新状态。

单号由 `IdAllocator` 生成（见 `app/storage/ids.py`）：进程内实现用于 Demo，
落盘 / 数据库实现用于多进程——多进程并发提交不会再重号。
"""
import time

from ..models.schema import CaseRecord
from ..storage.ids import IdAllocator, InMemoryIdAllocator, sequence_of


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


class MockGovServices:
    # 并联事项的办理状态流转
    STAGES = ["已受理", "办理中", "已办结"]

    def __init__(self, ids: IdAllocator = None):
        self.ids = ids if ids is not None else InMemoryIdAllocator()

    def sync_from(self, cases):
        """对齐已有办理单的单号序列，避免持久化后重号覆盖。"""
        self.ids.reserve("YJS", max([sequence_of(case.case_id) for case in cases] or [0]))
        return self

    def submit(self, scenario_id, items, materials, form, verify_report=None,
               owner_id: str = ""):
        case_id = self.ids.next("YJS", 4)
        item_status = {item: self.STAGES[0] for item in items}
        created = _now()
        return CaseRecord(
            case_id=case_id,
            scenario_id=scenario_id,
            form=form,
            items=items,
            materials=materials,
            verify_report=dict(verify_report or {}),
            item_status=item_status,
            flow=[],
            created_at=created,
            updated_at=created,
            owner_id=owner_id,
        )

    def start(self, case, item_id):
        """部门受理并开始办理该事项。"""
        case.item_status[item_id] = self.STAGES[1]
        case.updated_at = _now()
        return case

    def finish(self, case, item_id, status: str = None):
        """部门办结该事项（默认推进到末态）。"""
        case.item_status[item_id] = status or self.STAGES[-1]
        case.updated_at = _now()
        return case

    def is_finished(self, case) -> bool:
        """并联事项是否全部办结。"""
        status = case.item_status
        return bool(status) and all(value == self.STAGES[-1] for value in status.values())
