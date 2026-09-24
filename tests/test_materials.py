"""冒烟测试：材料提交链路（材料清单 -> 逐张上传核验 -> 齐备后才受理）。

跑法（在项目根目录）：python tests/test_materials.py
"""
import atexit
import itertools
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

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
    print("ALL MATERIALS TESTS PASSED")
