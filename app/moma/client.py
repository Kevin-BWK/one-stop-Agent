"""MoMA 平台客户端（桩实现）。

对接真实 MoMA 后，替换 chat / dispatch 内部逻辑即可，对外接口保持不变。
封装 MoMA 三大能力：多模型调度、智能路由、上下文管理。
"""
from typing import Any, Dict, List


class MoMAClient:
    MODEL_POOL = {
        "strong": "deepseek-r1",
        "light": "qwen-turbo",
        "vision": "qwen-vl",
        "rule": "rule-engine",
    }
    TASK_MODEL = {
        "consult": "strong",
        "collect": "light",
        "condition": "rule",
        "verify": "vision",
        "progress": "rule",
        "default": "light",
    }

    def dispatch(self, task_type: str) -> str:
        """多模型调度：根据任务类型选择模型。"""
        key = self.TASK_MODEL.get(task_type, "default")
        return self.MODEL_POOL[key]

    def chat(self, model: str, messages: List[Dict[str, str]], context: Any = None) -> str:
        """调用模型（桩）：真实实现改为 MoMA API 请求。"""
        last = messages[-1]["content"] if messages else ""
        return "[" + model + "] " + last

    def route(self, intent: str) -> str:
        """智能路由：返回应处理的 Agent 名称。"""
        return intent
