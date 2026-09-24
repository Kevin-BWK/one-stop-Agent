"""向量检索支撑：Embedding 客户端与向量索引（见 `docs/11`）。

与 `app/moma/client.py` 同一种风格——**桩 / 真实一键切换**：

- **未启用**（未配置 ``MOMA_EMBED_MODEL``、或端点缺失、或 ``MOMA_DISABLE_LIVE=1``）：
  本模块不参与检索，`KnowledgeBase` 继续走零依赖的本地 2-gram 基线，离线可用；
- **启用后**：调用 OpenAI 兼容的 ``POST {API_BASE}/embeddings``，把片段与问题映射成
  稠密向量，按余弦相似度召回，再与关键词召回做 RRF 融合（见 `retriever.py`）。

对外只有 `EmbeddingClient`（`available` / `embed`）与 `cosine` / `VectorIndex`；
谁来装配由 `retriever.py` 决定，`ConsultAgent` 等调用方完全无感（契约不变）。

环境变量：

=============================  ==================================================
``MOMA_EMBED_MODEL``           向量模型名，**配了它才启用向量检索**（如 bge-large-zh）
``MOMA_EMBED_API_BASE``        向量端点，默认回退 ``MOMA_MAIN_API_BASE`` / ``MOMA_API_BASE``
``MOMA_EMBED_API_KEY``         向量密钥，默认回退 ``MOMA_MAIN_API_KEY`` / ``MOMA_API_KEY``
``MOMA_EMBED_MIN_SCORE``       余弦相似度下限，低于它的召回直接丢弃（不配则按模型名取默认）
=============================  ==================================================

``MOMA_TIMEOUT`` / ``MOMA_MAX_RETRIES`` / ``MOMA_DISABLE_LIVE`` 同样生效。

密钥安全：``describe()`` **从不包含密钥**，与 `MoMAClient` 一致。
"""
import hashlib
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..config import load_env_file

# 一次请求最多带多少段文本：片段很少，主要是防止将来语料变大时超出接口上限
BATCH_SIZE = 16

# 余弦相似度下限的通用兜底默认值
DEFAULT_MIN_SCORE = 0.2
# 不同 embedding 模型的余弦分布差异很大（BGE 系普遍偏高、OpenAI 偏低），
# 单一阈值不通用；未显式配置 MOMA_EMBED_MIN_SCORE 时按模型名取默认值。
MIN_SCORE_BY_MODEL = (
    ("bge", 0.45),
    ("text-embedding-3", 0.30),
    ("m3e", 0.40),
    ("gte", 0.40),
    ("qwen", 0.40),
    ("glm", 0.35),
)


def default_min_score(model: Optional[str]) -> float:
    """按模型名给一个合理的余弦下限；认不出就退回 `DEFAULT_MIN_SCORE`。"""
    name = (model or "").lower()
    for keyword, value in MIN_SCORE_BY_MODEL:
        if keyword in name:
            return value
    return DEFAULT_MIN_SCORE


