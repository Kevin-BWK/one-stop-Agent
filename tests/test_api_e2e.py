"""端到端 API 测试：用 FastAPI TestClient 驱动完整多轮流程。

流程：建会话 -> 逐字段采集 -> 产出材料清单 -> 上传材料 -> 跑编排 -> 会话内查进度。
（材料未齐不允许受理，见 `docs/09`。）

依赖：pip install -r requirements.txt httpx
用法：python tests/test_api_e2e.py
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("MOMA_DISABLE_LIVE", "1")  # 测试离线运行，避免真实调用

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


# 造一张体积正常（核验通过）的图片
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * (20 * 1024 - 4)


def upload_materials(client, intake_id, view):
    """按槽位把必交材料全部传齐（材料未齐不允许受理，见 docs/09）。"""
    for material in view["materials"]:
        for slot in (material["slots"] or [""]):
            r = client.post(
                "/api/materials/" + intake_id + "/" + material["id"] + "/files",
                files={"file": ((slot or material["id"]) + ".jpg", JPG, "image/jpeg")},
                data={"slot": slot},
            )
            assert r.status_code == 200, r.text


def apply_and_submit(client, scenario_id, answers, message):
    """多轮采集 -> 产出材料清单 -> 上传材料 -> 跑编排 -> 从会话取办理单。"""
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

    # 字段采齐后只产出材料清单，此时**尚未受理**
    assert t.get("intake_id"), t
    assert t.get("case") is None, t
    intake_id = t["intake_id"]
    upload_materials(client, intake_id, t["material_view"])

    # 材料齐备 -> 跑编排（带 session_id，办理单会挂回会话）
    r = client.get("/apply", params={
        "scenario_id": scenario_id,
        "utterance": message,
        "answers": json.dumps(answers, ensure_ascii=False),
        "intake_id": intake_id,
        "session_id": sid,
    })
    assert r.status_code == 200, r.text
    assert "event: finished" in r.text, r.text

    state = client.get("/api/sessions/" + sid).json()
    assert state.get("case"), state
    return sid, state


def main():
    client = TestClient(app)

    # 健康检查
    health = client.get("/health").json()
    assert health["status"] == "ok"
    assert health["moma"] in ("live", "stub")

    # 咨询
    s = client.post("/api/session", json={"scenario_id": "restaurant_open"}).json()
    r = client.post("/api/chat", json={"session_id": s["session_id"], "message": "开餐饮店需要什么材料？"})
    assert r.json()["intent"] == "consult", r.json()

    # 餐饮店完整办理
    # 条件判定的规则矩阵见 tests/test_condition_routing.py；
    # 这里只留"通过 HTTP 提交的表单值真的流进了规则引擎"的集成冒烟（一正一反）。
    sid, t = apply_and_submit(client, "restaurant_open", RESTAURANT, "我想开一家牛肉面馆")
    case = t["case"]
    assert "D_signboard" in case["items"], case["items"]   # 正向：设了招牌
    assert "C_fire" not in case["items"], case["items"]    # 反向：80 平米

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

    # 企业场景也走一遍（证明换场景、换答案都能跑通）
    _, te = apply_and_submit(client, "enterprise_open", ENTERPRISE, "我想注册一家科技公司")
    assert "D_bank" in te["case"]["items"], te["case"]["items"]

    # 对话区提问：带会话走多轮上下文，会话不存在返回 404
    talk = client.post("/api/session", json={"scenario_id": "restaurant_open"}).json()
    r = client.post("/api/ask", json={
        "scenario_id": "restaurant_open", "question": "需要什么材料",
        "session_id": talk["session_id"]})
    assert r.status_code == 200 and r.json()["answer"], r.json()
    # 知识库真的接上了：回答里带办事指南依据（见 docs/11）
    assert "来自办事指南" in r.json()["answer"], r.json()["answer"]
    r = client.post("/api/ask", json={
        "scenario_id": "restaurant_open", "question": "hi", "session_id": "nope"})
    assert r.status_code == 404, r.text
    assert client.post("/api/ask", json={
        "scenario_id": "restaurant_open", "question": "  "}).status_code == 400

    # 条件判定实时预判：只读、无状态，按当前输入给出事项与材料
    # （规则细节见 tests/test_condition_routing.py，这里只验接口契约）
    base = client.post("/api/preview", json={"scenario_id": "restaurant_open", "answers": {}}).json()
    assert base["items"], base
    assert base["material_names"][0] == "法定代表人身份证", base    # id 已转成中文名

    filled = client.post("/api/preview", json={
        "scenario_id": "restaurant_open",
        "answers": {"business_type": "热食/有油烟", "signboard": True}}).json()
    assert filled["items"] != base["items"], filled                # 输入变了，预判就跟着变
    # 中文输入要能正确落到规则上，并且 id 已映射成中文名
    assert "油烟净化设施证明" in filled["material_names"], filled
    assert "户外招牌设施设置" in filled["item_names"], filled
    assert filled["notes"], filled                                 # 并说明为什么会多出这些

    assert client.post("/api/preview", json={"scenario_id": "nope", "answers": {}}).status_code == 404

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
