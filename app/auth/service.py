"""鉴权服务：注册 / 登录 / 令牌校验 / 材料文件签名链接。

对外只暴露"用户"与"令牌"，不关心底层是内存、JSON 还是数据库
（用户存储接口见 `app/storage/base.py::UserStore`）。

安全约定：
- 口令只落哈希（`hash_password`），**永不落明文、永不回显**；
- 令牌自包含 + HMAC 签名，服务端无状态校验（多进程可直接用）；
- 材料文件链接是**绑定到具体文件**的短时签名（见 `issue_file_token`），
  这样图片能直接作为 `<image src>` 加载，不必把令牌塞进请求头。
"""
import time
import uuid
from typing import Optional

from ..config import (DEFAULT_FILE_URL_TTL, DEFAULT_TOKEN_TTL, auth_secret,
                      env_flag, env_int)
from .models import ROLE_APPLICANT, ROLES, User, demo_user
from .security import (TOKEN_TYPE_FILE, TOKEN_TYPE_SESSION, Signer, hash_password,
                       verify_password)
from .store import InMemoryUserStore


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class AuthService:
    """账号与令牌的统一入口。"""

    def __init__(self, store=None, secret=None, token_ttl=None, file_ttl=None,
                 required=None):
        self.store = store if store is not None else InMemoryUserStore()
        self.signer = Signer(auth_secret() if secret is None else secret)
        self.token_ttl = int(token_ttl if token_ttl is not None
                             else env_int("AUTH_TOKEN_TTL", DEFAULT_TOKEN_TTL))
        self.file_ttl = int(file_ttl if file_ttl is not None
                            else env_int("AUTH_FILE_URL_TTL", DEFAULT_FILE_URL_TTL))
        self._required = required
        self._demo = demo_user()

    # ---------- 开关 ----------

    @property
    def required(self) -> bool:
        """是否强制登录（`AUTH_REQUIRED=1`）。

        关闭时未携带令牌的请求按"演示用户"处理，保证单用户 Demo 与既有
        端到端流程不受影响；上线前必须置为开启（见 `docs/10` 第 5 条）。
        """
        if self._required is not None:
            return bool(self._required)
        return env_flag("AUTH_REQUIRED")

    def demo_user(self) -> User:
        return self._demo

    # ---------- 账号 ----------

    def register(self, username: str, password: str, display_name: str = "",
                 role: str = ROLE_APPLICANT) -> User:
        username = (username or "").strip()
        if not username:
            raise ValueError("用户名不能为空")
        if len(password or "") < 6:
            raise ValueError("密码至少 6 位")
        if self.store.find_by_username(username) is not None:
            raise ValueError("用户名已被占用")
        user = User(
            user_id="u_" + uuid.uuid4().hex[:12],
            username=username,
            display_name=(display_name or username).strip(),
            role=role if role in ROLES else ROLE_APPLICANT,
            created_at=_now(),
        )
        if self.store.add(user, hash_password(password)) is None:
            raise ValueError("用户名已被占用")
        return user

    def login(self, username: str, password: str) -> User:
        user = self.store.find_by_username((username or "").strip())
        stored = self.store.password_hash_of(user.user_id) if user else ""
        if user is None or not verify_password(password, stored):
            # 同一句提示，不区分"用户不存在 / 密码错"，避免账号枚举
            raise KeyError("用户名或密码不正确")
        return user

    def get(self, user_id: str) -> Optional[User]:
        return self.store.get(user_id)

    # ---------- 令牌 ----------

    def issue_token(self, user: User) -> str:
        now = int(time.time())
        return self.signer.sign({
            "sub": user.user_id,
            "typ": TOKEN_TYPE_SESSION,
            "iat": now,
            "exp": now + self.token_ttl,
        })

    def resolve(self, token: str) -> Optional[User]:
        """校验登录令牌并取回用户；签名错 / 过期 / 用户已删都返回 None。"""
        claims = self.signer.verify(token)
        if not claims or claims.get("typ") != TOKEN_TYPE_SESSION:
            return None
        return self.store.get(str(claims.get("sub") or ""))

    def token_ttl_seconds(self) -> int:
        return self.token_ttl

    # ---------- 材料文件的签名链接 ----------

    def issue_file_token(self, owner_id: str, intake_id: str, material_id: str,
                         file_id: str) -> str:
        """给某张材料文件签一个短时链接（绑定 owner + 文件，不能挪作他用）。"""
        now = int(time.time())
        return self.signer.sign({
            "sub": str(owner_id or ""),
            "typ": TOKEN_TYPE_FILE,
            "i": intake_id,
            "m": material_id,
            "f": file_id,
            "iat": now,
            "exp": now + self.file_ttl,
        })

    def verify_file_token(self, token: str, intake_id: str, material_id: str,
                          file_id: str) -> Optional[str]:
        """校验文件签名链接；通过返回文件归属的 `owner_id`，否则 None。"""
        claims = self.signer.verify(token)
        if not claims or claims.get("typ") != TOKEN_TYPE_FILE:
            return None
        if (claims.get("i"), claims.get("m"), claims.get("f")) != (intake_id, material_id, file_id):
            return None
        return str(claims.get("sub") or "")
