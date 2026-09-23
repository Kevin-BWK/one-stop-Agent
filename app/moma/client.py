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
    ):
        self.api_base = (
            api_base if api_base is not None else os.getenv("MOMA_API_BASE", "")
        ).strip().rstrip("/")
        self.api_key = (
            api_key if api_key is not None else os.getenv("MOMA_API_KEY", "")
        ).strip()
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

    # ---------- 状态 ----------
    @property
    def live(self) -> bool:
        """是否处于真实模式（已配置地址与密钥）。"""
        return bool(self.api_base and self.api_key)

    def mode(self) -> str:
        """返回当前模式：``live`` 或 ``stub``。"""
        return "live" if self.live else "stub"

    def describe(self) -> Dict[str, Any]:
        """返回可安全暴露的配置摘要（不含密钥）。"""
        return {
            "mode": self.mode(),
            "api_base": self.api_base,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "models": dict(self._pool),
        }

    # ---------- MoMA 三大能力 ----------
    def dispatch(self, task_type: str) -> str:
        """多模型调度：根据任务类型选择模型。"""
        key = self.TASK_MODEL.get(task_type, "default")
        return self._pool[key]

    def chat(self, model: str, messages: List[Dict[str, str]], context: Any = None) -> str:
        """调用模型；无本地回退，失败时抛出 ``MoMAError``。"""
        return self.complete(model, messages, context=context)

    def complete(
        self,
        model: str,
        messages: List[Dict[str, str]],
        fallback: Optional[str] = None,
        context: Any = None,
        temperature: float = 0.2,
    ) -> str:
        """调用模型，支持本地回退。

        - 桩模式：直接返回 ``fallback``（未提供时返回桩文本）。
        - 真实模式：调用 MoMA；调用失败且提供 ``fallback`` 时优雅降级。
        """
        if not self.live:
            if fallback is not None:
                return fallback
            return self._stub(model, messages)
        try:
            return self._chat_live(model, messages, temperature=temperature)
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

    def _chat_live(self, model: str, messages: List[Dict[str, str]], temperature: float = 0.2) -> str:
        session = self._session or self._requests()
        url = self.api_base + "/chat/completions"
        headers = {
            "Authorization": "Bearer " + self.api_key,
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