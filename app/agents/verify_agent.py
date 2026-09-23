"""材料核验 Agent：形式校验 + 内容核验。

具体规则在 `app/materials/verify.py`（纯函数，便于单测），
本 Agent 是它在 Agent 层的门面，并负责按场景补齐所需上下文。
"""
from ..materials.verify import check_file, review
from .base import BaseAgent


class VerifyAgent(BaseAgent):
    name = "verify"

    def verify(self, materials):
        """受理前的材料清单预检（桩）：清单阶段还没有文件，恒通过。"""
        return {
            "status": "通过",
            "checked": len(materials),
            "missing": [],
            "model": self.model_for(),
        }

    def check_file(self, spec, filename, content: bytes) -> dict:
        """核验单张文件（形式 + 内容）。"""
        return check_file(spec, filename, content)

    def review(self, specs, files_map) -> dict:
        """按材料清单汇总核验结果，留档到办理单。"""
        return review(specs, files_map, model=self.model_for())
