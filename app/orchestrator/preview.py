"""条件判定实时预判：按**目前已知**的表单，预估要办哪些事、要交哪些材料。

用途：用户还在填表 / 对话的过程中，就把"大概要办什么、要交什么"提前告诉他，
而不是等采齐后一次性弹出来。

三条设计约束（都是为了让预判零风险）：

1. **只读**：不创建材料收集单、不动流程节点、不落库；
2. **无副作用**：条件判定是纯函数，可反复重算，改输入不会污染任何状态；
3. **不是最终结论**：正式清单仍以信息采齐后产出的材料收集单为准（见 `docs/09`），
   所以界面上要区分"预判"与"最终"。

因此它**不能**当作流程的首个节点——它依赖已采集的字段，字段没采时只有基础清单
（等于没判定）；它是挂在"接受输入"这一层的旁路计算。
"""
from typing import Any, Dict

from ..agents.condition_agent import evaluate_conditions
from ..materials.spec import material_names


def build_preview(scenario: Dict[str, Any], fields: Dict[str, Any]) -> Dict[str, Any]:
    """按当前字段预判事项与材料。

    `items` / `materials` 是 id 列表（结构化，与办理单一致）；
    `item_names` / `material_names` 是给界面显示的中文名（见 `docs/08` 文案规范）。
    """
    scenario = scenario or {}
    items, materials, notes = evaluate_conditions(scenario, fields or {})
    items_map = scenario.get("items") or {}
    return {
        "items": items,
        "item_names": [items_map.get(item_id, {}).get("name", item_id) for item_id in items],
        "materials": materials,
        "material_names": material_names(scenario, materials),
        "notes": notes,
    }
