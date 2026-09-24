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
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
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


def _png(width, height, size=20 * 1024) -> bytes:
    """造一张"真 PNG 头"的图：体积够大，但分辨率可以很低。"""
    header = (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR"
              + width.to_bytes(4, "big") + height.to_bytes(4, "big"))
    return header + b"\x00" * (size - len(header))


def _jpeg(width, height, size=20 * 1024) -> bytes:
    """造一张"真 JPEG 头"（含 SOF0 尺寸段）的图。"""
    sof = (b"\xff\xc0" + (17).to_bytes(2, "big") + b"\x08"
           + height.to_bytes(2, "big") + width.to_bytes(2, "big")
           + b"\x03" + b"\x01\x11\x00" + b"\x02\x11\x00" + b"\x03\x11\x00")
    body = b"\xff\xd8\xff\xe0" + (16).to_bytes(2, "big") + b"\x00" * 14 + sof
    return body + b"\x00" * (size - len(body))


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
        text = str(exc)
        assert ".txt" in text, text          # 说清"你传的是什么"
        assert "jpg" in text, text           # 说清"只收什么"
        assert "转成" in text, text          # 说清"怎么改"

    try:
        service.upload(scenario, intake, "premises", "空.jpg", "image/jpeg", b"", slot="场所证明")
        raise AssertionError("空文件本应被拒绝")
    except ValueError as exc:
        assert "0 字节" in str(exc), str(exc)

    view = service.upload(scenario, intake, "premises", "小图.jpg", "image/jpeg", _tiny_jpg(), slot="场所证明")
    premises = next(item for item in view["materials"] if item["id"] == "premises")
    assert premises["status"] == NEED_FIX
    assert "516B" in premises["files"][0]["reason"]      # 说清"这张图到底多大"


def test_errors_tell_the_user_how_to_fix():
    """每条"不能收 / 要重传"的说明都要回答三件事：什么问题、为什么、怎么改。

    这是产品要求不是文案偏好——办事人看完提示要能直接动手，
    所以断言"说清了没有"，而不是断言某句具体措辞（措辞会改）。
    """
    from app.materials.verify import (DEFAULT_MAX_FILE_BYTES, StubChecker,
                                      form_check, human_size)

    spec = {"id": "premises", "name": "经营场所证明", "accept": ["jpg", "pdf"],
            "fix_hint": "拍产权证的地址页与盖章页，整页进画面。"}

    # 体积超限：实际大小 + 上限 + 具体怎么压
    oversized = b"\x00" * (DEFAULT_MAX_FILE_BYTES + 1024)
    text = form_check(spec, "big.jpg", oversized)["reason"]
    assert human_size(len(oversized)) in text, text       # 你这个多大
    assert human_size(DEFAULT_MAX_FILE_BYTES) in text, text   # 上限多少
    assert "压缩" in text and "分辨率" in text, text        # 怎么改

    # 格式不对：你传的是什么、只收什么、怎么转
    text = form_check(spec, "scan.tiff", b"x" * 100)["reason"]
    assert ".tiff" in text and "jpg" in text and "另存为" in text, text

    # 内容核验：过小的图要有具体体积，且用上场景配置的"怎么改"
    text = StubChecker().check(spec, "small.jpg", b"\x00" * 516)["reason"]
    assert "516B" in text, text
    assert "地址页" in text, text        # fix_hint 被采用了

    # 场景没配 fix_hint 时也要有兜底动作
    text = StubChecker().check({"id": "x", "name": "其他材料"}, "s.jpg", b"\x00" * 516)["reason"]
    assert "重新拍" in text and "四角" in text, text


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

    assert parse_verdict('{"ok": true, "problem": "", "fix": ""}') == {
        "ok": True, "problem": "", "fix": ""}
    assert parse_verdict('```json\n{"ok": false, "problem": "看不清", "fix": "重拍"}\n```') == {
        "ok": False, "problem": "看不清", "fix": "重拍"}
    assert parse_verdict('判断结果：{"ok": true} 以上。')["ok"] is True
    assert parse_verdict('{"ok": "true"}')["ok"] is True      # 布尔被写成字符串
    assert parse_verdict('{"ok": false}')["ok"] is False
    # 老契约只回 reason：当作 problem 用，不至于白白丢掉模型给的说明
    assert parse_verdict('{"ok": false, "reason": "太暗了"}')["problem"] == "太暗了"

    for broken in ("", None, "没有 JSON", '{"reason": "缺 ok 字段"}', "{不是合法 JSON}", "[1, 2]"):
        assert parse_verdict(broken) is None, broken


