"""鉴权模块：用户模型、口令哈希、令牌签名、用户存储与鉴权服务。

为避免循环导入，这里不做 re-export，按需从子模块导入：

    from app.auth.service import AuthService
    from app.auth.models import User, ROLE_STAFF
    from app.auth.store import JsonFileUserStore
"""
