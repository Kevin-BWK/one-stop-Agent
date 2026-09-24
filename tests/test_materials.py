"""冒烟测试：材料提交链路（材料清单 -> 逐张上传核验 -> 齐备后才受理）。

跑法（在项目根目录）：python tests/test_materials.py
"""
import atexit
import itertools
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

# 测试离线运行：避免本机配了 .env 时材料核验去调真实多模态模型
os.environ.setdefault("MOMA_DISABLE_LIVE", "1")

from app.knowledge.retriever import KnowledgeBase
from app.materials.service import MaterialService
from app.materials.spec import (NEED_FIX, PASSED, PENDING, material_specs,
                                summary)
from app.materials.store import MaterialStore
from app.moma.client import MoMAClient
from app.moma.context import SessionContext
from app.mock_gov.services import MockGovServices
from app.orchestrator.flow import FLOW_NODES, STATUS_DONE
from app.orchestrator.main_agent import MainAgent
from app.storage.repo import InMemoryRepo
from test_flow import ENTERPRISE_ANSWERS, RESTAURANT_ANSWERS

TMP = Path(tempfile.mkdtemp(prefix="yjs-materials-"))
atexit.register(lambda: shutil.rmtree(TMP, ignore_errors=True))
_SEQ = itertools.count(1)


def _service() -> MaterialService:
    """每个用例一份独立存储，互不污染。"""
    slot = next(_SEQ)
    return MaterialService(store=MaterialStore(
        intakes_file=TMP / ("run" + str(slot)) / "intakes.json",
        materials_dir=TMP / ("run" + str(slot)) / "materials",
    ))


def _scenario(scenario_id):
    with open(ROOT / "scenarios" / (scenario_id + ".json"), encoding="utf-8-sig") as f:
        return json.load(f)


def _jpg(size=20 * 1024) -> bytes:
    """造一张体积正常（核验通过）的图片。"""
    return b"\xff\xd8\xff\xe0" + b"\x00" * (size - 4)


def _tiny_jpg() -> bytes:
    """造一张过小的图片（触发"需补正"）。"""
    return b"\xff\xd8\xff\xe0" + b"\x00" * 512


def _fill_all(service, scenario, intake):
    """把必交材料按槽位全部传齐。"""
    for spec in material_specs(scenario, intake.materials):
        if spec["multiple"]:
            service.upload(scenario, intake, spec["id"], "page1.jpg", "image/jpeg", _jpg(), slot="")
        else:
            for label in spec["slots"]:
                service.upload(scenario, intake, spec["id"], label + ".jpg", "image/jpeg",
                               _jpg(), slot=label)
    return intake


def _agent(scenario):
    return MainAgent(
        scenario=scenario,
        moma=MoMAClient(),
        knowledge=KnowledgeBase(ROOT / "data" / "knowledge"),
        gov=MockGovServices(),
        repo=InMemoryRepo(),
        context=SessionContext(),
    )


def test_plan_follows_condition_rules():
    """材料清单由条件判定产出：经营热食要多交油烟净化设施证明。"""
    service = _service()
    scenario = _scenario("restaurant_open")
    intake = service.plan(scenario, RESTAURANT_ANSWERS)

    assert intake.intake_id.startswith("CL")
    assert intake.materials == ["id_card", "premises", "layout", "oil_purifier"]

    view = service.view(scenario, intake)
    assert view["summary"] == {"total": 4, "passed": 0, "ready": False}
    assert all(item["status"] == PENDING for item in view["materials"])
    id_card = next(item for item in view["materials"] if item["id"] == "id_card")
    assert id_card["slots"] == ["正面", "反面"] and id_card["max_files"] == 2
    assert id_card["reason"] and id_card["form"]  # 必须告诉用户"为什么要交、怎么给"


