"""条件判定 Agent：根据表单内容判定事项与材料（智能路由核心）。

判定逻辑本身是**纯函数**（`evaluate_conditions` / `match_condition`），不依赖
MoMA、不碰存储、可反复调用。因此它有两个用途：

1. 信息采齐后的**正式判定** → 产出材料清单（`ConditionAgent.evaluate`）；
2. 填写过程中的**实时预判** → 按当前已知字段预估要办什么事、交什么材料
   （见 `app/orchestrator/preview.py`）。

规则矩阵测试见 `tests/test_condition_routing.py`。
"""
from typing import Any, Dict, List, Tuple

from .base import BaseAgent


def match_condition(cond: Dict[str, Any], fields: Dict[str, Any]) -> bool:
    """判断单条条件是否命中。

    支持的比较方式：`eq`（等于）/ `in`（在集合内）/ `gte`（大于等于）/ `bool`（布尔等于）。

    **字段尚未采集时一律不命中**——这是预判能安全作用于"填了一半"的表单的原因：
    没有输入就不会凭空断言，只会给出当前信息下成立的结论。
    """
    field = cond.get("field")
    if field not in fields:
        return False
    value = fields[field]
    if "eq" in cond:
        return value == cond["eq"]
    if "in" in cond:
        return value in cond["in"]
    if "gte" in cond:
        return isinstance(value, (int, float)) and value >= cond["gte"]
    if "bool" in cond:
        return bool(value) == bool(cond["bool"])
    return False


def evaluate_conditions(scenario: Dict[str, Any], fields: Dict[str, Any]) -> Tuple[List[str], List[str], List[str]]:
    """按场景的条件规则算出需要办的事项与材料（纯函数）。

    返回 `(items, materials, notes)`：前两者是**去重后保持顺序**的 id 列表，
    `notes` 是命中规则的说明文案（按 `condition_rules` 的书写顺序）。
    """
    items = list(scenario.get("base_items") or [])
    materials = list(scenario.get("base_materials") or [])
    notes: List[str] = []
    for rule in scenario.get("condition_rules") or []:
        if not match_condition(rule.get("if") or {}, fields or {}):
            continue
        items += rule.get("add_items") or []
        materials += rule.get("add_materials") or []
        note = rule.get("note", "")
        if note:
            notes.append(note)
    return list(dict.fromkeys(items)), list(dict.fromkeys(materials)), notes


class ConditionAgent(BaseAgent):
    name = "condition"

    def evaluate(self, scenario, form):
        """正式判定：表单 -> 事项 / 材料 / 判定说明。"""
        return evaluate_conditions(scenario, form.fields)
