"""多轮会话服务：把多 Agent 编排包装成可多轮驱动的状态机。

职责边界（重要）：
- 本服务只管**会话状态机**：会话与场景绑定、意图路由、字段逐项采集追问、材料清单产出、进度查询；
- **实际的办理（流程节点打勾、并联提交、各部门办结）统一由 `MainAgent` 跑**，
  入口是 `/apply`（带 `intake_id`）。本服务不再自己 `gov.submit`，
  否则两条路径会产出质量不一致的办理单（一条有流程节点与核验记录，一条没有）。

因此多轮办理的完整链路是：

    POST /api/session           建会话
    POST /api/fields   × N      逐项采集；最后一项返回 intake_id + 材料清单
    POST /api/materials/...     逐项上传材料
    POST /apply {intake_id}     跑完整编排，返回事件流
"""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.agents.condition_agent import ConditionAgent
from app.agents.consult_agent import ConsultAgent
from app.agents.progress_agent import ProgressAgent
from app.config import ROOT
from app.knowledge.retriever import KnowledgeBase
from app.materials.service import MaterialService
from app.materials.store import get_store
from app.moma.client import MoMAClient
from app.moma.context import SessionContext
from app.mock_gov.services import MockGovServices
from app.models.schema import ApplicationForm, CaseRecord, MaterialIntake
from app.orchestrator.router import route_intent
from app.storage.repo import InMemoryRepo


@dataclass
class SessionRecord:
    session_id: str
    scenario_id: str
    scenario: dict
    context: SessionContext
    form: ApplicationForm
    agents: Dict[str, Any]
    # 字段采齐后先产出材料清单（此时**尚未受理**）；材料齐备才由 /apply 生成 case
    intake: Optional[MaterialIntake] = None
    planned: bool = False
    case: Optional[CaseRecord] = None


