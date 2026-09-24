"""多轮会话存储的内存实现（Redis 实现的占位见 `app/storage/base.py`）。

`InMemorySessionRepo` 额外实现了 `__getitem__ / __contains__ / __len__`，
让调用方仍能像用 dict 一样访问（`sessions[sid]`），从而**零成本替换**
原有的 `self.sessions = {}`，不改上层代码。
"""
from typing import Any, Dict, List, Optional

from .base import SessionRepo


class InMemorySessionRepo(SessionRepo):
    """进程内会话表。多进程部署时换成 Redis（见 `docs/12`）。"""

    def __init__(self, items: Dict[str, Any] = None):
        self._items: Dict[str, Any] = dict(items or {})

    def put(self, session_id: str, record: Any) -> None:
        self._items[session_id] = record

    def get(self, session_id: str) -> Optional[Any]:
        return self._items.get(session_id)

    def drop(self, session_id: str) -> None:
        self._items.pop(session_id, None)

    def list_ids(self) -> List[str]:
        return list(self._items.keys())

    # --- 兼容 dict 用法（历史代码 / 测试直接下标取会话） ---
    def __getitem__(self, session_id: str):
        return self._items[session_id]

    def __contains__(self, session_id: str) -> bool:
        return session_id in self._items

    def __len__(self) -> int:
        return len(self._items)