def test_upload_enforces_slots_and_count():
    """具名槽位：一槽一张，缺一不算齐，多传一概不收。"""
    service = _service()
    scenario = _scenario("restaurant_open")
    intake = service.plan(scenario, RESTAURANT_ANSWERS)

    view = service.upload(scenario, intake, "id_card", "正面.jpg", "image/jpeg", _jpg(), slot="正面")
    id_card = next(item for item in view["materials"] if item["id"] == "id_card")
    assert id_card["status"] == PENDING and id_card["missing_slots"] == ["反面"]

    try:
        service.upload(scenario, intake, "id_card", "正面2.jpg", "image/jpeg", _jpg(), slot="正面")
        raise AssertionError("同一槽位重复上传本应被拒绝")
    except ValueError as exc:
        assert "已经交过了" in str(exc)

    try:
        service.upload(scenario, intake, "id_card", "x.jpg", "image/jpeg", _jpg(), slot="")
        raise AssertionError("具名槽位不指明槽位本应被拒绝")
    except ValueError as exc:
        assert "请指明" in str(exc)

    view = service.upload(scenario, intake, "id_card", "反面.jpg", "image/jpeg", _jpg(), slot="反面")
    id_card = next(item for item in view["materials"] if item["id"] == "id_card")
    assert id_card["status"] == PASSED and id_card["missing_slots"] == []

    try:
        service.upload(scenario, intake, "id_card", "多余.jpg", "image/jpeg", _jpg(), slot="反面")
        raise AssertionError("超过张数上限本应被拒绝")
    except ValueError as exc:
        assert "收满了" in str(exc)


def test_upload_rejects_bad_format_and_tiny_image():
    """形式校验挡格式/空文件；内容核验把过小的图判为"需补正"。"""
    service = _service()
    scenario = _scenario("restaurant_open")
    intake = service.plan(scenario, RESTAURANT_ANSWERS)

    try:
        service.upload(scenario, intake, "premises", "合同.txt", "text/plain", b"hello", slot="场所证明")
        raise AssertionError("不支持的格式本应被拒绝")
    except ValueError as exc:
        assert "格式收不了" in str(exc)

    try:
        service.upload(scenario, intake, "premises", "空.jpg", "image/jpeg", b"", slot="场所证明")
        raise AssertionError("空文件本应被拒绝")
    except ValueError as exc:
        assert "是空的" in str(exc)

    view = service.upload(scenario, intake, "premises", "小图.jpg", "image/jpeg", _tiny_jpg(), slot="场所证明")
    premises = next(item for item in view["materials"] if item["id"] == "premises")
    assert premises["status"] == NEED_FIX
    assert "重拍" in premises["files"][0]["reason"]


def test_need_fix_file_can_be_replaced_in_place():
    """需补正的那张不占名额，可以原地重传，旧文件被清掉。"""
    service = _service()
    scenario = _scenario("restaurant_open")
    intake = service.plan(scenario, RESTAURANT_ANSWERS)

    service.upload(scenario, intake, "premises", "小图.jpg", "image/jpeg", _tiny_jpg(), slot="场所证明")
    assert len(intake.files_of("premises")) == 1

    view = service.upload(scenario, intake, "premises", "清晰.jpg", "image/jpeg", _jpg(), slot="场所证明")
    premises = next(item for item in view["materials"] if item["id"] == "premises")
    assert premises["status"] == PASSED
    assert len(premises["files"]) == 1  # 补正的那张已被替换，没有堆积
    assert premises["files"][0]["filename"] == "清晰.jpg"


def test_multiple_pages_material_takes_1_to_max():
    """多页材料（公司章程）不固定页数，但不超过上限。"""
    service = _service()
    scenario = _scenario("enterprise_open")
    intake = service.plan(scenario, ENTERPRISE_ANSWERS)

    view = service.upload(scenario, intake, "articles", "章程1.jpg", "image/jpeg", _jpg())
    articles = next(item for item in view["materials"] if item["id"] == "articles")
    assert articles["status"] == PASSED  # 至少 1 张即算齐

    for index in range(2, 9):
        view = service.upload(scenario, intake, "articles", "章程" + str(index) + ".jpg",
                              "image/jpeg", _jpg())
    articles = next(item for item in view["materials"] if item["id"] == "articles")
    assert len(articles["files"]) == 8

    try:
        service.upload(scenario, intake, "articles", "章程9.jpg", "image/jpeg", _jpg())
        raise AssertionError("超过 max_files 本应被拒绝")
    except ValueError as exc:
        assert "收满了" in str(exc)


def test_remove_file_rolls_back_status():
    """撤回一张后，该项状态回落到待提交。"""
    service = _service()
    scenario = _scenario("restaurant_open")
    intake = service.plan(scenario, RESTAURANT_ANSWERS)
    service.upload(scenario, intake, "premises", "场所.jpg", "image/jpeg", _jpg(), slot="场所证明")

    file_id = intake.files_of("premises")[0].file_id
    view = service.remove(scenario, intake, "premises", file_id)
    premises = next(item for item in view["materials"] if item["id"] == "premises")
    assert premises["status"] == PENDING and premises["files"] == []


