"""存储抽象：把"状态存哪"和"业务怎么用"解耦（见 `docs/12`）。

多用户上线前的硬门槛是"单进程 + 内存状态"：会话 / 材料收集单 / 办理单 / 单号
都挂在进程内存里，`uvicorn --workers 4` 时互相找不到、并发还会重号（见 `docs/10` 第 4 条）。

这里先用**纯接口**把边界划出来：上层的 `AgentService` / `MainAgent` / `MaterialService`
只依赖这些接口，不关心背后是内存、JSON 文件还是 Redis / PostgreSQL。

    CaseRepo    办理单    -> 现在 JsonFileRepo / InMemoryRepo；生产 PostgreSQL / MySQL
    SessionRepo 多轮会话  -> 现在 InMemorySessionRepo；生产 Redis（短期）
    UserStore   用户账号  -> 现在 JsonFileUserStore / InMemoryUserStore；生产 PostgreSQL / MySQL
    IdAllocator 单号分配  -> 现在进程内计数器；生产数据库序列或带实例号的发号器

接入真实后端时**只需实现同名字法**，业务代码零改动；`app/storage/factory.py`
的 `build_storage()` 是唯一切换点（`STORAGE_BACKEND` 环境变量）。
"""
from abc import ABC, abstractmethod
from typing import Any, List, Optional


class CaseRepo(ABC):
    """办理单存储。

    SQL 参考实现（PostgreSQL / MySQL）：

        CREATE TABLE cases (
            case_id     VARCHAR(32) PRIMARY KEY,
            owner_id    VARCHAR(64) NOT NULL,
            scenario_id VARCHAR(64) NOT NULL,
            payload     JSONB NOT NULL,      -- CaseRecord.to_dict()
            created_at  TIMESTAMP,
            updated_at  TIMESTAMP
        );
        CREATE INDEX idx_cases_owner ON cases(owner_id);

    `list_cases(owner_id)` 对应 `WHERE owner_id = :owner_id`；
    不传 `owner_id` 时返回全部（供单号序列对齐等内部用途）。
    """

    @abstractmethod
    def save_case(self, case) -> None:
        """新增或覆盖一份办理单。"""

    @abstractmethod
    def get_case(self, case_id: str) -> Optional[Any]:
        """按单号取办理单；不存在返回 None。"""

    @abstractmethod
    def list_cases(self, owner_id: Optional[str] = None) -> List[Any]:
        """列出办理单；`owner_id` 非空时只返回该用户的。"""


class SessionRepo(ABC):
    """多轮会话存储。

    Redis 参考实现：key `session:{session_id}` -> `SessionRecord.to_dict()`，
    TTL 取会话有效期；进程内实现直接存对象（同进程零拷贝）。

    注意：`SessionRecord` 含 Agent 实例与运行时上下文，落 Redis 时需要
    "只序列化可持久化字段、读回时重建 Agent"——接口保持 put/get 即可，
    重建逻辑放在存储实现里（见 `docs/12` 的迁移路径）。
    """

    @abstractmethod
    def put(self, session_id: str, record: Any) -> None:
        """写入 / 覆盖一个会话。"""

    @abstractmethod
    def get(self, session_id: str) -> Optional[Any]:
        """取会话；不存在返回 None。"""

    @abstractmethod
    def drop(self, session_id: str) -> None:
        """删除会话（登出 / 过期回收）。"""

    @abstractmethod
    def list_ids(self) -> List[str]:
        """列出会话 id（运维 / 测试用）。"""


class UserStore(ABC):
    """用户账号存储。

    SQL 参考实现（PostgreSQL / MySQL）：

        CREATE TABLE users (
            user_id       VARCHAR(64) PRIMARY KEY,
            username      VARCHAR(64) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            display_name  VARCHAR(64),
            role          VARCHAR(32) NOT NULL,
            created_at    TIMESTAMP
        );

    口令只存 `hash_password()` 的结果，**永不落明文**。
    """

    @abstractmethod
    def add(self, user, password_hash: str):
        """新增用户；用户名重复由实现方决定行为（当前实现返回 None）。"""

    @abstractmethod
    def get(self, user_id: str) -> Optional[Any]:
        """按 id 取用户。"""

    @abstractmethod
    def find_by_username(self, username: str) -> Optional[Any]:
        """按用户名取用户（登录用）。"""

    @abstractmethod
    def password_hash_of(self, user_id: str) -> str:
        """取某用户的口令哈希；不存在返回空串。"""

    @abstractmethod
    def list_users(self) -> List[Any]:
        """列出全部用户（后台 / 测试用）。"""
