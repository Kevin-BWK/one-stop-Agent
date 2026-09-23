"""MoMA 平台客户端：多模型调度 / 智能路由 / 上下文管理。

两种运行模式：

- **桩模式（默认）**：未配置 ``MOMA_API_BASE`` / ``MOMA_API_KEY`` 时启用，
  返回本地模拟回复，保证零依赖 Demo 与单元测试可离线运行。
- **真实模式**：配置环境变量后启用，调用 MoMA 的 OpenAI 兼容接口
  ``POST {MOMA_API_BASE}/chat/completions``。

环境变量：

======================  ============================================
``MOMA_API_BASE``       服务地址，例如 https://moma.example.com/v1
``MOMA_API_KEY``        访问密钥（Bearer）
``MOMA_TIMEOUT``        超时秒数，默认 30
``MOMA_MAX_RETRIES``    失败重试次数，默认 2
``MOMA_MODEL_STRONG``   覆盖 strong 模型（可选）
``MOMA_MODEL_LIGHT``    覆盖 light 模型（可选）
``MOMA_MODEL_VISION``   覆盖 vision 模型（可选）
``MOMA_MODEL_RULE``     覆盖 rule 模型（可选）
======================  ============================================

设计要点：对外接口（``dispatch`` / ``chat`` / ``complete`` / ``route``）保持不变，
业务层无需关心当前是桩还是真实，接入真实环境时只需配置环境变量。
"""
import os
import time
from typing import Any, Callable, Dict, List, Optional

from ..config import load_env_file


class MoMAError(RuntimeError):
    """MoMA 调用相关异常基类。"""


class MoMAConfigError(MoMAError):
    """配置缺失或依赖未安装。"""


class MoMAAPIError(MoMAError):
    """MoMA 接口返回异常（网络、HTTP 状态或返回体无法解析）。"""


