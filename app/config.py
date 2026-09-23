"""全局路径与配置。"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = ROOT / "scenarios"
KNOWLEDGE_DIR = ROOT / "data" / "knowledge"


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
