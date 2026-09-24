"""材料核验 Agent：形式校验 + 内容核验。

具体规则与核验器在 `app/materials/verify.py`（便于单测）；本 Agent 是它在 Agent 层的门面，
负责按"子 Agent"角色解析出视觉模型名，并据此装配核验器（配了模型走视觉核验，
没配则用桩规则，见 `docs/09`）。
"""
from ..materials.verify import build_checker, check_file, review
from .base import BaseAgent


class VerifyAgent(BaseAgent):
    name = "verify"
    # 材料核验属于子 Agent 工作：走 MOMA_SUB_* 端点（未配置子端点时自动回退主端点）
    role = "sub"

    def __init__(self, moma, context):
        super().__init__(moma, context)
        self.checker = build_checker(moma, model=self.model_for(), role=self.role)

    def verify(self, materials):
        """受理前的材料清单预检（清单阶段还没有文件，恒通过）。

        一次性路径（CLI / 演示）走这里；带材料收集单的路径由 `review` 用真实文件核验。
        """
        return {
            "status": "通过",
            "checked": len(materials),
            "missing": [],
            "model": self.model_for(),
        }

    def check_file(self, spec, filename, content: bytes, slot: str = "") -> dict:
        """核验单张文件（形式 + 内容）。"""
        return check_file(spec, filename, content, slot=slot, checker=self.checker)

    def review(self, specs, files_map) -> dict:
        """按材料清单汇总核验结果，留档到办理单。"""
        return review(specs, files_map, model=self.model_for())
