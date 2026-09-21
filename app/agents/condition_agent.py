"""条件判定 Agent：根据表单内容判定事项与材料（智能路由核心）。"""
from .base import BaseAgent


class ConditionAgent(BaseAgent):
    name = "condition"

    def evaluate(self, scenario, form):
        items = list(scenario["base_items"])
        materials = list(scenario["base_materials"])
        notes = []
        for rule in scenario["condition_rules"]:
            if self._match(rule["if"], form.fields):
                items += rule.get("add_items", [])
                materials += rule.get("add_materials", [])
                note = rule.get("note", "")
                if note:
                    notes.append(note)
        items = list(dict.fromkeys(items))
        materials = list(dict.fromkeys(materials))
        return items, materials, notes

    def _match(self, cond, fields):
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