class AgentService:
    """按 session 管理多轮办事流程的服务对象。"""

    def __init__(self, root: Optional[Path] = None, store=None):
        self.root = Path(root) if root else ROOT
        self.moma = MoMAClient()
        self.knowledge = KnowledgeBase(self.root / "data" / "knowledge")
        self.gov = MockGovServices()
        self.repo = InMemoryRepo()
        # 默认用进程内共享的材料存储；测试可传入隔离的 store
        self.materials = MaterialService(store=store or get_store(), moma=self.moma)
        self.sessions: Dict[str, SessionRecord] = {}
        self._seq = 0

    # ---------- 对外接口 ----------
    def create_session(self, scenario_id: str) -> dict:
        scenario = self._load_scenario(scenario_id)
        if scenario is None:
            raise KeyError(f"场景不存在：{scenario_id}")
        self._seq += 1
        session_id = f"s{self._seq:06d}"
        context = SessionContext()
        rec = SessionRecord(
            session_id=session_id,
            scenario_id=scenario_id,
            scenario=scenario,
            context=context,
            form=ApplicationForm(scenario_id=scenario_id),
            agents=self._make_agents(context),
        )
        self.sessions[session_id] = rec
        opening = scenario.get("opening") or scenario["name"]
        return self._state(rec, message=opening)

    def handle_message(self, session_id: str, message: str) -> dict:
        rec = self._get(session_id)
        intent = route_intent(message)
        if intent == "query":
            if rec.case is None:
                return self._state(rec, message="还没有办理记录，请先开始办理。", intent=intent)
            text = rec.agents["progress"].query(rec.case.item_status, rec.scenario["items"])
            return self._state(rec, message=text, intent=intent)
        if intent == "consult":
            reply = rec.agents["consult"].answer(message, rec.scenario)
            return self._state(rec, message=reply, intent=intent)
        # apply
        if rec.planned:
            return self._state(rec, message="材料清单已经生成，先把材料交齐，通过后就能开始办理。",
                               intent=intent)
        if self._next_question(rec) is None:
            return self._plan(rec)
        return self._state(rec, message="开始办理，请按提示逐步填写信息。", intent=intent)

    def submit_field(self, session_id: str, key: str, value: Any) -> dict:
        rec = self._get(session_id)
        spec = self._field_spec(rec, key)
        if spec is None:
            raise KeyError(f"未知字段：{key}")
        value = self._coerce(spec, value)
        rec.form.fields[key] = value
        rec.context.set(key, value)
        q = self._next_question(rec)
        if q is not None:
            return self._state(rec, message=f"已记录「{spec.get('label', key)}」。", intent="apply")
        return self._plan(rec)

    def get_session(self, session_id: str) -> dict:
        return self._state(self._get(session_id))

    def get_case(self, case_id: str) -> Optional[dict]:
        case = self.repo.get_case(case_id)
        return self._case_dict(case) if case else None

    def attach_case(self, session_id: str, case: Optional[CaseRecord]) -> None:
        """把 `/apply` 生成的办理单挂回会话。

        办理由 `/apply` 跑，所以本服务拿不到 case；由调用方在编排结束后回填，
        这样多轮会话里的"进度查询"仍然可用。
        """
        rec = self.sessions.get(session_id)
        if rec is not None and case is not None:
            rec.case = case

    # ---------- 内部逻辑 ----------
    def _make_agents(self, context: SessionContext) -> Dict[str, Any]:
        return {
            "consult": ConsultAgent(self.moma, context),
            "condition": ConditionAgent(self.moma, context),
            "progress": ProgressAgent(self.moma, context),
        }

    def _load_scenario(self, scenario_id: str) -> Optional[dict]:
        path = self.root / "scenarios" / f"{scenario_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def _get(self, session_id: str) -> SessionRecord:
        rec = self.sessions.get(session_id)
        if rec is None:
            raise KeyError(f"会话不存在：{session_id}")
        return rec

    def _next_question(self, rec: SessionRecord) -> Optional[dict]:
        if rec.planned:
            return None
        for spec in rec.scenario["collect_fields"]:
            if spec["key"] not in rec.form.fields:
                return {
                    "key": spec["key"],
                    "label": spec.get("label", spec["key"]),
                    "type": spec.get("type", "text"),
                    "options": spec.get("options", []),
                    "required": spec.get("required", True),
                }
        return None

    def _field_spec(self, rec: SessionRecord, key: str) -> Optional[dict]:
        for spec in rec.scenario["collect_fields"]:
            if spec["key"] == key:
                return spec
        return None

    def _coerce(self, spec: dict, value: Any) -> Any:
        key = spec["key"]
        t = spec.get("type", "text")
        if t == "number":
            try:
                f = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"{key} 需要是数字")
            return int(f) if f.is_integer() else f
        if t == "bool":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() in ("true", "1", "yes", "y", "是")
            return bool(value)
        if t == "enum":
            opts = spec.get("options", [])
            if value not in opts:
                raise ValueError(f"{key} 只能是：{'、'.join(opts)}")
            return value
        return "" if value is None else str(value)

    def _plan(self, rec: SessionRecord) -> dict:
        """信息采齐 -> 产出材料清单（此时**尚未受理**）。

        受理与并联办理统一交给 `/apply` 驱动 `MainAgent` 完成，
        本服务不再自己 `gov.submit`——否则这里的办理单会缺流程节点、
        缺核验记录，并联事项也会永远停在"已受理"。
        """
        if not rec.planned:
            items, materials, notes = rec.agents["condition"].evaluate(rec.scenario, rec.form)
            rec.context.set("items", items)
            rec.context.set("materials", materials)
            rec.intake = self.materials.plan_from_form(
                rec.scenario, rec.form, items, materials, notes)
            rec.planned = True

        intake = rec.intake
        msg = "信息已收齐。"
        if intake.notes:
            msg += "其中：" + "；".join(intake.notes) + "。"
        msg += ("需要提交 " + str(len(intake.materials)) + " 份材料，材料没通过前无法受理。\n\n"
                + self.materials.brief(rec.scenario, intake))
        return self._state(rec, message=msg, intent="apply")

    def _state(self, rec: SessionRecord, message: str = "", intent: str = "") -> dict:
        return {
            "session_id": rec.session_id,
            "scenario_id": rec.scenario_id,
            "scenario_name": rec.scenario["name"],
            "intent": intent,
            "message": message,
            "next_question": self._next_question(rec),
            "items": rec.context.get("items", []),
            "materials": rec.context.get("materials", []),
            "intake_id": rec.intake.intake_id if rec.intake else "",
            "material_view": self.materials.view(rec.scenario, rec.intake) if rec.intake else None,
            "case": self._case_dict(rec.case),
            "progress": self._progress_list(rec),
        }

    def _case_dict(self, case: Optional[CaseRecord]) -> Optional[dict]:
        if case is None:
            return None
        return {
            "case_id": case.case_id,
            "scenario_id": case.scenario_id,
            "items": case.items,
            "materials": case.materials,
            "verify_report": case.verify_report,
            "item_status": case.item_status,
            "flow": case.flow,
            "created_at": case.created_at,
            "updated_at": case.updated_at,
        }

    def _progress_list(self, rec: SessionRecord) -> List[dict]:
        if rec.case is None:
            return []
        items_map = rec.scenario["items"]
        out = []
        for item_id, status in rec.case.item_status.items():
            name = items_map.get(item_id, {}).get("name", item_id)
            out.append({"item_id": item_id, "name": name, "status": status})
        return out