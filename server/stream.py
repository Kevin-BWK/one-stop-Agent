"""编排事件流：把 MainAgent 的 on_event 事件转成可推送的流。

- H5（调试端）：SSE（`GET /apply`），由 `to_sse()` 编码。
- App（成品端）：WebSocket（`/ws/apply`），直接发送 `Event.to_dict()`。
两端**事件负载完全一致**，只是装帧方式不同。

编排本身是同步的，这里放到后台线程跑，通过队列按发生顺序产出事件，
从而做到"节点一完成就推给前端"（而不是攒完再一次返回）。
"""
import json
import queue
import threading
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from app.agents.consult_agent import ConsultAgent
from app.config import ROOT
from app.knowledge.retriever import KnowledgeBase
from app.materials.spec import PASSED, material_specs, status_of
from app.materials.store import get_store
from app.moma.client import MoMAClient
from app.moma.context import SessionContext
from app.mock_gov.services import MockGovServices
from app.models.schema import MaterialIntake
from app.orchestrator.events import ERROR, Event
from app.orchestrator.main_agent import MainAgent
from app.storage.repo import JsonFileRepo

CASES_FILE = ROOT / "data" / "runtime" / "cases.json"


def load_scenario(scenario_id: str) -> Optional[Dict[str, Any]]:
    """读取场景配置；不存在返回 None。"""
    path = ROOT / "scenarios" / (str(scenario_id) + ".json")
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def answer_question(scenario: Dict[str, Any], question: str, context=None,
                    knowledge=None) -> str:
    """咨询应答：复用咨询 Agent（接 MoMA 后即为真实对话模型，接口不变）。

    传入 `context`（会话上下文）时会带上该会话的历史问答，即**多轮上下文**；
    不传则用一次性上下文，等价于无状态的单轮问答。
    传入 `knowledge` 时会先检索办事指南作为作答依据（见 `docs/11`）。
    """
    agent = ConsultAgent(MoMAClient(), context if context is not None else SessionContext())
    return agent.answer(question, scenario, knowledge)


def missing_required(scenario: Dict[str, Any], answers: Optional[Dict[str, Any]]) -> list:
    """提交前置校验：返回未填的必填项名称（按 collect_fields[].required）。"""
    answers = answers or {}
    missing = []
    for spec in scenario.get("collect_fields", []):
        if not spec.get("required"):
            continue
        value = answers.get(spec["key"])
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(spec.get("label", spec["key"]))
    return missing


def load_case(case_id: str) -> Optional[Dict[str, Any]]:
    """按单号读取已落盘的办理单（含 flow 节点台账）。"""
    case = JsonFileRepo(CASES_FILE).get_case(case_id)
    return case.to_dict() if case else None


def load_intake(intake_id: str) -> Optional[MaterialIntake]:
    """按受理号读取材料收集单。"""
    return get_store().get(intake_id) if intake_id else None


def material_gate(scenario: Dict[str, Any], intake: Optional[MaterialIntake]) -> list:
    """受理前置校验：返回还没交齐/没通过核验的必交材料名称。

    没有 intake（CLI 演示、老的调用方）时不做拦截，保持向后兼容。
    """
    if intake is None:
        return []
    blocked = []
    for spec in material_specs(scenario, list(intake.materials)):
        if not spec.get("required", True):
            continue
        if status_of(spec, intake.files_of(spec["id"])) != PASSED:
            blocked.append(spec["name"])
    return blocked


def build_agent(scenario: Dict[str, Any]) -> MainAgent:
    return MainAgent(
        scenario=scenario,
        moma=MoMAClient(),
        knowledge=KnowledgeBase(ROOT / "data" / "knowledge"),
        gov=MockGovServices(),
        repo=JsonFileRepo(CASES_FILE),
        context=SessionContext(),
    )


def iter_events(scenario: Dict[str, Any], utterance: str,
                answers: Optional[Dict[str, Any]] = None,
                intake: Optional[MaterialIntake] = None,
                on_finish=None) -> Iterator[Event]:
    """跑一次编排，按发生顺序产出事件（供 SSE / WebSocket 使用）。

    传入 intake 表示材料已提交齐备，编排从「材料核验」续跑到办结。
    `on_finish(case)` 在编排结束后（生成办理单时）回调，多轮会话用它把
    办理单挂回 session；客户端提前断开也不影响它被调用。
    """
    agent = build_agent(scenario)
    bucket: "queue.Queue" = queue.Queue()

    def worker():
        try:
            _, case = agent.run(utterance, answers or {}, on_event=bucket.put, intake=intake)
            if on_finish is not None and case is not None:
                on_finish(case)
        except Exception as exc:  # 编排异常也要让前端收到，不能静默
            bucket.put(Event(ERROR, {"code": exc.__class__.__name__, "message": str(exc)}))
        finally:
            bucket.put(None)

    threading.Thread(target=worker, daemon=True).start()

    while True:
        event = bucket.get()
        if event is None:
            return
        yield event


def to_sse(event: Event, event_id: int) -> str:
    """按 SSE 帧格式编码（H5 端使用）。"""
    payload = json.dumps(event.to_dict(), ensure_ascii=False)
    return "id: " + str(event_id) + "\nevent: " + event.type + "\ndata: " + payload + "\n\n"


def sse_stream(scenario: Dict[str, Any], utterance: str,
               answers: Optional[Dict[str, Any]] = None,
               intake: Optional[MaterialIntake] = None,
               on_finish=None):
    """SSE 响应体生成器。"""
    events = iter_events(scenario, utterance, answers, intake, on_finish)
    for index, event in enumerate(events, start=1):
        yield to_sse(event, index)
