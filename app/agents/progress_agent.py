"""进度跟踪 Agent：把办理流程节点与并联事项状态渲染成"进度看板"。"""
from ..orchestrator.flow import ICON, STATUS_DONE, STATUS_TODO
from .base import BaseAgent


class ProgressAgent(BaseAgent):
    name = "progress"

    def board(self, flow, item_status, items_map):
        """渲染完整进度看板：办理流程节点（打勾）+ 并联事项状态。"""
        flow = flow or []
        lines = ["【办理流程】"]
        done = 0
        for node in flow:
            status = node.get("status", STATUS_TODO)
            if status == STATUS_DONE:
                done += 1
            line = ICON.get(status, ICON[STATUS_TODO]) + " " + node.get("name", node.get("key", ""))
            line += "：" + status
            detail = node.get("detail") or ""
            if detail:
                line += "（" + detail + "）"
            lines.append(line)
        if flow:
            lines.append("流程进度：" + str(done) + "/" + str(len(flow)))

        if item_status:
            lines.append("【并联办理】")
            for item_id, status in item_status.items():
                name = items_map.get(item_id, {}).get("name", item_id)
                lines.append("· " + name + "：" + status)
        return "\n".join(lines)

    def query(self, item_status, items_map):
        """仅渲染并联事项状态（兼容旧接口）。"""
        return "\n".join(
            items_map.get(item_id, {}).get("name", item_id) + "：" + status
            for item_id, status in item_status.items()
        )
