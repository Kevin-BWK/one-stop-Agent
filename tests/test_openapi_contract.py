"""前后端契约一致性测试：后端 OpenAPI **↔** 前端 `contract.ts`（见 `docs/07`）。

为什么要有它：
- 前后端是两个工程（`server/` 与 `frontend/`），契约原先**只有前端一份定义**
  （`frontend/src/types/contract.ts`），后端改字段名没有任何机制能发现 → 前端静默坏掉；
- 现在后端用 Pydantic 声明了响应模型（`server/schemas.py` + 路由的 `response_model`），
  本文件拿 FastAPI 的 OpenAPI schema 做三项校验：

1. **所有返回 JSON 的路由都声明了响应模型**——否则 OpenAPI 里没有 schema，契约仍是空的；
2. **前端用到的字段，后端模型里必须都有**——后端可以更宽（多字段无害），但不能少；
3. 事件外壳是 `{type, data}`，与前端 `OutboundEvent` 一致。

用法：python tests/test_openapi_contract.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.main import create_app

CONTRACT_TS = ROOT / "frontend" / "src" / "types" / "contract.ts"

# 应当返回 JSON 的路由（SSE / WebSocket / 文件流不在此列）
JSON_ROUTES = (
    ("get", "/health"),
    ("post", "/api/session"),
    ("post", "/api/chat"),
    ("post", "/api/fields"),
    ("get", "/api/cases/{case_id}"),
    ("get", "/api/sessions/{session_id}"),
    ("get", "/scenarios/{scenario_id}"),
    ("post", "/api/preview"),
    ("post", "/api/ask"),
    ("post", "/api/materials/intake"),
    ("get", "/api/materials/{intake_id}"),
    ("post", "/api/materials/{intake_id}/{material_id}/files"),
    ("delete", "/api/materials/{intake_id}/{material_id}/files/{file_id}"),
)

# 路由 -> 期望绑定的响应模型（防止绑错模型）
EXPECTED_MODELS = {
    ("get", "/health"): "HealthOut",
    ("post", "/api/session"): "TurnResponse",
    ("post", "/api/chat"): "TurnResponse",
    ("post", "/api/fields"): "TurnResponse",
    ("get", "/api/cases/{case_id}"): "CaseOut",
    ("get", "/api/sessions/{session_id}"): "TurnResponse",
    ("get", "/scenarios/{scenario_id}"): "ScenarioOut",
    ("post", "/api/preview"): "PreviewOut",
    ("post", "/api/ask"): "AskResponse",
    ("post", "/api/materials/intake"): "MaterialViewOut",
    ("get", "/api/materials/{intake_id}"): "MaterialViewOut",
}

# 前端 interface -> 后端 OpenAPI 模型（前端字段必须是后端的子集）
FIELD_PAIRS = (
    ("MaterialView", "MaterialViewOut"),
    ("MaterialItem", "MaterialItemOut"),
    ("MaterialFile", "MaterialFileOut"),
    ("MaterialSummary", "MaterialSummaryOut"),
    ("ConditionPreview", "PreviewOut"),
)

_SCHEMA = None


def _schema():
    global _SCHEMA
    if _SCHEMA is None:
        _SCHEMA = create_app().openapi()
    return _SCHEMA


def _operation(schema, method, path):
    return (schema.get("paths", {}).get(path) or {}).get(method) or {}


def _ok_content(schema, method, path):
    return ((_operation(schema, method, path).get("responses") or {})
            .get("200") or {}).get("content") or {}


def _ts_fields(source, name):
    """从 contract.ts 里抠出某个 interface 的字段名（值类型不换行）。"""
    match = re.search(r"export interface " + re.escape(name) + r"\s*\{(.*?)\n\}", source, re.S)
    if match is None:
        raise AssertionError("contract.ts 里找不到 interface " + name)
    fields = set()
    for raw in match.group(1).splitlines():
        line = raw.split("//")[0].strip()
        found = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\??\s*:", line)
        if found:
            fields.add(found.group(1))
    return fields


def test_every_json_route_declares_response_model():
    """契约不能只活在前端：每个返回 JSON 的路由都得有响应模型。"""
    schema = _schema()
    missing = []
    for method, path in JSON_ROUTES:
        if "application/json" not in _ok_content(schema, method, path):
            missing.append(method.upper() + " " + path)
    assert not missing, ("这些接口没有声明响应模型（OpenAPI 里没有 JSON schema）："
                         + "、".join(missing))


def test_routes_bound_to_expected_models():
    """路由要绑到预期的具名模型，而不是随便一个模型。"""
    schema = _schema()
    problems = []
    for (method, path), model in EXPECTED_MODELS.items():
        ref = ((_ok_content(schema, method, path).get("application/json") or {})
               .get("schema") or {}).get("$ref", "")
        if not ref.endswith("/" + model):
            problems.append(method.upper() + " " + path + " -> " + (ref or "（无模型）")
                            + "（应为 " + model + "）")
    assert not problems, "响应模型绑定不对：" + "；".join(problems)


def test_frontend_fields_exist_in_backend_models():
    """前端用到的字段，后端模型里必须都有——防"后端改名、前端静默坏掉"。"""
    schema = _schema()
    source = CONTRACT_TS.read_text(encoding="utf-8")
    components = (schema.get("components") or {}).get("schemas") or {}
    problems = []
    for ts_name, model in FIELD_PAIRS:
        properties = set((components.get(model) or {}).get("properties") or {})
        assert properties, "OpenAPI 里找不到模型或有模型的字段：" + model
        missing = sorted(_ts_fields(source, ts_name) - properties)
        if missing:
            problems.append(ts_name + " → " + model + " 缺：" + "、".join(missing))
    assert not problems, "前后端契约不一致：" + "；".join(problems)


def test_event_shell_is_type_and_data():
    """事件外壳 `{type, data}`：后端 Event.to_dict()、EventOut、前端 OutboundEvent 三者一致。"""
    from app.orchestrator.events import Event
    from server.schemas import EventOut

    payload = Event("message", {"text": "hi"}).to_dict()
    assert set(payload) == {"type", "data"}, payload
    assert set(EventOut.model_fields) == {"type", "data"}
    assert "OutboundEvent" in CONTRACT_TS.read_text(encoding="utf-8")


def test_scenario_out_does_not_drop_config_fields():
    """场景配置是"配置即业务"：加 response_model 不能把配置字段裁掉（extra=allow）。"""
    from server.schemas import ScenarioOut

    raw = {
        "id": "restaurant_open", "name": "开办餐饮店一件事", "opening": "想开面馆",
        "collect_fields": [{"key": "area"}], "items": {"A": {"name": "营业执照"}},
        # 未来新增的配置键，不能因为没在模型里声明就被丢掉
        "future_field": {"anything": 1},
    }
    dumped = ScenarioOut(**raw).model_dump()
    assert dumped["future_field"] == {"anything": 1}, dumped
    assert dumped["items"]["A"]["name"] == "营业执照"


def main():
    test_every_json_route_declares_response_model()
    test_routes_bound_to_expected_models()
    test_frontend_fields_exist_in_backend_models()
    test_event_shell_is_type_and_data()
    test_scenario_out_does_not_drop_config_fields()
    print("OPENAPI CONTRACT PASSED")


if __name__ == "__main__":
    main()
