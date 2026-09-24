"""存储装配：`build_storage()` 是"换后端"的唯一切换点（见 `docs/12`）。

    STORAGE_BACKEND=memory   全部进程内（测试用）
    STORAGE_BACKEND=json     会话在内存、办理单 / 用户 / 单号落 JSON（默认，单机 Demo）
    STORAGE_BACKEND=sql      预留：实现 app/storage/base.py 的三个接口后注入
    STORAGE_BACKEND=redis    预留：同上

`sql` / `redis` 目前**只留接口不接实现**：调用 `build_storage("sql")` 会抛出
带说明的 `NotImplementedError`，提示需要实现哪个接口；真实接入时把实现
通过关键字参数注入即可，业务代码零改动：

    storage = build_storage("sql", cases=SqlCaseRepo(dsn), users=SqlUserStore(dsn))
"""
import atexit
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from ..auth.store import InMemoryUserStore, JsonFileUserStore
from ..config import DEFAULT_STORAGE_BACKEND, ROOT
from ..materials.store import MaterialStore
from .base import CaseRepo, SessionRepo, UserStore
from .ids import IdAllocator, InMemoryIdAllocator, JsonFileIdAllocator
from .repo import InMemoryRepo, JsonFileRepo
from .sessions import InMemorySessionRepo

KNOWN_BACKENDS = ("memory", "json", "sql", "redis")

# sql / redis 需要哪些组件才能跑起来（报错时按这个清单提示）
_REQUIRED_COMPONENTS = {
    "cases": "app.storage.base.CaseRepo",
    "sessions": "app.storage.base.SessionRepo",
    "users": "app.storage.base.UserStore",
    "ids": "app.storage.ids.IdAllocator",
    "materials": "app.materials.store.MaterialStore（对象存储）",
}


@dataclass
class Storage:
    """一次装配好的存储组合；上层只依赖它，不感知具体后端。"""

    cases: CaseRepo
    sessions: SessionRepo
    users: UserStore
    ids: IdAllocator
    materials: MaterialStore
    backend: str = "memory"

    def describe(self) -> dict:
        """对外可观测信息（不含任何密钥）。"""
        return {
            "backend": self.backend,
            "cases": type(self.cases).__name__,
            "sessions": type(self.sessions).__name__,
            "users": type(self.users).__name__,
            "ids": type(self.ids).__name__,
        }


def build_storage(backend: Optional[str] = None, root=None, **overrides: Any) -> Storage:
    """按后端名装配存储；`*_overrides` 可注入任一组件实现（sql / redis 必经此路）。

    可注入的键：`cases` / `sessions` / `users` / `ids` / `materials`。
    """
    name = (backend or os.environ.get("STORAGE_BACKEND") or DEFAULT_STORAGE_BACKEND).strip().lower()
    if name not in KNOWN_BACKENDS:
        raise ValueError("未知的 STORAGE_BACKEND：" + name + "（可选：" + " / ".join(KNOWN_BACKENDS) + "）")

    if name in ("sql", "redis"):
        return _build_external(name, **overrides)

    base = Path(root) if root else ROOT
    runtime = base / "data" / "runtime"

    if name == "memory":
        workdir = Path(tempfile.mkdtemp(prefix="ost-memory-"))
        atexit.register(lambda: shutil.rmtree(workdir, ignore_errors=True))
        ids: IdAllocator = overrides.get("ids") or InMemoryIdAllocator()
        defaults = {
            "cases": overrides.get("cases") or InMemoryRepo(),
            "sessions": overrides.get("sessions") or InMemorySessionRepo(),
            "users": overrides.get("users") or InMemoryUserStore(),
            "ids": ids,
            "materials": overrides.get("materials") or MaterialStore(
                intakes_file=workdir / "intakes.json",
                materials_dir=workdir / "materials",
                ids=ids,
            ),
        }
    else:  # json
        ids = overrides.get("ids") or JsonFileIdAllocator(runtime / "ids.json")
        defaults = {
            "cases": overrides.get("cases") or JsonFileRepo(runtime / "cases.json"),
            "sessions": overrides.get("sessions") or InMemorySessionRepo(),
            "users": overrides.get("users") or JsonFileUserStore(path=runtime / "users.json"),
            "ids": ids,
            "materials": overrides.get("materials") or MaterialStore(
                intakes_file=runtime / "intakes.json",
                materials_dir=runtime / "materials",
                ids=ids,
            ),
        }

    return Storage(backend=name, **defaults)


def _build_external(name: str, **overrides: Any) -> Storage:
    """sql / redis：**只留接口**，要求调用方注入实现。"""
    missing = [key for key in _REQUIRED_COMPONENTS if overrides.get(key) is None]
    if missing:
        wanted = "、".join(key + "（" + _REQUIRED_COMPONENTS[key] + "）" for key in missing)
        raise NotImplementedError(
            "STORAGE_BACKEND=" + name + " 尚未内置实现，请先实现这些存储接口并注入："
            + wanted + "。接口定义见 app/storage/base.py，接入步骤见 docs/12。"
        )
    return Storage(
        backend=name,
        cases=overrides["cases"],
        sessions=overrides["sessions"],
        users=overrides["users"],
        ids=overrides["ids"],
        materials=overrides["materials"],
    )
