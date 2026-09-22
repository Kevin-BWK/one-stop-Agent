"""冒烟测试：验证两个场景闭环、办理流程节点打勾与并联进度推进，无需 pytest。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.knowledge.retriever import KnowledgeBase
from app.moma.client import MoMAClient
from app.moma.context import SessionContext
from app.mock_gov.services import MockGovServices
from app.storage.repo import InMemoryRepo
from app.orchestrator.events import (CASE_CREATED, FINISHED, FLOW_NODE,
                                     ITEM_DONE, MESSAGE)
from app.orchestrator.flow import FLOW_NODES, STATUS_DONE
from app.orchestrator.main_agent import MainAgent

RESTAURANT_ANSWERS = {
    "utterance": "我想开一家牛肉面馆",
    "name": "老张牛肉面",
    "business_type": "热食/有油烟",
    "area_sqm": 80,
    "has_raw_food": False,
    "address": "幸福路 12 号",
    "signboard": True,
}

ENTERPRISE_ANSWERS = {
    "utterance": "我想注册一家科技公司",
    "company_name": "云启科技有限公司",
    "legal_person": "张三",
    "registered_capital": 100,
    "business_scope": "软件与信息技术服务",
    "address": "创新大道 1 号",
    "need_bank": True,
    "employees": 10,
}

FLOW_KEYS = [key for key, _ in FLOW_NODES]


def _make_agent(scenario_id, repo=None):
    with open(ROOT / "scenarios" / (scenario_id + ".json"), encoding="utf-8-sig") as f:
        scenario = json.load(f)
    repo = repo if repo is not None else InMemoryRepo()
    agent = MainAgent(
        scenario=scenario,
        moma=MoMAClient(),
        knowledge=KnowledgeBase(ROOT / "data" / "knowledge"),
        gov=MockGovServices(),
        repo=repo,
        context=SessionContext(),
    )
    return agent, repo


def _run(scenario_id, answers):
    agent, _ = _make_agent(scenario_id)
    _, case = agent.run(answers["utterance"], answers)
    return case


def test_restaurant_flow():
    case = _run("restaurant_open", RESTAURANT_ANSWERS)
    assert case.case_id.startswith("YJS")
    assert "A_license" in case.items
    assert "D_signboard" in case.items  # 设置了招牌 -> 触发城管
    assert "C_fire" not in case.items  # 80 平米 -> 不触发消防


def test_restaurant_condition_routing():
    big = dict(RESTAURANT_ANSWERS, area_sqm=500)
    case = _run("restaurant_open", big)
    assert "C_fire" in case.items  # 大面积 -> 触发消防检查


def test_enterprise_flow():
    case = _run("enterprise_open", ENTERPRISE_ANSWERS)
    assert case.case_id.startswith("YJS")
    assert "D_bank" in case.items  # 预约开户
    assert "用工备案材料" in case.materials  # 10 人 -> 用工备案


def test_flow_nodes_all_checked():
    """办理流程跑完后，框架节点与各部门事项节点全部打勾。"""
    case = _run("restaurant_open", RESTAURANT_ANSWERS)
    flow = {node["key"]: node for node in case.flow}
    for key in FLOW_KEYS:
        assert flow[key]["status"] == STATUS_DONE

    # 并联事项由部门子 Agent 完成后成为流程节点并打勾
    for item_id in case.items:
        assert flow[item_id]["status"] == STATUS_DONE

    keys = [node["key"] for node in case.flow]
    assert keys[:len(FLOW_KEYS) - 1] == FLOW_KEYS[:-1]  # 事项节点插在 并联提交 与 进度跟踪 之间
    assert keys[-1] == FLOW_KEYS[-1]


def test_item_agents_report_completion():
    """部门子 Agent 办理完成后回调主 Agent，事项状态与进度节点自动更新。"""
    agent, _ = _make_agent("restaurant_open")
    _, case = agent.run(RESTAURANT_ANSWERS["utterance"], RESTAURANT_ANSWERS)
    assert set(case.item_status.values()) == {MockGovServices.STAGES[-1]}  # 全部办结
    assert agent.gov.is_finished(case)
    assert "【并联办理】" in agent.query(case.case_id)[0][-1][1]


def test_progress_query_by_case_id():
    """查询意图 + 单号可返回既有办理单的进度看板。"""
    agent, _ = _make_agent("enterprise_open")
    _, case = agent.run(ENTERPRISE_ANSWERS["utterance"], ENTERPRISE_ANSWERS)
    trace, found = agent.run("查询进度", {"case_id": case.case_id})
    assert found is not None
    assert found.case_id == case.case_id
    assert "【办理流程】" in trace[-1][1]


def test_events_emitted_for_gui():
    """可选 on_event 回调按契约推送事件，供 GUI 实时刷新。"""
    agent, _ = _make_agent("restaurant_open")
    events = []
    _, case = agent.run(RESTAURANT_ANSWERS["utterance"], RESTAURANT_ANSWERS, on_event=events.append)

    types = [event.type for event in events]
    assert types[0] == FLOW_NODE  # 首个事件是"意图识别"节点打勾
    assert types[-1] == FINISHED
    for expected in (MESSAGE, FLOW_NODE, CASE_CREATED, ITEM_DONE, FINISHED):
        assert expected in types

    created = next(event for event in events if event.type == CASE_CREATED)
    assert {"case_id", "scenario_id", "items", "materials"} <= set(created.data)
    assert created.data["case_id"] == case.case_id

    node_event = next(event for event in events if event.type == FLOW_NODE)
    assert {"key", "name", "status", "detail", "updated_at", "done", "total"} <= set(node_event.data)

    item_event = next(event for event in events if event.type == ITEM_DONE)
    assert {"item_id", "name", "department", "output", "status"} <= set(item_event.data)

    # flow_node 的已完成数量单调不减，且最终全部完成
    node_events = [e for e in events if e.type == FLOW_NODE]
    done_counts = [e.data["done"] for e in node_events]
    assert done_counts == sorted(done_counts)
    assert done_counts[-1] == node_events[-1].data["total"] == len(case.flow)

    # finish 事件带回最终进度
    assert events[-1].data["case_id"] == case.case_id
    assert all(node["status"] == STATUS_DONE for node in events[-1].data["flow"])

    # 事件可 JSON 序列化（Web 层需写入 SSE data）
    assert json.loads(json.dumps([event.to_dict() for event in events]))[-1]["type"] == FINISHED


def test_run_without_on_event_unchanged():
    """不传 on_event 时行为与以往一致（向后兼容）。"""
    agent, _ = _make_agent("enterprise_open")
    trace, case = agent.run(ENTERPRISE_ANSWERS["utterance"], ENTERPRISE_ANSWERS)
    assert trace and case is not None
    assert set(case.item_status.values()) == {MockGovServices.STAGES[-1]}


if __name__ == "__main__":
    test_restaurant_flow()
    test_restaurant_condition_routing()
    test_enterprise_flow()
    test_flow_nodes_all_checked()
    test_item_agents_report_completion()
    test_progress_query_by_case_id()
    test_events_emitted_for_gui()
    test_run_without_on_event_unchanged()
    print("ALL TESTS PASSED")
