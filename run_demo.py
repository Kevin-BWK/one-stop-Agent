"""最小可运行演示：跑通"开办企业 / 开办餐饮店"两个场景的闭环，并展示办理进度推进。

用法：
    python run_demo.py                    # 两个场景都跑
    python run_demo.py restaurant         # 只跑餐饮店
    python run_demo.py enterprise         # 只跑企业
    python run_demo.py --query YJS0001    # 按办理单号查询进度看板
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
from app.storage.repo import JsonFileRepo
from app.orchestrator.main_agent import MainAgent

CASES_FILE = ROOT / "data" / "runtime" / "cases.json"

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
        repo=JsonFileRepo(CASES_FILE),
        context=SessionContext(),
    )


def print_trace(trace):
    for stage, text in trace:
        print("")
        print("[" + stage + "]")
        print(text)


def demo(scenario_id, answers):
    scenario = load_scenario(scenario_id)
    agent = build_agent(scenario)
    print("=" * 60)
    print("场景：" + scenario["name"] + "  (id=" + scenario_id + ")")
    print("=" * 60)
    trace, case = agent.run(answers["utterance"], answers)
    print_trace(trace)
    print("")
    print("-" * 60)
    print("办理单号：" + case.case_id)
    print("并联事项：" + "、".join(case.items))
    print("材料清单：" + "、".join(case.materials))
    print("")
    print("提示：办理单已落盘，可执行  python run_demo.py --query " + case.case_id + "  查询进度。")
    return case


def query_demo(case_id):
    repo = JsonFileRepo(CASES_FILE)
    case = repo.get_case(case_id)
    if case is None:
        print("未找到办理单 " + case_id + "。请先运行  python run_demo.py  生成办理单。")
        return None
    agent = build_agent(load_scenario(case.scenario_id))
    print("=" * 60)
    print("办理单 " + case_id + " 进度查询")
    print("=" * 60)
    trace, case = agent.query(case_id)
    print_trace(trace)
    print("")
    print("并联事项已全部办结。" if agent.gov.is_finished(case) else "并联事项仍在办理中。")
    return case


def main(argv):
    if argv and argv[0] in ("--query", "-q"):
        if len(argv) < 2:
            print("用法：python run_demo.py --query <办理单号>")
            return
        query_demo(argv[1])
        return
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
