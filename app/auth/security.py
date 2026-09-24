"""口令哈希与令牌签名：零依赖（仅用 stdlib 的 hashlib / hmac / secrets / base64）。

设计要点：

1. **口令不落明文**：`hash_password` 用 PBKDF2-HMAC-SHA256（随机盐 + 迭代），
   存成 `pbkdf2_sha256$轮数$盐$散列`；校验用 `hmac.compare_digest` 防时序侧信道。
2. **令牌自包含**：签发出来的是 `payload.signature`（两段 base64url），
   签名用 HMAC-SHA256，claims 里带 `sub` / `exp` / `typ`。
   服务端**无需存储**即可校验 —— 天然适配"会话进 Redis、服务多进程"的部署；
   若要支持"主动登出 / 吊销"，把已签发令牌的 `jti` 记入黑名单即可（见 `docs/12`）。
3. 两类令牌共用同一签名器，靠 `typ` 区分：
   - `typ="session"`：登录令牌，代表"我是某个用户"；
   - `typ="file"`：材料文件专用签名链接，**绑定到具体文件**（图片要直接作为
     `<image src>` 使用，没法自定义请求头，只能走查询串）。
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any, Dict, Optional

PBKDF2_ALGORITHM = "pbkdf2_sha256"
PBKDF2_ROUNDS = 120_000

TOKEN_TYPE_SESSION = "session"
TOKEN_TYPE_FILE = "file"


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def hash_password(password: str, rounds: int = PBKDF2_ROUNDS, salt: str = "") -> str:
    """把明文口令哈希成可入库的字符串（同一口令每次结果不同，因为盐随机）。"""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"),
                                 salt.encode("utf-8"), int(rounds))
    return "$".join([PBKDF2_ALGORITHM, str(rounds), salt, digest.hex()])


def verify_password(password: str, stored: str) -> bool:
    """校验口令；`stored` 非法时返回 False（不抛异常，避免登录接口 500）。"""
    try:
        algorithm, rounds, salt, digest = str(stored or "").split("$")
    except ValueError:
        return False
    if algorithm != PBKDF2_ALGORITHM:
        return False
    try:
        calc = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"),
                                   salt.encode("utf-8"), int(rounds))
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(calc.hex(), digest)


class Signer:
    """HMAC-SHA256 签名器：签发 / 校验自包含令牌。"""

    def __init__(self, secret):
        self.secret = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)

    def sign(self, claims: Dict[str, Any]) -> str:
        body = _b64e(json.dumps(claims, ensure_ascii=False, separators=(",", ":"),
                                sort_keys=True).encode("utf-8"))
        signature = _b64e(hmac.new(self.secret, body.encode("ascii"),
                                   hashlib.sha256).digest())
        return body + "." + signature

    def verify(self, token: str, now: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """校验签名与有效期；通过返回 claims，否则返回 None。"""
        if not token or "." not in str(token):
            return None
        body, _, signature = str(token).partition(".")
        expected = _b64e(hmac.new(self.secret, body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, signature):
            return None
        try:
            claims = json.loads(_b64d(body).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        if not isinstance(claims, dict):
            return None
        expires = claims.get("exp")
        if expires is not None and int(expires) < int(now if now is not None else time.time()):
            return None
        return claims
