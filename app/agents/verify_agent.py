"""材料核验 Agent：检查材料是否齐全、格式是否合规（桩）。"""
from .base import BaseAgent


class VerifyAgent(BaseAgent):
    name = "verify"

    def verify(self, materials):
        model = self.model_for()
        # 桩：真实实现调用多模态模型识别证件、核对材料
        report = {
            "status": "通过",
            "checked": len(materials),
            "missing": [],
            "model": model,
        }
        return report