def test_clean_text_keeps_it_showable_and_safe():
    """模型的话要能直接给群众看：压平换行、限长、屏蔽长数字串（证件号不落盘）。"""
    from app.materials.verify import clean_text

    assert clean_text("画面里\n有一只猫  ") == "画面里 有一只猫"
    assert clean_text("证件号 110101199003071234 看不清") == "证件号 …… 看不清"
    assert clean_text("看不清第 5 位") == "看不清第 5 位"     # 短数字不动
    assert clean_text("结尾有句号。") == "结尾有句号"
    assert clean_text("") == "" and clean_text(None) == ""
    assert len(clean_text("模" * 300)) == 121                # 限长（120 字 + 省略号）


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
    """模型判"不是这份材料" -> 需补正（不是拒收），问题与动作都要转达成人话。"""
    checker, _ = _vision([_vision_reply(
        '{"ok": false, "problem": "画面里是一只猫", "fix": "把身份证正面平放，四角进画面再拍"}')])
    verdict = checker.check(_id_card_spec(), "front.jpg", _jpg(), slot="正面")

    text = verdict["reason"]
    assert verdict["result"] == "需补正" and verdict["status"] == "需补正", verdict
    assert "法定代表人身份证" in text and "正面" in text, text
    assert "一只猫" in text, text                     # 模型说的问题原样转达（比"看不清"具体）
    assert "四角进画面" in text, text                  # 模型给的动作可以直接照做
    assert "qwen" not in text.lower(), text           # 但不暴露模型名（docs/08 文案规范）

    # 老契约（只回 reason）也要认
    checker, _ = _vision([_vision_reply('{"ok": false, "reason": "太模糊"}')])
    assert "太模糊" in checker.check(_id_card_spec(), "f.jpg", _jpg(), slot="正面")["reason"]

    # 模型没说怎么改时，用场景配置的 fix_hint（{slot} 会被替换成具体槽位）
    spec = dict(_id_card_spec(), fix_hint="把身份证「{slot}」平放再拍。")
    checker, _ = _vision([_vision_reply('{"ok": false, "problem": "太暗"}')])
    text = checker.check(spec, "f.jpg", _jpg(), slot="正面")["reason"]
    assert "太暗" in text and "把身份证「正面」平放再拍。" in text, text


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


def test_image_size_reads_jpeg_and_png_headers():
    """零依赖读像素尺寸；读不出就返回 None（调用方据此不做分辨率判断）。"""
    from app.materials.verify import image_size

    assert image_size(_png(1080, 1920)) == (1080, 1920)
    assert image_size(_jpeg(1600, 1200)) == (1600, 1200)

    # 读不出的情况：宁可少判一条，也不能把好图误判成"看不清"
    assert image_size(b"not an image") is None
    assert image_size(b"\x89PNG\r\n\x1a\n") is None     # 头不全
    assert image_size(_jpg()) is None                   # 假 jpg，没有 SOF 段


def test_local_rules_catch_low_resolution_without_the_model():
    """分工：客观硬伤由本地规则判，**一次模型调用都不该花**。

    体积够大但只有 320×240 的图——体积规则抓不到，得靠读文件头拿像素尺寸。
    """
    from app.materials.verify import StubChecker

    spec = {"id": "id_card", "name": "法定代表人身份证", "reason": "证明身份",
            "fix_hint": "把身份证「{slot}」平放再拍。"}
    small = _png(320, 240)

    # 没配模型时，桩核验独立就能拦下
    verdict = StubChecker().check(spec, "s.png", small, slot="正面")
    assert verdict["result"] == "需补正", verdict
    assert "320×240" in verdict["reason"], verdict
    assert "把身份证「正面」平放再拍。" in verdict["reason"], verdict

    # 配了模型时：本地先判，模型一次都不调
    checker, session = _vision([_vision_reply('{"ok": true}')])
    assert checker.check(spec, "s.png", small, slot="正面")["result"] == "需补正"
    assert session.calls == [], session.calls


def test_local_pass_still_goes_to_the_model():
    """反过来：本地判不出问题时才真的把图交给模型——否则多模态就白接了。"""
    checker, session = _vision([_vision_reply('{"ok": true}')])
    spec = {"id": "id_card", "name": "法定代表人身份证", "reason": "证明身份"}

    verdict = checker.check(spec, "big.png", _png(1080, 1920), slot="正面")
    assert verdict["result"] == "通过", verdict
    assert len(session.calls) == 1, session.calls        # 高清图才值得问语义

    parts = session.calls[0]["json"]["messages"][1]["content"]
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,"), parts[1]


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


def test_service_switches_to_vision_when_model_configured():
    """接线：配了多模态模型，MaterialService 会自动从桩核验切到视觉核验。

    这是"多模态材料核验"能不能生效的那根线。单测 `build_checker` 不够——
    要确认服务是拿同一个 moma 去装配的，否则会出现"核验器能造出来、服务却不用"的假接线。
    """
    from app.materials.verify import StubChecker, VisionChecker
    from test_moma_client import FakeSession, no_sleep

    def service_in(name):
        return MaterialService(
            store=MaterialStore(intakes_file=TMP / name / "intakes.json",
                                materials_dir=TMP / name / "materials"),
            moma=None,
        )

    # 默认（没配模型）：桩核验
    assert isinstance(service_in("switch_stub").checker, StubChecker)

    # 配了子端点：自动切到视觉核验，模型名取自 vision 池
    live = MaterialService(
        store=MaterialStore(intakes_file=TMP / "switch_live" / "intakes.json",
                            materials_dir=TMP / "switch_live" / "materials"),
        moma=MoMAClient(api_base="https://x/v1", api_key="k",
                        session=FakeSession([]), sleep=no_sleep),
    )
    assert isinstance(live.checker, VisionChecker), live.checker
    assert live.checker.model == "qwen-vl", live.checker.model