class EmbeddingError(RuntimeError):
    """向量调用相关异常（网络、HTTP 状态或返回体无法解析）。"""


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """余弦相似度（零依赖）；维度不一致或含零向量时一律返回 0.0。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = norm_a = norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def fingerprint(texts: Sequence[str]) -> str:
    """片段集合指纹：文本内容或数量变了，向量缓存即失效。"""
    digest = hashlib.sha1()
    for text in texts:
        digest.update((text or "").encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


class EmbeddingClient:
    """OpenAI 兼容的 Embedding 客户端；未配置时 `available` 为 False。"""

    def __init__(
        self,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        session: Any = None,
        sleep: Optional[Callable[[float], None]] = None,
        load_env: bool = True,
    ):
        if load_env:
            load_env_file()  # 自动读取项目根目录 .env（不覆盖已有环境变量）
        self.disabled = bool(os.getenv("MOMA_DISABLE_LIVE"))
        self.api_base = self._resolve(
            api_base, "MOMA_EMBED_API_BASE", "MOMA_MAIN_API_BASE", "MOMA_API_BASE"
        ).rstrip("/")
        self.api_key = self._resolve(
            api_key, "MOMA_EMBED_API_KEY", "MOMA_MAIN_API_KEY", "MOMA_API_KEY"
        )
        self.model = self._resolve(model, "MOMA_EMBED_MODEL")
        self.timeout = float(
            timeout if timeout is not None else os.getenv("MOMA_TIMEOUT", "30")
        )
        self.max_retries = int(
            max_retries if max_retries is not None else os.getenv("MOMA_MAX_RETRIES", "2")
        )
        # 阈值优先级：显式环境变量 > 按模型名的默认值 > 通用兜底。
        # 硬编码一个值会把召回要么砍光（模型分布偏低）、要么放进噪声（分布偏高）。
        raw_min_score = os.getenv("MOMA_EMBED_MIN_SCORE")
        if raw_min_score is not None and raw_min_score.strip():
            self.min_score = float(raw_min_score)
            self.min_score_source = "env"
        else:
            self.min_score = default_min_score(self.model)
            self.min_score_source = "model-default"
        self._session = session  # 可注入（测试用，避免真实网络）
        self._sleep = sleep or time.sleep

    @staticmethod
    def _resolve(explicit: Optional[str], *env_names: str) -> str:
        """显式参数优先；否则取第一个非空环境变量；都没有时返回空串。

        ``MOMA_DISABLE_LIVE`` 打开时忽略环境变量（显式参数仍生效），
        便于测试 / 离线演示强制停用向量检索。
        """
        if explicit is not None:
            return explicit.strip()
        if os.getenv("MOMA_DISABLE_LIVE"):
            return ""
        for name in env_names:
            value = os.getenv(name)
            if value is not None and value.strip():
                return value.strip()
        return ""

    # ---------- 状态 ----------

    @property
    def available(self) -> bool:
        """是否具备向量检索条件：有模型名 + 有端点 + 未被禁用。

        刻意**不要求密钥**：内网端点常不校验密钥；真缺了也会在调用失败时降级基线。
        """
        return bool(self.model and self.api_base and not self.disabled)

    def mode(self) -> str:
        """返回当前模式：``live``（启用向量）或 ``stub``（走基线）。"""
        return "live" if self.available else "stub"

    def describe(self) -> Dict[str, Any]:
        """可安全暴露的配置摘要（不含密钥）。"""
        return {
            "mode": self.mode(),
            "disabled": self.disabled,
            "api_base": self.api_base,
            "model": self.model,
            "min_score": self.min_score,
            "min_score_source": self.min_score_source,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
        }

    # ---------- 对外 ----------

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        """把若干段文本映射成向量，**按输入顺序**返回。"""
        items = [text or "" for text in (texts or [])]
        if not items:
            return []
        if not self.available:
            raise EmbeddingError("未配置向量模型（MOMA_EMBED_MODEL），无法向量化")
        vectors: List[List[float]] = []
        for start in range(0, len(items), BATCH_SIZE):
            vectors.extend(self._embed_batch(items[start:start + BATCH_SIZE]))
        if len(vectors) != len(items):
            raise EmbeddingError(
                "向量返回数量与输入不一致：" + str(len(vectors)) + " != " + str(len(items))
            )
        return vectors

    # ---------- 内部实现 ----------

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        session = self._session or self._requests()
        url = self.api_base + "/embeddings"
        headers = {
            "Authorization": "Bearer " + self.api_key,
            "Content-Type": "application/json",
        }
        payload = {"model": self.model, "input": list(texts)}

        last_error: Optional[EmbeddingError] = None
        for attempt in range(self.max_retries + 1):
            try:
                response = session.post(url, headers=headers, json=payload, timeout=self.timeout)
            except Exception as exc:  # 网络层异常 -> 重试
                last_error = EmbeddingError("向量请求失败：" + str(exc))
            else:
                status = getattr(response, "status_code", 0)
                if status >= 500 or status == 429:
                    last_error = EmbeddingError(
                        "向量服务暂时不可用（HTTP " + str(status) + "）：" + self._snippet(response)
                    )
                elif status >= 400:
                    # 4xx 属请求本身问题，重试无意义，直接失败
                    raise EmbeddingError(
                        "向量请求被拒绝（HTTP " + str(status) + "）：" + self._snippet(response)
                    )
                else:
                    return self._parse(response, len(texts))
            if attempt < self.max_retries:
                self._sleep(min(0.5 * (2 ** attempt), 4.0))
        raise last_error or EmbeddingError("向量调用失败")

    def _requests(self) -> Any:
        try:
            import requests
        except ImportError as exc:  # pragma: no cover - 依赖未安装时
            raise EmbeddingError(
                "真实向量调用需要 requests：pip install -r requirements.txt"
            ) from exc
        return requests

    @staticmethod
    def _snippet(response: Any) -> str:
        return str(getattr(response, "text", "") or "")[:200]

    @staticmethod
    def _parse(response: Any, expected: int) -> List[List[float]]:
        try:
            data = response.json()
        except Exception as exc:
            raise EmbeddingError("向量返回不是合法 JSON") from exc
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list) or len(items) != expected:
            raise EmbeddingError("无法解析向量返回：" + str(data)[:200])
        # OpenAI 兼容返回带 index，且不保证顺序 —— 按 index 归位
        ordered: List[Optional[List[float]]] = [None] * expected
        for position, item in enumerate(items):
            if not isinstance(item, dict):
                raise EmbeddingError("向量条目格式异常：" + str(item)[:120])
            vector = item.get("embedding")
            if not isinstance(vector, list) or not vector:
                raise EmbeddingError("向量条目缺少 embedding：" + str(item)[:120])
            index = item.get("index")
            slot = index if isinstance(index, int) and 0 <= index < expected else position
            ordered[slot] = [float(value) for value in vector]
        if any(vector is None for vector in ordered):
            raise EmbeddingError("向量返回不完整")
        return [vector for vector in ordered if vector is not None]


class VectorIndex:
    """一组片段向量的余弦召回索引。"""

    def __init__(self, vectors: Sequence[Sequence[float]]):
        self.vectors = [list(vector) for vector in vectors]

    def __len__(self) -> int:
        return len(self.vectors)

    def search(self, query_vector: Sequence[float], top_k: int,
               min_score: float = 0.0) -> List[Tuple[int, float]]:
        """返回 `[(片段下标, 相似度), ...]`，按相似度降序；低于 `min_score` 的丢弃。"""
        if not self.vectors or not query_vector:
            return []
        scored: List[Tuple[int, float]] = []
        for index, vector in enumerate(self.vectors):
            score = cosine(query_vector, vector)
            if score >= min_score:
                scored.append((index, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:max(1, int(top_k))]


# ---------- 向量缓存（避免每次启动都重算，见 docs/11）----------

def load_vectors(path: Path, model: str, text_fingerprint: str) -> Optional[List[List[float]]]:
    """读向量缓存；模型或片段指纹不匹配（含文件损坏）时返回 None。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if data.get("model") != model or data.get("fingerprint") != text_fingerprint:
        return None
    vectors = data.get("vectors")
    if not isinstance(vectors, list) or not vectors:
        return None
    return vectors


def save_vectors(path: Path, model: str, text_fingerprint: str,
                 vectors: Sequence[Sequence[float]]) -> bool:
    """写向量缓存；失败只返回 False——缓存是优化项，不该影响检索。"""
    payload = {"model": model, "fingerprint": text_fingerprint, "vectors": vectors}
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception:
        return False
