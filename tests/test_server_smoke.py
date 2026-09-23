"""服务层冒烟测试：验证多轮会话闭环（无需 FastAPI / pytest）。

用法：python tests/test_server_smoke.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("MOMA_DISABLE_LIVE", "1")  # 测试离线运行，避免真实调用

from server.service import AgentService

RESTAURANT = {
    "name": "老张牛肉面",
    "business_type": "热食/有油烟",
    "area_sqm": 80,
    "has_raw_food": False,
    "address": "幸福路 12 号",
    "signboard": True,
}

ENTERPRISE = {
    "company_name": "云启科技有限公司",
    "legal_person": "张三",
    "registered_capital": 100,
    "business_scope": "软件与信息技术服务",
    "address": "创新大道 1 号",
    "need_bank": True,
    "employees": 10,
}


def run_scenario(svc, scenario_id, answers, message):
    s = svc.create_session(scenario_id)
    t = svc.handle_message(s["session_id"], message)
    assert t["intent"] == "apply", t
    guard = 0
    while t.get("next_question"):
        q = t["next_question"]
        t = svc.submit_field(s["session_id"], q["key"], answers[q["key"]])
        guard += 1
        assert guard < 20, "字段采集出现死循环"
    assert t.get("case"), t
    return s["session_id"], t


def main():
    svc = AgentService(ROOT)

    # 咨询意图
    s = svc.create_session("restaurant_open")
    t = svc.handle_message(s["session_id"], "开餐饮店需要什么材料？")
    assert t["intent"] == "consult", t

    # 餐饮店多轮闭环（80㎡ + 招牌 -> 招牌审批，不触发消防）
    sid, t = run_scenario(svc, "restaurant_open", RESTAURANT, "我想开一家牛肉面馆")
    assert "D_signboard" in t["case"]["items"], t["case"]["items"]
    assert "C_fire" not in t["case"]["items"], t["case"]["items"]
    assert "油烟净化设施证明" in t["case"]["materials"], t["case"]["materials"]

    # 大面积 -> 触发消防
    big = dict(RESTAURANT, area_sqm=500)
    _, tb = run_scenario(svc, "restaurant_open", big, "我想开一家大烧烤店")
    assert "C_fire" in tb["case"]["items"], tb["case"]["items"]

    # 企业多轮闭环（预约开户 + 10 人 -> 用工备案）
    _, te = run_scenario(svc, "enterprise_open", ENTERPRISE, "我想注册一家科技公司")
    assert "D_bank" in te["case"]["items"], te["case"]["items"]
    assert "用工备案材料" in te["case"]["materials"], te["case"]["materials"]

    # 进度查询
    p = svc.handle_message(sid, "进度到哪了")
    assert p["intent"] == "query", p
    assert p["progress"], p

    print("SERVER SMOKE PASSED")


if __name__ == "__main__":
    main()
