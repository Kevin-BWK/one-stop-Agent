"""多轮会话服务：把多 Agent 编排包装成可多轮驱动的状态机。

阶段一目标：
1. 会话与场景绑定（session_id -> scenario）
2. 意图路由：咨询 / 办理 / 进度
3. 字段逐项采集，采齐后自动条件判定 -> 核验 -> 并联提交
4. 进度查询

说明：CLI 的 MainAgent.run 仍保留为一次性演示入口；本服务提供 App 所需的多轮能力。
"""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.agents.condition_agent import ConditionAgent
from app.agents.consult_agent import ConsultAgent
from app.agents.progress_agent import ProgressAgent
from app.agents.verify_agent import VerifyAgent
from app.config import ROOT
from app.knowledge.retriever import KnowledgeBase
from app.moma.client import MoMAClient
from app.moma.context import SessionContext
from app.mock_gov.services import MockGovServices
from app.models.schema import ApplicationForm, CaseRecord
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
    case: Optional[CaseRecord] = None
    submitted: bool = False


class AgentService:
    """按 session 管理多轮办事流程的服务对象。"""

    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else ROOT
        self.moma = MoMAClient()
        self.knowledge = KnowledgeBase(self.root / "data" / "knowledge")
        self.gov = MockGovServices()
        self.repo = InMemoryRepo()
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
        q = self._next_question(rec)
        msg = "开始办理，请按提示逐步填写信息。" if q else "信息已填写完成，可直接提交办理。"
        return self._state(rec, message=msg, intent=intent)

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
        return self._finalize(rec)

    def get_session(self, session_id: str) -> dict:
        return self._state(self._get(session_id))

    def get_case(self, case_id: str) -> Optional[dict]:
        case = self.repo.get_case(case_id)
        return self._case_dict(case) if case else None

    # ---------- 内部逻辑 ----------
    def _make_agents(self, context: SessionContext) -> Dict[str, Any]:
        return {
            "consult": ConsultAgent(self.moma, context),
            "condition": ConditionAgent(self.moma, context),
            "verify": VerifyAgent(self.moma, context),
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
        if rec.submitted:
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

    def _finalize(self, rec: SessionRecord) -> dict:
        scenario = rec.scenario
        items, materials, notes = rec.agents["condition"].evaluate(scenario, rec.form)
        rec.context.set("items", items)
        rec.context.set("materials", materials)
        report = rec.agents["verify"].verify(materials)
        case = self.gov.submit(scenario["id"], items, materials, rec.form)
        self.repo.save_case(case)
        rec.case = case
        rec.submitted = True
        note_text = "；".join(notes) if notes else "无特殊条件"
        msg = f"办理单 {case.case_id} 已生成并并联提交。判定说明：{note_text}。"
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