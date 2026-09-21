"""办理流程节点与进度台账。

本 Agent 代替群众走完整套办理流程，因此"办理进度"就是这套流程的节点进度：
"意图识别 -> 事项咨询 -> 信息采集 -> 条件判定 -> 材料核验 -> 并联提交 -> 各部门事项 -> 进度跟踪"，
每个节点在对应 Agent 阶段完成时立即"打勾"，状态依次为 待办 -> 进行中 -> 已完成。

其中"各部门事项"节点为动态节点：并联提交后按场景事项清单动态加入，
由对应部门子 Agent 办理完成后回调主 Agent 打勾。

框架节点由编排框架统一定义，两个业务场景共用；新增场景无需改动此处。
"""
import time

STATUS_TODO = "待办"
STATUS_DOING = "进行中"
STATUS_DONE = "已完成"

ICON = {STATUS_TODO: "[ ]", STATUS_DOING: "[→]", STATUS_DONE: "[√]"}
INLINE_ICON = {STATUS_TODO: "○", STATUS_DOING: "▶", STATUS_DONE: "√"}

# 标准办理流程节点：key -> 展示名称
FLOW_NODES = [
    ("intent", "意图识别"),
    ("consult", "事项咨询"),
    ("collect", "信息采集"),
    ("condition", "条件判定"),
    ("verify", "材料核验"),
    ("submit", "并联提交"),
    ("track", "进度跟踪"),
]


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class FlowProgress:
    """办理流程台账：记录各流程节点状态的推进过程，可快照、可渲染。"""

    def __init__(self, nodes=None):
        nodes = list(nodes or FLOW_NODES)
        self._order = [key for key, _ in nodes]
        self._names = {key: name for key, name in nodes}
        self._status = {key: STATUS_TODO for key in self._order}
        self._detail = {}
        self._updated = {}

    def add_node(self, key: str, name: str, before: str = None) -> "FlowProgress":
        """动态追加流程节点（如并联办理的各部门事项），可插入到指定节点之前。"""
        if key in self._status:
            return self
        self._names[key] = name
        if before in self._order:
            self._order.insert(self._order.index(before), key)
        else:
            self._order.append(key)
        self._status[key] = STATUS_TODO
        return self

    def start(self, key: str) -> "FlowProgress":
        """开始处理某节点（待办 -> 进行中）。"""
        self._status[key] = STATUS_DOING
        self._updated[key] = now()
        return self

    def complete(self, key: str, detail: str = "") -> "FlowProgress":
        """节点办理完成，打勾（进行中 -> 已完成）。"""
        self._status[key] = STATUS_DONE
        self._detail[key] = detail
        self._updated[key] = now()
        return self

    def status(self, key: str) -> str:
        return self._status.get(key, STATUS_TODO)

    def is_done(self, key: str) -> bool:
        return self.status(key) == STATUS_DONE

    def current(self):
        """当前正在办理（或下一个待办）的节点 key。"""
        for key in self._order:
            if self._status[key] != STATUS_DONE:
                return key
        return None

    def done_count(self) -> int:
        return sum(1 for key in self._order if self._status[key] == STATUS_DONE)

    def total(self) -> int:
        return len(self._order)

    def node(self, key: str):
        """单个节点的快照。"""
        return {
            "key": key,
            "name": self._names.get(key, key),
            "status": self._status.get(key, STATUS_TODO),
            "detail": self._detail.get(key, ""),
            "updated_at": self._updated.get(key, ""),
        }

    def snapshot(self):
        """导出为可持久化的节点列表。"""
        return [self.node(key) for key in self._order]

    def render_inline(self) -> str:
        """单行进度条，用于编排过程中逐步展示打勾效果。"""
        marks = " ".join(INLINE_ICON[self._status[key]] + self._names[key] for key in self._order)
        return "办理进度 " + str(self.done_count()) + "/" + str(self.total()) + " ｜ " + marks