def test_persist_and_reload():
    """材料收集单与文件落盘后，重新打开存储仍能读回。"""
    service = _service()
    scenario = _scenario("restaurant_open")
    intake = service.plan(scenario, RESTAURANT_ANSWERS)
    service.upload(scenario, intake, "premises", "场所.jpg", "image/jpeg", _jpg(), slot="场所证明")

    reloaded = MaterialStore(intakes_file=service.store.intakes_file,
                             materials_dir=service.store.materials_dir)
    again = reloaded.get(intake.intake_id)
    assert again is not None
    assert again.materials == intake.materials
    record = again.files_of("premises")[0]
    path = reloaded.path_of(again, "premises", record.file_id)
    assert path is not None and path.read_bytes() == _jpg()


def test_material_gate_blocks_until_ready():
    """必交材料没齐就不允许受理；齐了之后才放行。"""
    from server.stream import material_gate

    service = _service()
    scenario = _scenario("restaurant_open")
    intake = service.plan(scenario, RESTAURANT_ANSWERS)

    blocked = material_gate(scenario, intake)
    assert len(blocked) == 4  # 4 份必交材料全没过

    _fill_all(service, scenario, intake)
    assert material_gate(scenario, intake) == []

    state = summary(material_specs(scenario, intake.materials), intake.files)
    assert state == {"total": 4, "passed": 4, "ready": True}


def test_resume_from_materials_produces_case():
    """材料齐备后从「材料核验」续跑，生成办理单且不再重播咨询。"""
    service = _service()
    scenario = _scenario("restaurant_open")
    intake = service.plan(scenario, RESTAURANT_ANSWERS)
    _fill_all(service, scenario, intake)

    agent = _agent(scenario)
    events = []
    trace, case = agent.run(RESTAURANT_ANSWERS["utterance"], RESTAURANT_ANSWERS,
                            on_event=events.append, intake=intake)

    stages = [stage for stage, _ in trace]
    assert "材料核验Agent" in stages
    assert "咨询Agent" not in stages      # 前四步已办过，不重复播报
    assert "部门子Agent" in stages

    assert case.materials == intake.materials          # 办理单存的是材料 id
    assert case.verify_report["passed"] == 4
    assert case.verify_report["status"] == "通过"

    flow = {node["key"]: node for node in case.flow}
    for key, _ in FLOW_NODES:
        assert flow[key]["status"] == STATUS_DONE
    assert all(status == MockGovServices.STAGES[-1] for status in case.item_status.values())

    types = [event.type for event in events]
    assert types[0] == "flow_node" and types[-1] == "finished"


def test_resume_rejects_incomplete_materials():
    """服务端兜底：材料没交齐就续跑，必须报错而不是悄悄受理。"""
    service = _service()
    scenario = _scenario("restaurant_open")
    intake = service.plan(scenario, RESTAURANT_ANSWERS)
    service.upload(scenario, intake, "premises", "场所.jpg", "image/jpeg", _jpg(), slot="场所证明")

    agent = _agent(scenario)
    try:
        agent.run(RESTAURANT_ANSWERS["utterance"], RESTAURANT_ANSWERS, intake=intake)
        raise AssertionError("材料没交齐本应被拒绝")
    except ValueError as exc:
        assert "还没交齐" in str(exc)


# ---------- 内容核验：桩规则 vs 视觉模型（见 app/materials/verify.py）----------

def _vision(replies, max_retries=0):
    """造一个"接了多模态模型"的核验器，用 FakeSession 喂预设回复，不联网。"""
    from app.materials.verify import VisionChecker
    from test_moma_client import FakeSession, no_sleep

    session = FakeSession(list(replies))
    moma = MoMAClient(api_base="https://x/v1", api_key="k", session=session,
                      sleep=no_sleep, max_retries=max_retries)
    return VisionChecker(moma, model="qwen-vl"), session


def _vision_reply(payload):
    from test_moma_client import ok
    return ok(payload)


def _id_card_spec():
    return {"id": "id_card", "name": "法定代表人身份证", "reason": "证明申请人身份的真实性",
            "accept": ["jpg", "jpeg", "png", "pdf"]}


