"""HTTP 鉴权层：注册 / 登录 / 当前用户依赖 / 数据归属校验（见 `docs/12`）。

职责边界：
- `app/auth/` 负责**账号与令牌本身**（口令哈希、令牌签名、用户存储）；
- 这里只负责**把它接到 HTTP 上**：解析请求里的令牌、得到当前用户、
  以及"这个用户能不能访问这条数据"的统一判断。

三种取用户的方式，按场景选用：

| 场景 | 用谁 | 未登录时 |
| --- | --- | --- |
| 普通接口（会话 / 材料 / 办理单） | `make_user_dependency(auth)`（`Depends`） | `AUTH_REQUIRED=1` 时 401；否则演示用户 |
| 材料文件读取（`<image src>`） | `resolve_user()` 手动解析 | 见 `server/materials.py::read_file`（先验文件签名链接） |
| 内部调用 / 单测 | 直接构造 `User` | —— |

兼容策略：`AUTH_REQUIRED` 默认关闭，未携带令牌的请求按**演示用户**处理，
所以单用户 Demo 与既有端到端流程行为完全不变；上线前置为 `1` 即强制登录。
"""
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth.models import User
from app.auth.service import AuthService

from .schemas import LoginRequest, RegisterRequest, TokenOut, UserOut

_TOKEN_HEADER = "authorization"
_FALLBACK_HEADER = "x-auth-token"


def extract_token(request: Request) -> str:
    """从请求头取登录令牌：优先 `Authorization: Bearer <token>`，其次 `X-Auth-Token`。

    只看请求头——查询串里的 `token` 是**材料文件的签名**（另一种令牌类型），
    两者不能混用，所以这里不读查询串。
    """
    raw = (request.headers.get(_TOKEN_HEADER) or "").strip()
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    if raw:
        return raw
    return (request.headers.get(_FALLBACK_HEADER) or "").strip()


def resolve_user(request: Request, auth: AuthService) -> Optional[User]:
    """解析当前用户；用于无法走依赖的入口（如材料文件读取）。

    - 带令牌：签名 / 有效期通过则返回用户，否则返回 None（**不降级为演示用户**，
      否则"令牌过期"会静默变成"以演示用户身份通过"）；
    - 不带令牌：`AUTH_REQUIRED=1` 时返回 None，否则返回演示用户。
    """
    token = extract_token(request)
    if token:
        return auth.resolve(token)
    return None if auth.required else auth.demo_user()


def make_user_dependency(auth: AuthService) -> Callable[..., User]:
    """生成 `Depends` 用的当前用户依赖。"""

    def current_user(request: Request) -> User:
        token = extract_token(request)
        if token:
            user = auth.resolve(token)
            if user is None:
                raise HTTPException(status_code=401, detail="登录已过期或令牌无效，请重新登录")
            return user
        if auth.required:
            raise HTTPException(status_code=401, detail="请先登录")
        return auth.demo_user()

    return current_user


def ensure_access(user: User, owner_id: str, permission: str = "case:any") -> None:
    """校验能否访问 `owner_id` 名下的数据；不能则 403。

    `owner_id` 为空（历史 / 演示数据）时放行，保证老数据仍可读；
    别人的数据需要对应权限（如工作人员的 `case:any`，见 `app/auth/models.py`）。
    """
    if not user.can_access(owner_id, permission):
        raise HTTPException(status_code=403, detail="无权访问他人数据")


def build_auth_router(auth: AuthService) -> APIRouter:
    """账号接口：注册 / 登录 / 当前用户。"""
    router = APIRouter(prefix="/api/auth", tags=["auth"])
    current_user = make_user_dependency(auth)

    @router.post("/register", response_model=UserOut)
    def register(req: RegisterRequest):
        """注册办事账号（演示 / 内测用；生产应接实名与验证码）。"""
        try:
            return auth.register(req.username, req.password,
                                 display_name=req.display_name).to_dict()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.post("/login", response_model=TokenOut)
    def login(req: LoginRequest):
        """账号口令登录，返回自包含令牌。"""
        try:
            user = auth.login(req.username, req.password)
        except KeyError as exc:
            raise HTTPException(status_code=401, detail=str(exc).strip("'\""))
        return {
            "token": auth.issue_token(user),
            "token_type": "Bearer",
            "expires_in": auth.token_ttl_seconds(),
            "user": user.to_dict(),
        }

    @router.get("/me", response_model=UserOut)
    def me(user: User = Depends(current_user)):
        """取当前登录用户（未开启强制鉴权时为演示用户）。"""
        return user.to_dict()

    return router
