"""单号分配器：把"进程内自增"收口成可替换接口（见 `docs/10` 第 4 条）。

此前办理单（`YJS0001`）、材料收集单（`CL0001`）、会话（`s000001`）都由
各自对象上的 `self._seq += 1` 生成：**多进程会重号**，落盘后还会互相覆盖。

现在统一走 `IdAllocator`：

    InMemoryIdAllocator  进程内计数器（默认，单进程 Demo / 测试）
    JsonFileIdAllocator  计数器落盘（多进程共享一份文件时至少不重号）
    生产                 数据库序列（`nextval`）或带实例号的分布式发号器

配套两个能力：
- `reserve(key, n)`：启动时对齐历史数据里的最大号，避免重启后重号；
- `INSTANCE_ID`：多实例部署时给单号加实例号，跨实例也不会撞号。
"""
import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from threading import Lock
from typing import Dict

from .atomic import read_json, write_json

_TRAILING_DIGITS = re.compile(r"(\d+)$")


def instance_prefix() -> str:
    """实例号前缀（`INSTANCE_ID` 环境变量）；未配置时为空串，行为与单实例一致。"""
    return (os.environ.get("INSTANCE_ID") or "").strip()


def sequence_of(value: str) -> int:
    """从形如 `YJS0001` / `CLi10007` 的单号里取出末尾数字；取不出返回 0。

    末尾数字才是序号，所以加不加实例号都能正确解析（用于 `reserve` 对齐历史数据）。
    """
    found = _TRAILING_DIGITS.search(str(value or ""))
    return int(found.group(1)) if found else 0


class IdAllocator(ABC):
    """发号接口：`key + [实例号] + 递增数字`（如 `YJS0001` / `CLi10007` / `s000001`）。"""

    def __init__(self, prefix: str = None):
        self.prefix = instance_prefix() if prefix is None else prefix

    def format(self, key: str, value: int, width: int = 4) -> str:
        return key + self.prefix + str(int(value)).zfill(int(width))

    @abstractmethod
    def next(self, key: str, width: int = 4) -> str:
        """取下一个号。"""

    @abstractmethod
    def reserve(self, key: str, value: int) -> None:
        """把某个序列的下界抬到 `value`（对齐历史最大号，防止重号）。"""

    @abstractmethod
    def peek(self, key: str) -> int:
        """当前已发出的最大值（只读，测试 / 运维用）。"""


class InMemoryIdAllocator(IdAllocator):
    """进程内计数器；配合 `reserve` 也能避免单进程重启后重号。"""

    def __init__(self, prefix: str = None, counters: Dict[str, int] = None):
        super().__init__(prefix)
        self._counters: Dict[str, int] = dict(counters or {})
        self._lock = Lock()

    def next(self, key: str, width: int = 4) -> str:
        with self._lock:
            value = self._counters.get(key, 0) + 1
            self._counters[key] = value
        return self.format(key, value, width)

    def reserve(self, key: str, value: int) -> None:
        with self._lock:
            self._counters[key] = max(self._counters.get(key, 0), int(value or 0))

    def peek(self, key: str) -> int:
        return self._counters.get(key, 0)


class JsonFileIdAllocator(IdAllocator):
    """计数器落盘到 JSON：多进程重启后不重号。

    并发安全仍依赖"单实例写"或文件锁——真正多进程并发请换数据库序列（见 `docs/12`）。
    """

    def __init__(self, path, prefix: str = None):
        super().__init__(prefix)
        self.path = Path(path)
        self._counters: Dict[str, int] = {}
        raw = read_json(self.path, {}) or {}
        for key, value in raw.items():
            try:
                self._counters[str(key)] = int(value)
            except (TypeError, ValueError):
                continue
        self._lock = Lock()

    def _flush(self) -> None:
        write_json(self.path, self._counters)

    def next(self, key: str, width: int = 4) -> str:
        with self._lock:
            value = self._counters.get(key, 0) + 1
            self._counters[key] = value
            self._flush()
        return self.format(key, value, width)

    def reserve(self, key: str, value: int) -> None:
        with self._lock:
            current = self._counters.get(key, 0)
            new_value = max(current, int(value or 0))
            if new_value != current:
                self._counters[key] = new_value
                self._flush()

    def peek(self, key: str) -> int:
        return self._counters.get(key, 0)
