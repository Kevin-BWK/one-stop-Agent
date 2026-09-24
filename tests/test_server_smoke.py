"""服务层冒烟测试：验证多轮会话闭环（无需 FastAPI / pytest）。

链路：建会话 -> 逐字段采集 -> 产出材料清单 -> 上传材料 -> 跑编排 -> 会话内查进度。

要点：服务层**不再自己受理**（不 `gov.submit`），办理统一由 `/apply` 驱动
`MainAgent` 完成，否则两条路径会产出质量不一致的办理单（见 `docs/09`）。

用法：python tests/test_server_smoke.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("MOMA_DISABLE_LIVE", "1")  # 测试离线运行，避免真实调用

from app.materials.spec import material_specs
from app.materials.store import MaterialStore
from app.orchestrator.flow import STATUS_DONE
from server.service import AgentService
from server.stream import iter_events, load_scenario, material_gate

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


def collect(svc, scenario_id, answers, message):
    """建会话并逐字段采集，返回 (session_id, 最后一轮返回)。"""
    s = svc.create_session(scenario_id)
    t = svc.handle_message(s["session_id"], message)
    assert t["intent"] == "apply", t
    guard = 0
    while t.get("next_question"):
        q = t["next_question"]
        t = svc.submit_field(s["session_id"], q["key"], answers[q["key"]])
        guard += 1
        assert guard < 20, "字段采集出现死循环"
    return s["session_id"], t


def upload_all(svc, scenario, intake):
    """按槽位把必交材料全部传齐。"""
    for spec in material_specs(scenario, intake.materials):
        for slot in (spec["slots"] or [""]):
            svc.materials.upload(scenario, intake, spec["id"],
                                 (slot or spec["id"]) + ".jpg", "image/jpeg", JPG, slot=slot)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="yjs-service-"))
    try:
        svc = AgentService(ROOT, store=MaterialStore(
            intakes_file=tmp / "intakes.json", materials_dir=tmp / "materials"))

        # 1) 咨询意图
        s = svc.create_session("restaurant_open")
        t = svc.handle_message(s["session_id"], "开餐饮店需要什么材料？")
        assert t["intent"] == "consult", t

        # 2) 多轮采集：字段填完应产出材料清单，而**不是**直接受理
        #    （规则矩阵见 tests/test_condition_routing.py，这里只做集成冒烟）
        sid, t = collect(svc, "restaurant_open", RESTAURANT, "我想开一家牛肉面馆")
        assert t["intake_id"].startswith("CL"), t
        assert t.get("case") is None, "字段采齐后不该直接受理"
        assert "D_signboard" in t["items"], t["items"]      # 正向：设了招牌
        assert "C_fire" not in t["items"], t["items"]       # 反向：80 平米
        # 实时预判：采齐后应与正式清单一致（同一套纯函数算出来的）
        assert t["preview"]["items"] == t["items"], t["preview"]
        assert t["preview"]["materials"] == t["materials"], t["preview"]

        view = t["material_view"]
        names = [m["name"] for m in view["materials"]]
        # 本层特有的集成点：条件判定结果 -> 材料清单，且 id 已转成中文名
        assert "油烟净化设施证明" in names, names
        assert view["summary"] == {"total": 4, "passed": 0, "ready": False}, view["summary"]
        for material in view["materials"]:
            assert material["reason"] and material["form"], material   # 必须告诉用户为什么、怎么给

        # 3) 材料没交齐不允许受理
        scenario = load_scenario("restaurant_open")
        intake = svc.materials.store.get(t["intake_id"])
        assert len(material_gate(scenario, intake)) == 4

        # 4) 传齐后放行
        upload_all(svc, scenario, intake)
        assert material_gate(scenario, intake) == []

        # 5) 跑编排；办理单应被挂回会话
        events = list(iter_events(scenario, "我想开一家牛肉面馆", RESTAURANT, intake,
                                  on_finish=lambda case: svc.attach_case(sid, case)))
        types = [event.type for event in events]
        assert types[0] == "flow_node" and types[-1] == "finished", types
        assert "case_created" in types and "item_done" in types, types

        rec = svc.sessions[sid]
        assert rec.case is not None, "办理单应已挂回会话"
        flow = {node["key"]: node for node in rec.case.flow}
        assert flow["verify"]["status"] == STATUS_DONE, flow["verify"]
        assert len(rec.case.flow) == 11, len(rec.case.flow)          # 7 框架节点 + 4 部门事项
        assert set(rec.case.item_status.values()) == {"已办结"}, rec.case.item_status
        assert rec.case.verify_report.get("passed") == 4, rec.case.verify_report
        assert rec.case.materials == intake.materials, rec.case.materials

        # 6) 会话内查进度
        p = svc.handle_message(sid, "进度到哪了")
        assert p["intent"] == "query", p
        assert p["progress"], p
        assert len(p["progress"]) == 4, p["progress"]

        # 7) 再问办理 -> 应提示去交材料，而不是重复生成清单
        again = svc.handle_message(sid, "开始办理")
        assert again["intake_id"] == t["intake_id"], again

        # 8) 企业场景也走一遍（证明换场景、换答案都能跑通）
        _, te = collect(svc, "enterprise_open", ENTERPRISE, "我想注册一家科技公司")
        assert "D_bank" in te["items"], te["items"]
        assert len(te["material_view"]["materials"]) == 4, te["material_view"]["summary"]

        print("SERVER SMOKE PASSED")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