# ---------- 真实 HTTP 通路（配了模型时）----------

class _LoopbackUpstream:
    """一个最小的 OpenAI 兼容端点，用来验证"配了模型"这条真实通路。

    它只做两件真事：把收到的请求记下来、按用例指定的内容回复。这样能验证
    base64 图片真的发出去了、回复真的被解析成了用户提示——
    **唯一没验的只剩"模型本身的判断力"，那需要真 key。**
    """

    def __init__(self, reply):
        self.reply = reply
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                outer.requests.append({
                    "path": self.path,
                    "auth": self.headers.get("Authorization"),
                    "json": json.loads(self.rfile.read(length) or b"{}"),
                })
                raw = json.dumps(
                    {"choices": [{"message": {"content": outer.reply}}]}
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):
                pass        # 别把访问日志混进测试输出

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self):
        return "http://127.0.0.1:" + str(self.server.server_address[1]) + "/v1"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def test_live_path_sends_image_and_applies_model_verdict():
    """配了模型时，真实 HTTP 通路整条要走通：发 base64 图片 -> 解析回复 -> 变成用户提示。"""
    from app.materials.verify import VisionChecker

    upstream = _LoopbackUpstream(
        '{"ok": false, "problem": "画面里是一张餐桌", "fix": "把身份证平放在桌面上再拍"}')
    try:
        no = next(_SEQ)
        service = MaterialService(
            store=MaterialStore(intakes_file=TMP / ("live" + str(no)) / "intakes.json",
                                materials_dir=TMP / ("live" + str(no)) / "materials"),
            moma=MoMAClient(api_base=upstream.base_url, api_key="test-key"),
        )
        assert isinstance(service.checker, VisionChecker), service.checker

        scenario = _scenario("restaurant_open")
        intake = service.plan(scenario, RESTAURANT_ANSWERS)
        view = service.upload(scenario, intake, "id_card", "front.png", "image/png",
                              _png(1080, 1920), slot="正面")

        # 1) 请求真的发到了上游，形状是 OpenAI 兼容的多模态
        assert len(upstream.requests) == 1, upstream.requests
        sent = upstream.requests[0]
        assert sent["path"].endswith("/chat/completions"), sent["path"]
        assert sent["auth"] == "Bearer test-key", sent["auth"]
        parts = sent["json"]["messages"][1]["content"]
        assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,"), parts[1]

        # 2) 回复被解析成对用户可见的补正提示
        id_card = next(item for item in view["materials"] if item["id"] == "id_card")
        assert id_card["status"] == NEED_FIX, id_card
        reason = id_card["files"][0]["reason"]
        assert "法定代表人身份证" in reason, reason
        assert "画面里是一张餐桌" in reason, reason            # 模型说的问题转达给用户
        assert "把身份证平放在桌面上再拍" in reason, reason      # 模型给的动作也带上
    finally:
        upstream.close()


if __name__ == "__main__":
    test_plan_follows_condition_rules()
    test_upload_enforces_slots_and_count()
    test_upload_rejects_bad_format_and_tiny_image()
    test_errors_tell_the_user_how_to_fix()
    test_need_fix_file_can_be_replaced_in_place()
    test_multiple_pages_material_takes_1_to_max()
    test_remove_file_rolls_back_status()
    test_persist_and_reload()
    test_material_gate_blocks_until_ready()
    test_resume_from_materials_produces_case()
    test_resume_rejects_incomplete_materials()
    test_parse_verdict_tolerates_model_noise()
    test_clean_text_keeps_it_showable_and_safe()
    test_vision_checker_passes_clean_photo()
    test_vision_messages_carry_text_and_image()
    test_vision_checker_flags_wrong_document()
    test_vision_checker_skips_non_image_and_huge_file()
    test_image_size_reads_jpeg_and_png_headers()
    test_local_rules_catch_low_resolution_without_the_model()
    test_local_pass_still_goes_to_the_model()
    test_vision_checker_falls_back_when_model_unavailable()
    test_build_checker_selects_by_live_model()
    test_form_check_runs_before_model()
    test_service_and_agent_actually_use_the_checker()
    test_service_switches_to_vision_when_model_configured()
    test_live_path_sends_image_and_applies_model_verdict()
    print("ALL MATERIALS TESTS PASSED")
