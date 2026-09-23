"""Agent 基类。"""


class BaseAgent:
    name = "base"
    # 模型角色：main = 主 Agent 模型；sub = 子 Agent 模型
    role = "main"

    def __init__(self, moma, context):
        self.moma = moma
        self.context = context

    def model_for(self):
        return self.moma.model_for(self.role, self.name)