class MoMAClient:
    MODEL_POOL = {
        "strong": "deepseek-r1",
        "light": "qwen-turbo",
        "vision": "qwen-vl",
        "rule": "rule-engine",
    }
    TASK_MODEL = {
        "consult": "strong",
        "collect": "light",
        "condition": "rule",
        "verify": "vision",
        "progress": "rule",
        "item": "rule",
        "default": "light",
    }
    MODEL_ENV = {
        "strong": "MOMA_MODEL_STRONG",
        "light": "MOMA_MODEL_LIGHT",
        "vision": "MOMA_MODEL_VISION",
        "rule": "MOMA_MODEL_RULE",
    }

    def __init__(
        self,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        session: Any = None,
        sleep: Optional[Callable[[float], None]] = None,
        sub_api_base: Optional[str] = None,
        sub_api_key: Optional[str] = None,
        main_model: Optional[str] = None,
        sub_model: Optional[str] = None,
        load_env: bool = True,
    ):
        if load_env:
            load_env_file()  # 自动读取项目根目录 .env（不覆盖已有环境变量）
        # MOMA_DISABLE_LIVE=1 时忽略环境变量中的地址/密钥（显式参数仍生效），
        # 用于测试与离线演示时强制桩模式，避免误触真实调用。
        self.disabled = bool(os.getenv("MOMA_DISABLE_LIVE"))
        # 主角色（主 Agent）：显式参数 > MOMA_MAIN_* > 兼容旧变量 MOMA_API_*
        self.api_base = (
            self._resolve(api_base, "MOMA_MAIN_API_BASE", "MOMA_API_BASE")
        ).rstrip("/")
        self.api_key = self._resolve(api_key, "MOMA_MAIN_API_KEY", "MOMA_API_KEY")
        # 子角色（子 Agent）：显式参数 > MOMA_SUB_* > 回退到主角色
        self.sub_api_base = (
            self._resolve(sub_api_base, "MOMA_SUB_API_BASE") or self.api_base
        ).rstrip("/")
        self.sub_api_key = self._resolve(sub_api_key, "MOMA_SUB_API_KEY") or self.api_key
        # 每个角色的默认模型（未配置时回退到内置模型池）
        self.main_model = self._resolve(main_model, "MOMA_MAIN_MODEL") or None
        self.sub_model = self._resolve(sub_model, "MOMA_SUB_MODEL") or None
        self.timeout = float(
            timeout if timeout is not None else os.getenv("MOMA_TIMEOUT", "30")
        )
        self.max_retries = int(
            max_retries if max_retries is not None else os.getenv("MOMA_MAX_RETRIES", "2")
        )
        self._session = session  # 可注入（测试用，避免真实网络）
        self._sleep = sleep or time.sleep
        self._pool = dict(self.MODEL_POOL)
        for key, env in self.MODEL_ENV.items():
            value = os.getenv(env)
            if value:
                self._pool[key] = value

    def _resolve(self, explicit: Optional[str], *env_names: str) -> str:
        """显式参数优先；否则取第一个非空环境变量；都没有时返回空串。

        当 ``MOMA_DISABLE_LIVE`` 打开时忽略环境变量（显式参数仍生效），
        以便测试/离线演示强制桩模式。
        """
        if explicit is not None:
            return explicit.strip()
        if self.disabled:
            return ""
        for name in env_names:
            value = os.getenv(name)
            if value is not None and value.strip():
                return value.strip()
        return ""

    # ---------- 状态 ----------
    @property
    def live(self) -> bool:
        """主角色是否处于真实模式（已配置地址与密钥，且未被禁用）。"""
        return self.role_live("main")

    def role_live(self, role: str = "main") -> bool:
        """指定角色（main / sub）是否处于真实模式。"""
        base = self.sub_api_base if role == "sub" else self.api_base
        key = self.sub_api_key if role == "sub" else self.api_key
        return bool(base and key)

    def mode(self) -> str:
        """返回当前模式：``live`` 或 ``stub``。"""
        return "live" if self.live else "stub"

    def describe(self) -> Dict[str, Any]:
        """返回可安全暴露的配置摘要（不含密钥）。"""
        return {
            "mode": self.mode(),
            "disabled": self.disabled,
            "roles": {
                "main": {"live": self.role_live("main"), "api_base": self.api_base,
                         "model": self.main_model or self._pool.get("strong")},
                "sub": {"live": self.role_live("sub"), "api_base": self.sub_api_base,
                        "model": self.sub_model or self._pool.get("light")},
            },
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "models": dict(self._pool),
        }

    # ---------- MoMA 三大能力 ----------
    def dispatch(self, task_type: str) -> str:
        """多模型调度：根据任务类型选择模型。"""
        key = self.TASK_MODEL.get(task_type, "default")
        return self._pool[key]

    def model_for(self, role: str = "main", task: Optional[str] = None) -> str:
        """多模型调度：解析某个角色/任务应使用的模型名。

        - 若配置了角色级模型（``MOMA_MAIN_MODEL`` / ``MOMA_SUB_MODEL``）→ 用它；
        - 否则回退到内置模型池（按任务类型调度，保持离线/旧行为不变）。
        """
        if role == "sub" and self.sub_model:
            return self.sub_model
        if role == "main" and self.main_model:
            return self.main_model
        return self.dispatch(task or role)

    def chat(
        self,
        model: str,
        messages: List[Dict[str, str]],
        context: Any = None,
        role: str = "main",
    ) -> str:
        """调用模型；无本地回退，失败时抛出 ``MoMAError``。"""
        return self.complete(model, messages, context=context, role=role)

    def complete(
        self,
        model: str,
        messages: List[Dict[str, str]],
        fallback: Optional[str] = None,
        context: Any = None,
        temperature: float = 0.2,
        role: str = "main",
    ) -> str:
        """调用模型，支持本地回退。

        - 桩模式：直接返回 ``fallback``（未提供时返回桩文本）。
        - 真实模式：调用 MoMA；调用失败且提供 ``fallback`` 时优雅降级。

        ``role`` 决定使用哪套端点/密钥：``main``（主 Agent）或 ``sub``（子 Agent）。
        """
        if not self.role_live(role):
            if fallback is not None:
                return fallback
            return self._stub(model, messages)
        try:
            return self._chat_live(model, messages, temperature=temperature, role=role)
        except MoMAError:
            if fallback is not None:
                return fallback
            raise

    def route(self, intent: str) -> str:
        """智能路由：返回应处理的 Agent 名称。（真实路由由编排层承担）"""
        return intent

    # ---------- 内部实现 ----------
    @staticmethod
    def _stub(model: str, messages: List[Dict[str, str]]) -> str:
        last = messages[-1]["content"] if messages else ""
        return "[" + model + "] " + last

    def _chat_live(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        role: str = "main",
    ) -> str:
        session = self._session or self._requests()
        base = self.sub_api_base if role == "sub" else self.api_base
        key = self.sub_api_key if role == "sub" else self.api_key
        url = base + "/chat/completions"
        headers = {
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
        }
        payload = {"model": model, "messages": messages, "temperature": temperature}

        last_error: Optional[MoMAError] = None
        for attempt in range(self.max_retries + 1):
            try:
                response = session.post(url, headers=headers, json=payload, timeout=self.timeout)
            except Exception as exc:  # 网络层异常 -> 重试
                last_error = MoMAAPIError("MoMA 请求失败：" + str(exc))
            else:
                status = getattr(response, "status_code", 0)
                if status >= 500 or status == 429:
                    last_error = MoMAAPIError(
                        "MoMA 服务暂时不可用（HTTP " + str(status) + "）：" + self._snippet(response)
                    )
                elif status >= 400:
                    # 4xx 属请求本身问题，重试无意义，直接失败
                    raise MoMAAPIError(
                        "MoMA 请求被拒绝（HTTP " + str(status) + "）：" + self._snippet(response)
                    )
                else:
                    return self._parse(response)
            if attempt < self.max_retries:
                self._sleep(min(0.5 * (2 ** attempt), 4.0))
        raise last_error or MoMAAPIError("MoMA 调用失败")

    def _requests(self) -> Any:
        try:
            import requests
        except ImportError as exc:  # pragma: no cover - 依赖未安装时
            raise MoMAConfigError(
                "真实 MoMA 调用需要 requests：pip install -r requirements.txt"
            ) from exc
        return requests

    @staticmethod
    def _snippet(response: Any) -> str:
        text = getattr(response, "text", "") or ""
        return str(text)[:200]

    @staticmethod
    def _parse(response: Any) -> str:
        try:
            data = response.json()
        except Exception as exc:
            raise MoMAAPIError("MoMA 返回不是合法 JSON") from exc
        # OpenAI 兼容格式
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            pass
        # 兼容部分平台的简化返回
        for key in ("content", "output", "text", "reply"):
            value = data.get(key) if isinstance(data, dict) else None
            if isinstance(value, str):
                return value
        raise MoMAAPIError("无法解析 MoMA 返回：" + str(data)[:200])
