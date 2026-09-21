"""冒烟测试：验证两个场景都能跑通闭环，无需 pytest。"""
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


def _run(scenario_id, answers):
    with open(ROOT / "scenarios" / (scenario_id + ".json"), encoding="utf-8-sig") as f:
        scenario = json.load(f)
    agent = MainAgent(
        scenario=scenario,
        moma=MoMAClient(),
        knowledge=KnowledgeBase(ROOT / "data" / "knowledge"),
        gov=MockGovServices(),
        repo=InMemoryRepo(),
        context=SessionContext(),
    )
    trace, case = agent.run(answers["utterance"], answers)
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


if __name__ == "__main__":
    test_restaurant_flow()
    test_restaurant_condition_routing()
    test_enterprise_flow()
    print("ALL TESTS PASSED")
