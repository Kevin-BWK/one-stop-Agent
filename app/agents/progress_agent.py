"""进度跟踪 Agent：查询并联办理进度。"""
from .base import BaseAgent


class ProgressAgent(BaseAgent):
    name = "progress"

    def query(self, item_status, items_map):
        lines = []
        for item_id, status in item_status.items():
            name = items_map.get(item_id, {}).get("name", item_id)
            lines.append(name + "：" + status)
        return "\n".join(lines)
