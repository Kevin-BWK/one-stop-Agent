"""材料提交业务入口：产出材料清单 -> 逐项上传 -> 全部通过。

流程上材料提交**先于受理**：材料清单由条件判定算出，判定又依赖申请信息，
所以用户先填信息、拿到材料清单，逐项拍照上传，齐了才允许并联提交。
"""
from typing import Any, Dict, Optional

from ..agents.collect_agent import CollectAgent
from ..agents.condition_agent import ConditionAgent
from ..moma.client import MoMAClient
from ..moma.context import SessionContext
from ..models.schema import MaterialIntake
from . import spec as spec_rule
from .store import MaterialStore
from .verify import build_checker, check_file


class MaterialService:
    """材料清单、上传、撤回的统一入口（HTTP 层与编排层共用）。"""

    def __init__(self, store: Optional[MaterialStore] = None, moma=None, checker=None):
        self.store = store or MaterialStore()
        self.moma = moma or MoMAClient()
        # 内容核验器：配了多模态模型就走视觉核验，否则用桩规则（见 app/materials/verify.py）
        self.checker = checker or build_checker(
            self.moma, model=self.moma.dispatch("verify"), role="sub")

    # ---------- 材料清单 ----------

    def plan(self, scenario: Dict[str, Any], answers: Dict[str, Any]) -> MaterialIntake:
        """跑「信息采集 -> 条件判定」，产出材料清单并开一张材料收集单。"""
        context = SessionContext()
        form = CollectAgent(self.moma, context).collect(
            scenario["id"], scenario.get("collect_fields") or [], answers or {}
        )
        items, materials, notes = ConditionAgent(self.moma, context).evaluate(scenario, form)
        return self.plan_from_form(scenario, form, items, materials, notes)

    def plan_from_form(self, scenario: Dict[str, Any], form, items, materials,
                       notes) -> MaterialIntake:
        """已有表单与判定结果时直接开收集单。

        多轮会话路径（`/api/chat` + `/api/fields`）逐项采集完就已经有表单了，
        不必再跑一遍信息采集与条件判定。
        """
        return self.store.create(scenario["id"], form, list(items), list(materials), list(notes))

    def specs_of(self, scenario: Dict[str, Any], intake: MaterialIntake) -> list:
        return spec_rule.material_specs(scenario, intake.materials)

    def view(self, scenario: Dict[str, Any], intake: MaterialIntake) -> Dict[str, Any]:
        """材料区渲染所需的全部数据（清单 + 状态 + 已传文件）。"""
        specs = self.specs_of(scenario, intake)
        return {
            "intake_id": intake.intake_id,
            "scenario_id": intake.scenario_id,
            "items": list(intake.items),
            "notes": list(intake.notes),
            "summary": spec_rule.summary(specs, intake.files),
            "materials": [self._material_view(intake, spec) for spec in specs],
        }

    def _material_view(self, intake: MaterialIntake, spec: Dict[str, Any]) -> Dict[str, Any]:
        files = intake.files_of(spec["id"])
        return {
            "id": spec["id"],
            "name": spec["name"],
            "reason": spec["reason"],
            "form": spec["form"],
            "accept": spec["accept"],
            "slots": spec["slots"],
            "multiple": spec["multiple"],
            "max_files": spec["max_files"],
            "required": spec["required"],
            "status": spec_rule.status_of(spec, files),
            "missing_slots": spec_rule.missing_slots(spec, files),
            "files": [self._file_view(intake, spec["id"], item) for item in files],
        }

    @staticmethod
    def _file_view(intake: MaterialIntake, material_id: str, record) -> Dict[str, Any]:
        data = record.to_dict()
        data["url"] = (
            "/api/materials/" + intake.intake_id + "/" + material_id + "/files/" + record.file_id
        )
        return data

    def brief(self, scenario: Dict[str, Any], intake: MaterialIntake) -> str:
        """对话区播报：逐项说明要什么、为什么、怎么给。"""
        specs = self.specs_of(scenario, intake)
        return "\n".join(spec_rule.describe_lines(specs))

    # ---------- 上传 / 撤回 ----------

    def upload(self, scenario: Dict[str, Any], intake: MaterialIntake, material_id: str,
               filename: str, content_type: str, content: bytes, slot: str = "") -> Dict[str, Any]:
        spec = self._spec(scenario, intake, material_id)
        slot = (slot or "").strip()
        files = intake.files_of(material_id)
        reason = spec_rule.reject_reason(spec, files, slot)
        if reason:
            raise ValueError(reason)

        verdict = check_file(spec, filename, content, slot=slot, checker=self.checker)
        if verdict["result"] == "不通过":
            raise ValueError(verdict["reason"])

        # 同一槽位上次没通过的那张先撤掉，避免越积越多
        self.store.remove_needs_fix(intake, material_id, slot)
        self.store.add_file(
            intake, material_id, filename, content_type, content,
            slot=slot, status=verdict["status"], reason=verdict["reason"],
        )
        return self.view(scenario, intake)

    def remove(self, scenario: Dict[str, Any], intake: MaterialIntake,
               material_id: str, file_id: str) -> Dict[str, Any]:
        if not self.store.remove_file(intake, material_id, file_id):
            raise KeyError("找不到这张文件，可能已经被撤回了。")
        return self.view(scenario, intake)

    def _spec(self, scenario: Dict[str, Any], intake: MaterialIntake,
              material_id: str) -> Dict[str, Any]:
        for spec in self.specs_of(scenario, intake):
            if spec["id"] == material_id:
                return spec
        raise KeyError("这次办理不需要「" + str(material_id) + "」这份材料。")
