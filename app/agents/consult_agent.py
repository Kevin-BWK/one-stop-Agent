"""咨询 Agent：解答办事流程与材料问题。

优先走 MoMA（真实模式）；未配置或调用失败时回退到本地办理要点，
保证零依赖 Demo 与离线单测仍然可用。
"""
from .base import BaseAgent


class ConsultAgent(BaseAgent):
    name = "consult"

    def answer(self, question, scenario):
        model = self.model_for()
        local = self._local_reply(scenario)
        messages = self._messages(question, scenario)
        reply = self.moma.complete(
            model,
            messages,
            fallback="[" + model + "] " + local,
            context=self.context,
        )
        self.context.add_history("user", question)
        self.context.add_history("assistant", reply)
        return reply

    @staticmethod
    def _item_text(scenario):
        return "、".join(
            v["name"] + "（" + v["department"] + "）" for v in scenario["items"].values()
        )

    def _local_reply(self, scenario):
        return "办理要点：" + self._item_text(scenario) + "。"

    def _messages(self, question, scenario):
        materials = "、".join(scenario.get("base_materials", []))
        system = (
            "你是“一件事·一次办”政务办事咨询助手，回答要简洁、准确、口语化，"
            "只围绕当前办理事项作答。"
            "当前事项：" + scenario.get("name", "") + "。"
            "办理事项：" + self._item_text(scenario) + "。"
            "基础材料：" + (materials or "以办事指南为准") + "。"
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": question},
        ]