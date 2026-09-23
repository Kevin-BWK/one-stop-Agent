"""部门事项办理子 Agent：办理单个并联事项，完成后把结果回调上报给主 Agent。

真实实现中，这里调用对应部门（市场监管 / 税务 / 消防 / 城管 / 卫健…）的
政务系统接口或工具；桩实现直接返回"已办结"，用于驱动主 Agent 更新流程节点。

该 Agent 使用**子 Agent 角色**（``MOMA_SUB_*``）的模型：真实模式下由子模型
生成一句办结回执；未配置或调用失败时回退到本地文案，保证离线可运行。
"""
from .base import BaseAgent


class ItemAgent(BaseAgent):
    name = "item"
    role = "sub"

    def process(self, item_id, item_meta, on_done=None):
        """办理一个并联事项；完成后通过 on_done 自动上报主 Agent。"""
        model = self.model_for()
        name = item_meta.get("name", item_id)
        department = item_meta.get("department", "")
        output = item_meta.get("output", "")
        fallback = "已办结"
        note = self.moma.complete(
            model,
            self._messages(department, name, output),
            fallback=fallback,
            context=self.context,
            role=self.role,
        )
        result = {
            "item_id": item_id,
            "name": name,
            "department": department,
            "status": "已办结",
            "output": output,
            "model": model,
            "note": note,
        }
        if on_done is not None:
            on_done(result)
        return result

    @staticmethod
    def _messages(department, name, output):
        system = "你是政务并联办理中的部门子 Agent，用一句话给出办结回执，简洁、正式。"
        user = (
            "部门：" + (department or "政务部门")
            + "；事项：" + name
            + "；出件：" + (output or "无")
            + "。请给出办结回执。"
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
