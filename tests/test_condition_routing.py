"""条件判定（智能路由）的规则矩阵测试——纯规则层。

为什么单独一个文件：条件判定是**纯函数**（`scenario + fields -> items/materials/notes`），
跟 MoMA 在线/离线、HTTP 契约、材料上传都无关。把它混在 e2e 里会"跑得慢、定位差、改得贵"。

分工约定：

- **本文件**：规则矩阵的唯一权威——每个比较方式、每条规则、边界值、组合、反向、配置一致性；
- 其他测试文件（`test_flow` / `test_server_smoke` / `test_api_e2e`）：只留一条
  "输入真的流进了规则引擎"的集成冒烟，规则细节不在这里重复。

零依赖、零网络、零文件写入：python tests/test_condition_routing.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.agents.condition_agent import evaluate_conditions, match_condition


def _scenario(scenario_id):
    with open(ROOT / "scenarios" / (scenario_id + ".json"), encoding="utf-8-sig") as f:
        return json.load(f)


RESTAURANT = _scenario("restaurant_open")
ENTERPRISE = _scenario("enterprise_open")

RESTAURANT_BASE_ITEMS = ["A_license", "B_food_permit", "E_health_cert"]
RESTAURANT_BASE_MATERIALS = ["id_card", "premises", "layout"]
ENTERPRISE_BASE_ITEMS = ["A_license", "B_tax", "C_social", "E_seal"]
ENTERPRISE_BASE_MATERIALS = ["legal_id_card", "address_proof", "articles"]


def fields(**kwargs):
    """构造"已采集的字段"。

    故意只放入显式给定的字段：字段缺失时规则不命中，这正是预判能安全作用于
    "填了一半"的表单的原因（见 match_condition 的文档）。
    """
    return dict(kwargs)


# ---------- 基础：没有规则命中时只给基础清单 ----------

def test_base_lists_match_scenario_config():
    """兜底：本文件写死的基础清单要与场景配置一致（防止配置改了测试没跟着改）。"""
    assert RESTAURANT["base_items"] == RESTAURANT_BASE_ITEMS
    assert RESTAURANT["base_materials"] == RESTAURANT_BASE_MATERIALS
    assert ENTERPRISE["base_items"] == ENTERPRISE_BASE_ITEMS
    assert ENTERPRISE["base_materials"] == ENTERPRISE_BASE_MATERIALS


def test_no_rule_hit_returns_base_only():
    """冷食/无油烟、80㎡、不生食、不设招牌 -> 只有基础事项与材料，且没有判定说明。"""
    items, materials, notes = evaluate_conditions(RESTAURANT, fields(
        business_type="冷食/无油烟", area_sqm=80, has_raw_food=False, signboard=False))
    assert items == RESTAURANT_BASE_ITEMS, items
    assert materials == RESTAURANT_BASE_MATERIALS, materials
    assert notes == [], notes


def test_empty_fields_return_base_only():
    """字段还没采集时不凭空断言：只剩基础清单（预判的安全性来源）。"""
    for scenario, expect_items, expect_materials in (
        (RESTAURANT, RESTAURANT_BASE_ITEMS, RESTAURANT_BASE_MATERIALS),
        (ENTERPRISE, ENTERPRISE_BASE_ITEMS, ENTERPRISE_BASE_MATERIALS),
    ):
        items, materials, notes = evaluate_conditions(scenario, {})
        assert items == expect_items, items
        assert materials == expect_materials, materials
        assert notes == [], notes


# ---------- 逐条规则（餐饮店）----------

def test_rule_hot_food_adds_oil_purifier():
    """经营热食 -> 加「油烟净化设施证明」；冷食/蒸煮不加。"""
    _, hot, notes = evaluate_conditions(RESTAURANT, fields(business_type="热食/有油烟"))
    assert hot == RESTAURANT_BASE_MATERIALS + ["oil_purifier"], hot
    assert any("油烟" in note for note in notes), notes

    for other in ("冷食/无油烟", "蒸煮"):
        _, materials, _ = evaluate_conditions(RESTAURANT, fields(business_type=other))
        assert "oil_purifier" not in materials, (other, materials)


def test_rule_area_threshold_boundary():
    """面积 >=300㎡ 才要消防检查（边界值 299 / 300 都要测）。"""
    for area, expect in ((80, False), (299, False), (300, True), (500, True)):
        items, _, _ = evaluate_conditions(RESTAURANT, fields(area_sqm=area))
        assert ("C_fire" in items) is expect, (area, items)


def test_rule_area_ignores_non_numeric_value():
    """面积还没填（空串）或填了非数字时，阈值规则不该命中。"""
    for value in ("", None, "abc"):
        items, _, _ = evaluate_conditions(RESTAURANT, fields(area_sqm=value))
        assert "C_fire" not in items, (value, items)


def test_rule_raw_food_adds_cold_room():
    """经营生食/冷食/自制饮品 -> 加「专间布局图」。"""
    _, yes, notes = evaluate_conditions(RESTAURANT, fields(has_raw_food=True))
    assert yes == RESTAURANT_BASE_MATERIALS + ["cold_room"], yes
    assert any("专间" in note for note in notes), notes

    _, no, _ = evaluate_conditions(RESTAURANT, fields(has_raw_food=False))
    assert "cold_room" not in no, no


def test_rule_signboard_adds_city_approval():
    """设置户外招牌 -> 加「户外招牌设施设置」（城管）。"""
    yes, _, notes = evaluate_conditions(RESTAURANT, fields(signboard=True))
    assert "D_signboard" in yes, yes
    assert any("招牌" in note for note in notes), notes

    no, _, _ = evaluate_conditions(RESTAURANT, fields(signboard=False))
    assert "D_signboard" not in no, no


# ---------- 逐条规则（企业）----------

def test_rule_bank_appointment():
    """同步预约银行开户 -> 加「银行开户预约」。"""
    yes, _, notes = evaluate_conditions(ENTERPRISE, fields(need_bank=True))
    assert "D_bank" in yes, yes
    assert any("银行" in note for note in notes), notes

    no, _, _ = evaluate_conditions(ENTERPRISE, fields(need_bank=False))
    assert "D_bank" not in no, no


def test_rule_employees_threshold_boundary():
    """拟用工 >=10 人 才需要用工备案（边界值 9 / 10 都要测）。"""
    for count, expect in ((0, False), (9, False), (10, True), (50, True)):
        _, materials, _ = evaluate_conditions(ENTERPRISE, fields(employees=count))
        assert ("labor_filing" in materials) is expect, (count, materials)


# ---------- 组合与去重 ----------

def test_restaurant_all_rules_combined():
    """餐饮店全开：基础 3 事 3 材 + 消防 + 招牌 + 油烟 + 专间，顺序为 基础在前、按规则追加。"""
    items, materials, notes = evaluate_conditions(RESTAURANT, fields(
        business_type="热食/有油烟", area_sqm=500, has_raw_food=True, signboard=True))

    assert items == RESTAURANT_BASE_ITEMS + ["C_fire", "D_signboard"], items
    assert materials == RESTAURANT_BASE_MATERIALS + ["oil_purifier", "cold_room"], materials
    assert len(notes) == 4, notes                       # 4 条规则全部命中
    assert len(items) == len(set(items)), items         # 不重复
    assert len(materials) == len(set(materials)), materials


def test_enterprise_all_rules_combined():
    items, materials, notes = evaluate_conditions(ENTERPRISE, fields(need_bank=True, employees=10))
    assert items == ENTERPRISE_BASE_ITEMS + ["D_bank"], items
    assert materials == ENTERPRISE_BASE_MATERIALS + ["labor_filing"], materials
    assert len(notes) == 2, notes


def test_notes_only_for_triggered_rules():
    """判定说明的条数必须等于命中规则的条数（不多说也不少说）。"""
    _, _, none = evaluate_conditions(RESTAURANT, fields(business_type="蒸煮"))
    assert none == []

    _, _, two = evaluate_conditions(RESTAURANT, fields(
        business_type="热食/有油烟", signboard=True))
    assert len(two) == 2, two


def test_duplicate_additions_are_deduped():
    """规则重复加同一个 id 时要去重，且保持原有顺序。"""
    synthetic = {
        "base_items": ["A"],
        "base_materials": ["m1"],
        "condition_rules": [
            {"if": {"field": "flag", "bool": True},
             "add_items": ["A", "B"], "add_materials": ["m1", "m2"], "note": "n1"},
        ],
    }
    items, materials, _ = evaluate_conditions(synthetic, {"flag": True})
    assert items == ["A", "B"], items
    assert materials == ["m1", "m2"], materials


# ---------- 配置一致性 ----------

def test_produced_ids_are_defined_in_scenario():
    """产出的每个 id 都必须在场景里定义——防止配置漏写导致前端拿不到中文名。"""
    cases = (
        (RESTAURANT, {"business_type": "热食/有油烟", "area_sqm": 500,
                      "has_raw_food": True, "signboard": True}),
        (ENTERPRISE, {"need_bank": True, "employees": 10}),
    )
    for scenario, all_on in cases:
        items, materials, _ = evaluate_conditions(scenario, all_on)
        for item_id in items:
            assert item_id in scenario["items"], (scenario["id"], item_id)
        for material_id in materials:
            assert material_id in scenario["materials"], (scenario["id"], material_id)


def test_rule_references_existing_fields():
    """条件规则引用的字段必须在 collect_fields 里声明过（防止规则永远不生效）。"""
    for scenario in (RESTAURANT, ENTERPRISE):
        declared = {spec["key"] for spec in scenario["collect_fields"]}
        for rule in scenario["condition_rules"]:
            assert rule["if"]["field"] in declared, (scenario["id"], rule)


# ---------- 比较方式本身 ----------

def test_match_operators():
    """四种比较方式各自的行为，以及未知操作符 / 缺字段时不命中。"""
    assert match_condition({"field": "x", "eq": 1}, {"x": 1}) is True
    assert match_condition({"field": "x", "eq": 1}, {"x": 2}) is False

    assert match_condition({"field": "x", "in": ["a", "b"]}, {"x": "a"}) is True
    assert match_condition({"field": "x", "in": ["a", "b"]}, {"x": "c"}) is False

    assert match_condition({"field": "x", "gte": 300}, {"x": 300}) is True
    assert match_condition({"field": "x", "gte": 300}, {"x": 299}) is False

    assert match_condition({"field": "x", "bool": True}, {"x": True}) is True
    assert match_condition({"field": "x", "bool": True}, {"x": False}) is False

    assert match_condition({"field": "x", "unknown": 1}, {"x": 1}) is False
    assert match_condition({"field": "missing", "eq": 1}, {"x": 1}) is False


def test_evaluation_is_pure():
    """纯函数：同样输入给同样输出，且不修改传入的字段字典。"""
    data = {"business_type": "热食/有油烟", "area_sqm": 500}
    snapshot = dict(data)

    first = evaluate_conditions(RESTAURANT, data)
    second = evaluate_conditions(RESTAURANT, data)

    assert first == second, (first, second)
    assert data == snapshot, data


if __name__ == "__main__":
    test_base_lists_match_scenario_config()
    test_no_rule_hit_returns_base_only()
    test_empty_fields_return_base_only()
    test_rule_hot_food_adds_oil_purifier()
    test_rule_area_threshold_boundary()
    test_rule_area_ignores_non_numeric_value()
    test_rule_raw_food_adds_cold_room()
    test_rule_signboard_adds_city_approval()
    test_rule_bank_appointment()
    test_rule_employees_threshold_boundary()
    test_restaurant_all_rules_combined()
    test_enterprise_all_rules_combined()
    test_notes_only_for_triggered_rules()
    test_duplicate_additions_are_deduped()
    test_produced_ids_are_defined_in_scenario()
    test_rule_references_existing_fields()
    test_match_operators()
    test_evaluation_is_pure()
    print("CONDITION ROUTING PASSED")
