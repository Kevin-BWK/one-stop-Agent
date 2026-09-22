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

from app.config import ROOT
from app.knowledge.retriever import KnowledgeBase
from app.moma.client import MoMAClient
from app.moma.context import SessionContext
from app.mock_gov.services import MockGovServices
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


def load_case(case_id: str) -> Optional[Dict[str, Any]]:
    """按单号读取已落盘的办理单（含 flow 节点台账）。"""
    case = JsonFileRepo(CASES_FILE).get_case(case_id)
    return case.to_dict() if case else None


def build_agent(scenario: Dict[str, Any]) -> MainAgent:
    return MainAgent(
        scenario=scenario,
        moma=MoMAClient(),
        knowledge=KnowledgeBase(ROOT / "data" / "knowledge"),
        gov=MockGovServices(),
        repo=JsonFileRepo(CASES_FILE),
        context=SessionContext(),
    )


def iter_events(scenario: Dict[str, Any], utterance: str, answers: Optional[Dict[str, Any]] = None) -> Iterator[Event]:
    """跑一次编排，按发生顺序产出事件（供 SSE / WebSocket 使用）。"""
    agent = build_agent(scenario)
    bucket: "queue.Queue" = queue.Queue()

    def worker():
        try:
            agent.run(utterance, answers or {}, on_event=bucket.put)
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


def sse_stream(scenario: Dict[str, Any], utterance: str, answers: Optional[Dict[str, Any]] = None):
    """SSE 响应体生成器。"""
    for index, event in enumerate(iter_events(scenario, utterance, answers), start=1):
        yield to_sse(event, index)