def test_parse_verdict_tolerates_model_noise():
    """模型常把 JSON 包在代码块或解释文字里；解析不出来就返回 None（调用方据此回落）。"""
    from app.materials.verify import parse_verdict

    assert parse_verdict('{"ok": true, "reason": "清晰完整"}') == {"ok": True, "reason": "清晰完整"}
    assert parse_verdict('```json\n{"ok": false, "reason": "看不清"}\n```') == {
        "ok": False, "reason": "看不清"}
    assert parse_verdict('判断结果：{"ok": true} 以上。')["ok"] is True
    assert parse_verdict('{"ok": "true"}')["ok"] is True      # 布尔被写成字符串
    assert parse_verdict('{"ok": false}')["ok"] is False
    assert parse_verdict('{"ok": true}')["reason"] == ""

    for broken in ("", None, "没有 JSON", '{"reason": "缺 ok 字段"}', "{不是合法 JSON}", "[1, 2]"):
        assert parse_verdict(broken) is None, broken


def test_vision_checker_passes_clean_photo():
    """模型判合规 -> 通过，且真的发出了一次多模态请求。"""
    checker, session = _vision([_vision_reply('{"ok": true, "reason": "身份证正面清晰完整"}')])
    verdict = checker.check(_id_card_spec(), "front.jpg", _jpg(), slot="正面")

    assert verdict["result"] == "通过" and verdict["status"] == "已通过", verdict
    assert verdict["reason"] == ""
    assert len(session.calls) == 1, session.calls


def test_vision_messages_carry_text_and_image():
    """多模态消息形状：system + user（content 为数组，含文本与图片 data URL）。"""
    checker, session = _vision([_vision_reply('{"ok": true}')])
    checker.check(_id_card_spec(), "front.jpg", _jpg(), slot="正面")

    messages = session.calls[0]["json"]["messages"]
    assert messages[0]["role"] == "system"
    user = messages[1]
    assert user["role"] == "user" and isinstance(user["content"], list), user

    parts = [part["type"] for part in user["content"]]
    assert parts == ["text", "image_url"], parts
    ask = user["content"][0]["text"]
    assert "法定代表人身份证" in ask and "正面" in ask, ask
    assert "证明申请人身份的真实性" in ask, ask          # 用途也带上，模型判断才有依据
    image = user["content"][1]["image_url"]["url"]
    assert image.startswith("data:image/jpeg;base64,"), image[:48]


def test_vision_checker_flags_wrong_document():
    """模型判"不是这份材料" -> 需补正（不是拒收），原因是人话且转达模型给的理由。"""
    checker, _ = _vision([_vision_reply('{"ok": false, "reason": "这是一张猫的照片"}')])
    verdict = checker.check(_id_card_spec(), "front.jpg", _jpg(), slot="正面")

    assert verdict["result"] == "需补正" and verdict["status"] == "需补正", verdict
    assert "法定代表人身份证" in verdict["reason"], verdict
    assert "正面" in verdict["reason"], verdict
    assert "猫" in verdict["reason"], verdict            # 模型的理由要转达给用户
    assert "qwen" not in verdict["reason"].lower(), verdict   # 但不暴露模型名（docs/08）


def test_vision_checker_skips_non_image_and_huge_file():
    """非图片、超大图不送模型（省带宽），但核验照常完成。"""
    from app.materials.verify import VISION_MAX_BYTES

    checker, session = _vision([])      # 不给回复：一旦真的调模型就会露馅
    spec = {"id": "articles", "name": "公司章程", "accept": ["pdf", "jpg"]}

    # PDF 没有视觉信息 -> 桩规则
    assert checker.check(spec, "articles.pdf", b"%PDF-1.4" + b"\x00" * 20000)["result"] == "通过"
    # 超过送模型上限 -> 桩规则
    huge = _jpg(VISION_MAX_BYTES + 1024)
    assert checker.check(spec, "big.jpg", huge)["result"] == "通过"
    assert session.calls == [], session.calls


def test_vision_checker_falls_back_when_model_unavailable():
    """模型故障 / 返回乱码 / 没开模型 —— 一律回落桩规则，不能卡住办事。"""
    from app.materials.verify import VisionChecker
    spec = {"id": "premises", "name": "经营场所证明"}

    # 网络异常
    checker, _ = _vision([ConnectionError("net")])
    assert checker.check(spec, "p.jpg", _jpg())["result"] == "通过"

    # 返回无法解析的内容
    checker, _ = _vision([_vision_reply("我看不出来是什么")])
    assert checker.check(spec, "p.jpg", _jpg())["result"] == "通过"

    # 没开模型（桩模式）：complete 拿到空 fallback -> 解析失败 -> 回落
    checker = VisionChecker(MoMAClient(api_base="", api_key=""), model="qwen-vl")
    assert checker.check(spec, "p.jpg", _jpg())["result"] == "通过"

    # 回落之后，"图片过小 -> 需补正"的闭环仍然有效
    assert checker.check(spec, "p.jpg", _tiny_jpg())["result"] == "需补正"


