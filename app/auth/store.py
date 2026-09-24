"""用户存储：内存实现与 JSON 文件实现（接口见 `app/storage/base.py`）。

只存 `User.to_dict()` 与**口令哈希**，不存明文口令。
落盘用原子替换（`app/storage/atomic.py`），生产换 PostgreSQL / MySQL
时按 `UserStore` 的五个方法实现即可。
"""
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import ROOT
from ..storage.atomic import read_json, write_json
from ..storage.base import UserStore
from .models import User

DEFAULT_USERS_FILE = "data/runtime/users.json"


def _record(user, password_hash: str) -> Dict[str, Any]:
    return {"user": user.to_dict(), "password_hash": password_hash}


class InMemoryUserStore(UserStore):
    """进程内用户表（测试 / 单进程演示用）。"""

    def __init__(self, items: Optional[Dict[str, Dict[str, Any]]] = None):
        self._items: Dict[str, Dict[str, Any]] = dict(items or {})

    def add(self, user, password_hash: str):
        if self.find_by_username(user.username) is not None:
            return None
        self._items[user.user_id] = _record(user, password_hash)
        return user

    def get(self, user_id: str) -> Optional[User]:
        item = self._items.get(user_id)
        return User.from_dict(item["user"]) if item else None

    def find_by_username(self, username: str) -> Optional[User]:
        for item in self._items.values():
            if item["user"].get("username") == username:
                return User.from_dict(item["user"])
        return None

    def password_hash_of(self, user_id: str) -> str:
        item = self._items.get(user_id)
        return str(item.get("password_hash", "")) if item else ""

    def list_users(self) -> List[User]:
        return [User.from_dict(item["user"]) for item in self._items.values()]


class JsonFileUserStore(InMemoryUserStore):
    """用户落盘到 JSON（`data/runtime/users.json`），重启后账号仍在。"""

    def __init__(self, path=None, root=None):
        base = Path(root) if root else ROOT
        self.path = Path(path) if path else base / DEFAULT_USERS_FILE
        raw = read_json(self.path, {}) or {}
        items: Dict[str, Dict[str, Any]] = {}
        for user_id, item in raw.items():
            if isinstance(item, dict) and "user" in item:
                items[str(user_id)] = item
        super().__init__(items)

    def _flush(self) -> None:
        write_json(self.path, self._items)

    def add(self, user, password_hash: str):
        created = super().add(user, password_hash)
        if created is not None:
            self._flush()
        return created
