"""Agent 基类。"""


class BaseAgent:
    name = "base"

    def __init__(self, moma, context):
        self.moma = moma
        self.context = context

    def model_for(self):
        return self.moma.dispatch(self.name)
