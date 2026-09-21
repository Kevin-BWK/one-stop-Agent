"""最小可运行演示：跑通“开办企业 / 开办餐饮店”两个场景的闭环。

用法：
    python run_demo.py                # 两个场景都跑
    python run_demo.py restaurant     # 只跑餐饮店
    python run_demo.py enterprise     # 只跑企业
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.knowledge.retriever import KnowledgeBase
from app.moma.client import MoMAClient
from app.moma.context import SessionContext
from app.mock_gov.services import MockGovServices
from app.storage.repo import InMemoryRepo
from app.orchestrator.main_agent import MainAgent

RESTAURANT_ANSWERS = {
    "utterance": "我想在学校旁边开一家牛肉面馆",
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


def load_scenario(scenario_id):
    path = ROOT / "scenarios" / (scenario_id + ".json")
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def build_agent(scenario):
    return MainAgent(
        scenario=scenario,
        moma=MoMAClient(),
        knowledge=KnowledgeBase(ROOT / "data" / "knowledge"),
        gov=MockGovServices(),
        repo=InMemoryRepo(),
        context=SessionContext(),
    )


def demo(scenario_id, answers):
    scenario = load_scenario(scenario_id)
    agent = build_agent(scenario)
    print("=" * 60)
    print("场景：" + scenario["name"] + "  (id=" + scenario_id + ")")
    print("=" * 60)
    trace, case = agent.run(answers["utterance"], answers)
    for stage, text in trace:
        print("")
        print("[" + stage + "]")
        print(text)
    print("")
    print("-" * 60)
    print("办理单号：" + case.case_id)
    print("并联事项：" + "、".join(case.items))
    print("材料清单：" + "、".join(case.materials))
    return case


def main(argv):
    choices = {"restaurant": "restaurant_open", "enterprise": "enterprise_open"}
    targets = []
    for arg in argv:
        if arg in choices:
            targets.append(choices[arg])
    if not targets:
        targets = ["restaurant_open", "enterprise_open"]
    for sid in targets:
        answers = RESTAURANT_ANSWERS if sid == "restaurant_open" else ENTERPRISE_ANSWERS
        demo(sid, answers)


if __name__ == "__main__":
    main(sys.argv[1:])
