"""全局路径与配置。"""
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = ROOT / "scenarios"
KNOWLEDGE_DIR = ROOT / "data" / "knowledge"

# 鉴权与存储相关默认值（可用环境变量覆盖，见 docs/12）
DEFAULT_TOKEN_TTL = 7 * 24 * 3600      # 登录令牌有效期（秒）
DEFAULT_FILE_URL_TTL = 10 * 60         # 材料文件签名链接有效期（秒）
DEFAULT_STORAGE_BACKEND = "json"       # memory / json / sql / redis

# 开发环境的密钥文件（data/runtime 已在 .gitignore 中，不会入库）
_SECRET_FILE = ROOT / "data" / "runtime" / "auth_secret.key"


def env_flag(name: str, default: bool = False) -> bool:
    """读布尔型环境变量（`1/true/yes/on` 为真）。"""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "y", "on")


def env_int(name: str, default: int) -> int:
    """读整型环境变量；非法值回退默认值。"""
    try:
        return int(str(os.environ.get(name, "")).strip())
    except (TypeError, ValueError):
        return default


def auth_secret() -> bytes:
    """令牌签名密钥。

    取值优先级：
    1. `AUTH_SECRET` 环境变量（生产**必须**显式配置，且各实例一致）；
    2. `data/runtime/auth_secret.key`（开发环境自动生成并复用，重启不失效）。

    密钥只用于本机签名，**不对外输出**（与 MoMA 密钥同样的安全约定）。
    """
    load_env_file()
    value = os.environ.get("AUTH_SECRET")
    if value:
        return value.encode("utf-8")
    if _SECRET_FILE.exists():
        try:
            text = _SECRET_FILE.read_text(encoding="utf-8").strip()
            if text:
                return text.encode("utf-8")
        except OSError:
            pass
    text = secrets.token_hex(32)
    try:
        _SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SECRET_FILE.write_text(text, encoding="utf-8")
    except OSError:
        pass
    return text.encode("utf-8")


def load_env_file(path=None, override=False):
    """读取 ``.env`` 并注入环境变量（零依赖，不引入第三方库）。

    - 默认读取项目根目录下的 ``.env``；
    - 已存在的环境变量默认**不覆盖**（真实环境变量优先）；
    - 文件不存在时静默返回 ``False``；
    - 只做 KEY=VALUE 解析，支持 ``#`` 注释与成对引号。

    安全提示：``.env`` 已在 ``.gitignore`` 中，切勿提交或打印其内容。
    """
    env_path = Path(path) if path else (ROOT / ".env")
    if not env_path.exists():
        return False
    for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = value
    return True
