"""端到端 API 测试：用 FastAPI TestClient 驱动完整多轮流程。

依赖：pip install -r requirements.txt httpx
用法：python tests/test_api_e2e.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from server.main import app

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


def apply_and_submit(client, scenario_id, answers, message):
    r = client.post("/api/session", json={"scenario_id": scenario_id})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]

    r = client.post("/api/chat", json={"session_id": sid, "message": message})
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["intent"] == "apply", t

    guard = 0
    while t.get("next_question"):
        q = t["next_question"]
        r = client.post("/api/fields", json={"session_id": sid, "key": q["key"], "value": answers[q["key"]]})
        assert r.status_code == 200, r.text
        t = r.json()
        guard += 1
        assert guard < 20
    assert t.get("case"), t
    return sid, t


def main():
    client = TestClient(app)

    # 健康检查
    assert client.get("/health").json() == {"status": "ok"}

    # 咨询
    s = client.post("/api/session", json={"scenario_id": "restaurant_open"}).json()
    r = client.post("/api/chat", json={"session_id": s["session_id"], "message": "开餐饮店需要什么材料？"})
    assert r.json()["intent"] == "consult", r.json()

    # 餐饮店完整办理
    sid, t = apply_and_submit(client, "restaurant_open", RESTAURANT, "我想开一家牛肉面馆")
    case = t["case"]
    assert "D_signboard" in case["items"], case["items"]
    assert "C_fire" not in case["items"], case["items"]
    assert "油烟净化设施证明" in case["materials"], case["materials"]

    # 办理单查询
    r = client.get(f"/api/cases/{case['case_id']}")
    assert r.status_code == 200 and r.json()["case_id"] == case["case_id"]

    # 会话状态查询
    r = client.get(f"/api/sessions/{sid}")
    assert r.status_code == 200 and r.json()["session_id"] == sid

    # 进度查询
    r = client.post("/api/chat", json={"session_id": sid, "message": "进度到哪了"})
    assert r.status_code == 200
    p = r.json()
    assert p["intent"] == "query" and p["progress"], p

    # 企业完整办理（条件路由：开户 + 用工备案）
    _, te = apply_and_submit(client, "enterprise_open", ENTERPRISE, "我想注册一家科技公司")
    assert "D_bank" in te["case"]["items"], te["case"]["items"]
    assert "用工备案材料" in te["case"]["materials"], te["case"]["materials"]

    # 大面积触发消防
    big = dict(RESTAURANT, area_sqm=500)
    _, tb = apply_and_submit(client, "restaurant_open", big, "我想开一家大烧烤店")
    assert "C_fire" in tb["case"]["items"], tb["case"]["items"]

    # 异常分支
    assert client.post("/api/session", json={"scenario_id": "nope"}).status_code == 404
    assert client.post("/api/chat", json={"session_id": "nope", "message": "hi"}).status_code == 404
    r = client.post("/api/fields", json={"session_id": sid, "key": "nope", "value": 1})
    assert r.status_code == 404, r.text
    r = client.post("/api/fields", json={"session_id": sid, "key": "area_sqm", "value": "abc"})
    assert r.status_code == 400, r.text

    print("API E2E PASSED")


if __name__ == "__main__":
    main()