"""用户与权限模型（纯标准库 dataclass，保证骨架零依赖可运行）。

多用户改造的基石：会话 / 材料收集单 / 办理单都记录 `owner_id`，
由这里定义的 `User` 判断"能不能访问别人的数据"（RBAC，见 `docs/02` 安全层）。
"""
from dataclasses import dataclass
from typing import Any, Dict

# 角色（RBAC）
ROLE_APPLICANT = "applicant"   # 办事人：只能操作自己的会话 / 材料 / 办理单
ROLE_STAFF = "staff"           # 政务工作人员：可跨用户查询办理单
ROLE_ADMIN = "admin"           # 管理员：全部权限

# 角色 -> 权限集合；"*" 为通配
PERMISSIONS = {
    ROLE_APPLICANT: frozenset({"session:own", "material:own", "case:own"}),
    ROLE_STAFF: frozenset({"session:own", "material:own", "case:own", "case:any"}),
    ROLE_ADMIN: frozenset({"*"}),
}

ROLES = (ROLE_APPLICANT, ROLE_STAFF, ROLE_ADMIN)

# 演示 / 未登录场景下的默认办事人（`AUTH_REQUIRED` 未开启时使用）
DEMO_USER_ID = "u_demo"


@dataclass
class User:
    """一个办事账号。"""

    user_id: str
    username: str
    display_name: str = ""
    role: str = ROLE_APPLICANT
    created_at: str = ""

    def has_permission(self, permission: str) -> bool:
        perms = PERMISSIONS.get(self.role) or frozenset()
        return "*" in perms or permission in perms

    def is_owner(self, owner_id: str) -> bool:
        """`owner_id` 为空（历史数据 / 演示数据）时不设限，保持向后兼容。"""
        return not owner_id or owner_id == self.user_id

    def can_access(self, owner_id: str, any_permission: str = "case:any") -> bool:
        """能不能读写 `owner_id` 名下的数据。

        自己的数据永远可以；别人的数据需要 `any_permission`（如工作人员的 `case:any`）。
        """
        return self.is_owner(owner_id) or self.has_permission(any_permission)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "User":
        data = data or {}
        return cls(
            user_id=data.get("user_id", ""),
            username=data.get("username", ""),
            display_name=data.get("display_name", ""),
            role=data.get("role", ROLE_APPLICANT),
            created_at=data.get("created_at", ""),
        )


def demo_user() -> User:
    """未开启强制鉴权时的默认办事人（单用户 Demo 兼容用）。"""
    return User(user_id=DEMO_USER_ID, username="demo", display_name="演示用户",
                role=ROLE_APPLICANT, created_at="")