def test_build_checker_selects_by_live_model():
    """没配模型就给桩核验器——省掉"先把整张图 base64、再发现走不通"的浪费。"""
    from app.materials.verify import (StubChecker, VisionChecker, build_checker)
    from test_moma_client import FakeSession, no_sleep

    assert isinstance(build_checker(None), StubChecker)
    assert isinstance(build_checker(MoMAClient(api_base="", api_key="")), StubChecker)

    live = MoMAClient(api_base="https://x/v1", api_key="k", session=FakeSession([]),
                      sleep=no_sleep)
    checker = build_checker(live, model="qwen-vl")
    assert isinstance(checker, VisionChecker) and checker.model == "qwen-vl"


def test_form_check_runs_before_model():
    """形式校验优先：格式不对直接拒收，不该浪费一次模型调用。"""
    from app.materials.verify import check_file

    checker, session = _vision([_vision_reply('{"ok": true}')])
    verdict = check_file(_id_card_spec(), "id_card.exe", _jpg(), checker=checker)

    assert verdict["result"] == "不通过", verdict
    assert session.calls == [], session.calls


def test_service_and_agent_actually_use_the_checker():
    """接线：MaterialService 与 VerifyAgent 都要把核验器与槽位真的用上。

    （本项目出过两次"写好了没人调"：SessionContext.history() 与 KnowledgeBase.retrieve()，
    所以这条测试专门盯接线。）
    """
    from app.agents.verify_agent import VerifyAgent
    from app.materials.verify import StubChecker, VisionChecker
    from test_moma_client import FakeSession, no_sleep

    # 1) MaterialService：把核验器与槽位传下去
    seen = []

    class SpyChecker:
        def check(self, spec, filename, content, slot=""):
            seen.append((spec["id"], slot))
            return {"result": "通过", "status": "已通过", "reason": ""}

    slot_no = next(_SEQ)
    service = MaterialService(
        store=MaterialStore(
            intakes_file=TMP / ("spy" + str(slot_no)) / "intakes.json",
            materials_dir=TMP / ("spy" + str(slot_no)) / "materials",
        ),
        checker=SpyChecker(),
    )
    scenario = _scenario("restaurant_open")
    intake = service.plan(scenario, RESTAURANT_ANSWERS)
    service.upload(scenario, intake, "id_card", "front.jpg", "image/jpeg", _jpg(), slot="正面")
    assert seen == [("id_card", "正面")], seen

    # 2) VerifyAgent：材料核验走子 Agent 端点；配了模型就装视觉核验器
    assert VerifyAgent.role == "sub"
    stub_agent = VerifyAgent(MoMAClient(api_base="", api_key=""), SessionContext())
    assert isinstance(stub_agent.checker, StubChecker)

    session = FakeSession([_vision_reply('{"ok": true}')])
    agent = VerifyAgent(
        MoMAClient(api_base="https://x/v1", api_key="k", session=session, sleep=no_sleep),
        SessionContext(),
    )
    assert isinstance(agent.checker, VisionChecker)
    verdict = agent.check_file(_id_card_spec(), "front.jpg", _jpg(), slot="正面")
    assert verdict["result"] == "通过", verdict
    assert len(session.calls) == 1, session.calls


if __name__ == "__main__":
    test_plan_follows_condition_rules()
    test_upload_enforces_slots_and_count()
    test_upload_rejects_bad_format_and_tiny_image()
    test_need_fix_file_can_be_replaced_in_place()
    test_multiple_pages_material_takes_1_to_max()
    test_remove_file_rolls_back_status()
    test_persist_and_reload()
    test_material_gate_blocks_until_ready()
    test_resume_from_materials_produces_case()
    test_resume_rejects_incomplete_materials()
    test_parse_verdict_tolerates_model_noise()
    test_vision_checker_passes_clean_photo()
    test_vision_messages_carry_text_and_image()
    test_vision_checker_flags_wrong_document()
    test_vision_checker_skips_non_image_and_huge_file()
    test_vision_checker_falls_back_when_model_unavailable()
    test_build_checker_selects_by_live_model()
    test_form_check_runs_before_model()
    test_service_and_agent_actually_use_the_checker()
    print("ALL MATERIALS TESTS PASSED")
