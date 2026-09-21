"""咨询 Agent：解答办事流程与材料问题。"""
from .base import BaseAgent


class ConsultAgent(BaseAgent):
    name = "consult"

    def answer(self, question, scenario):
        model = self.model_for()
        items = [v["name"] + "（" + v["department"] + "）" for v in scenario["items"].values()]
        reply = "办理要点：" + "、".join(items) + "。"
        self.context.add_history("user", question)
        self.context.add_history("assistant", reply)
        return "[" + model + "] " + reply
