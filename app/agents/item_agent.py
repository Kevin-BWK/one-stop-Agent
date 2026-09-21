"""部门事项办理子 Agent：办理单个并联事项，完成后把结果回调上报给主 Agent。

真实实现中，这里调用对应部门（市场监管 / 税务 / 消防 / 城管 / 卫健…）的
政务系统接口或工具；桩实现直接返回"已办结"，用于驱动主 Agent 更新流程节点。
"""
from .base import BaseAgent


class ItemAgent(BaseAgent):
    name = "item"

    def process(self, item_id, item_meta, on_done=None):
        """办理一个并联事项；完成后通过 on_done 自动上报主 Agent。"""
        result = {
            "item_id": item_id,
            "name": item_meta.get("name", item_id),
            "department": item_meta.get("department", ""),
            "status": "已办结",
            "output": item_meta.get("output", ""),
            "model": self.model_for(),
        }
        if on_done is not None:
            on_done(result)
        return result
