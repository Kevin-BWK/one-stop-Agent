"""编排事件：供前端等调用方实时订阅办理过程。

`MainAgent.run(utterance, answers, on_event=...)` / `query(case_id, on_event=...)`
在关键节点触发事件；**不传 on_event 时行为与以往完全一致**（只返回 trace 与 case）。

Web 层（FastAPI）只需把 `Event.to_dict()` 写入 SSE 流的 `data`，编排逻辑无需再改。
事件契约见 docs/07-前端交互设计.md。
"""
from dataclasses import dataclass, field
from typing import Any, Dict

MESSAGE = "message"             # 面向用户的文本（咨询应答 / 采集表单 / 核验结果 / 部门办结 / 进度看板）
FLOW_NODE = "flow_node"         # 流程节点状态变化（打勾）
CASE_CREATED = "case_created"   # 并联提交，生成办理单
ITEM_DONE = "item_done"         # 部门子 Agent 办结某个并联事项
FINISHED = "finished"           # 全流程结束
ERROR = "error"                 # 编排异常


@dataclass
class Event:
    """一次编排事件：type 为类型，data 为负载（字段定义见 docs/07）。"""
    type: str
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转为可 JSON 序列化的字典（Web 层写入 SSE data 用）。"""
        return {"type": self.type, "data": self.data}
