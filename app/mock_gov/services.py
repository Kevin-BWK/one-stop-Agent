"""政务系统 Mock：模拟市场监管/税务/消防/城管/卫健等并联办理。"""
import time
from ..models.schema import CaseRecord


class MockGovServices:
    def __init__(self):
        self._seq = 0

    def submit(self, scenario_id, items, materials, form):
        self._seq += 1
        case_id = "YJS" + str(self._seq).zfill(4)
        item_status = {item: "已受理" for item in items}
        return CaseRecord(
            case_id=case_id,
            scenario_id=scenario_id,
            form=form,
            items=items,
            materials=materials,
            verify_report={},
            item_status=item_status,
            created_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        )

    def advance(self, case):
        """模拟推进：把各事项推进到下一状态。"""
        stages = ["已受理", "办理中", "现场核查", "已办结"]
        for item in list(case.item_status.keys()):
            cur = case.item_status[item]
            idx = stages.index(cur) if cur in stages else 0
            if idx < len(stages) - 1:
                case.item_status[item] = stages[idx + 1]
        return case
