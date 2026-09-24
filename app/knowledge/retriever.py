"""知识检索：把办事指南按问题切成片段、按相关度返回。

检索有**两条召回通道**，对外契约完全一致：

    search(scenario_id, query, top_k) -> [Chunk, ...]   命中片段（按相关度降序）
    retrieve(scenario_id, query, top_k) -> str          拼成文本；无命中时兜底整篇

1. **关键词基线**（零依赖）：字符 2-gram + 标题加权打分，永远可用，离线可跑；
2. **向量召回**（可选）：配了 ``MOMA_EMBED_MODEL`` 才启用，语义相近即可命中
   （问"排烟"也能找到"油烟净化设施"），见 `app/knowledge/embedding.py`。

两路结果用 **RRF（倒数排名融合）** 合并——向量懂语义、关键词抓字面，互补后更稳。
向量端点不可用时**自动降级**到关键词基线（进入冷却期，过后自动重试），
检索（进而咨询）不会因此失败。`ConsultAgent` 等调用方一行都不用改。

「配了向量却没生效」这类问题不用猜：`explain()` 给出单次检索的完整快照
（命中片段、两路分数、实际通道、降级原因），`stats()` 给出累计计数。

零依赖的中文检索为什么用 2-gram：中文没有空格，没有分词器时按"相邻两字"切
已经能覆盖绝大多数中文词组（"油烟"、"材料"、"营业执照"），且不需要词典。
"""
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .embedding import (EmbeddingClient, EmbeddingError, VectorIndex, fingerprint,
                        load_vectors, save_vectors)

NOT_FOUND = "未找到该场景办事指南。"

# RRF（Reciprocal Rank Fusion）常数：越大越"平滑"，60 是常用默认值
RRF_K = 60
# 向量召回候选倍数：先多召回一些再融合，给 RRF 留出排序空间
VECTOR_CANDIDATES = 4
# 向量构建失败后的冷却秒数：期间走基线，冷却结束自动再试（端点恢复后无需重启进程）
VECTOR_RETRY_COOLDOWN = 60.0

# 标题命中的权重：问题里的词如果出现在小节标题上，通常比出现在正文里更相关
TITLE_WEIGHT = 3.0
# 长度归一系数：避免长段落仅因为"字多"就压过短而精准的条目
LENGTH_PENALTY = 0.05

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.、)])\s+")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_WORD = re.compile(r"[a-z0-9]+")


@dataclass
class Chunk:
    """一个可检索的指南片段。"""
    scenario_id: str
    heading: str              # 所属小节标题（如文档标题"开办餐饮店办事指南"）
    text: str
    score: float = 0.0

    def render(self) -> str:
        return self.text


@dataclass
class _Entry:
    """建索引时预存分词结果，避免每次检索重复切词。"""
    heading: str
    text: str
    heading_tokens: frozenset = field(default_factory=frozenset)
    text_tokens: frozenset = field(default_factory=frozenset)


@dataclass
class _Hit:
    """一次召回命中的片段及其**分数来源**（可观测性靠它，见 `explain()`）。"""
    index: int
    entry: _Entry
    score: float                              # 最终分数（融合后，或纯关键词分）
    vector_score: Optional[float] = None      # 该片段的余弦相似度（没走向量时为 None）
    keyword_score: Optional[float] = None     # 该片段的关键词分（没被关键词命中时为 None）


@dataclass
class RetrievalResult:
    """一次检索的完整过程快照：`search()` 只用它的 hits，`explain()` 暴露全部。"""
    scenario_id: str
    doc_key: str
    query: str
    channel: str                              # "keyword" 或 "vector+keyword"
    hits: List[_Hit] = field(default_factory=list)
    degraded: str = ""                        # 降级原因；空串表示向量通道正常工作
    vector_model: str = ""
    vector_min_score: float = 0.0
    elapsed_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "doc_key": self.doc_key,
            "query": self.query,
            "channel": self.channel,
            "degraded": self.degraded,
            "vector_model": self.vector_model,
            "vector_min_score": self.vector_min_score,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "hits": [
                {
                    "index": hit.index,
                    "heading": hit.entry.heading,
                    "text": hit.entry.text,
                    "score": round(hit.score, 6),
                    "vector_score": (round(hit.vector_score, 6)
                                     if hit.vector_score is not None else None),
                    "keyword_score": (round(hit.keyword_score, 6)
                                      if hit.keyword_score is not None else None),
                }
                for hit in self.hits
            ],
        }


def tokenize(text: str) -> List[str]:
    """极简分词（零依赖）：中文取 2-gram（单字则取该字本身），英文/数字按词。"""
    lowered = (text or "").lower()
    tokens: List[str] = []
    for run in _CJK_RUN.findall(lowered):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[index:index + 2] for index in range(len(run) - 1))
    tokens.extend(_WORD.findall(lowered))
    return tokens


def split_chunks(markdown: str) -> List[Tuple[str, str]]:
    """把 markdown 切成可检索的片段，返回 `[(小节标题, 片段正文), ...]`。

    两级切分：

    1. 按标题分节，标题单独存进 `heading`（参与打分，但不重复进正文）；
    2. 节内按空行分段，**列表项逐条拆开**——办事指南里的"事项/材料/条件"几乎都是
       列表，每条独立成块检索粒度才够细。
    """
    chunks: List[Tuple[str, str]] = []
    heading = ""
    buffer: List[str] = []

    def flush():
        nonlocal buffer
        text = "\n".join(buffer).strip()
        if text:
            chunks.append((heading, text))
        buffer = []

    for raw in (markdown or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush()
            continue
        matched = _HEADING.match(line)
        if matched:
            flush()
            heading = matched.group(2).strip()
            continue
        if _LIST_ITEM.match(line):
            flush()
            item = _LIST_ITEM.sub("", line).strip()
            if item:
                chunks.append((heading, item))
            continue
        buffer.append(line)
    flush()
    return chunks


def format_chunks(chunks: Sequence[Chunk]) -> str:
    """把检索结果拼成可读文本（去重、保持相关度顺序）。"""
    seen = set()
    lines = []
    for chunk in chunks:
        text = (chunk.text or "").strip()
        if text and text not in seen:
            seen.add(text)
            lines.append(text)
    return "\n".join(lines)


def rrf_fuse(rankings: Sequence[Sequence[Tuple[int, float]]],
             k: int = RRF_K) -> List[Tuple[int, float]]:
    """倒数排名融合（RRF）：把多路召回的**排名**（而不是分数）合成一个分数。

    不同通道的分数（余弦相似度 vs 关键词权重）量纲不同，直接相加没有意义；
    只看"排第几"就能公平合并，且天然偏好**多路都命中**的片段：

        score(d) = Σ 1 / (k + rank(d))
    """
    scores: Dict[int, float] = {}
    for ranking in rankings:
        for rank, (index, _weight) in enumerate(ranking):
            scores[index] = scores.get(index, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


class KnowledgeBase:
    """按场景加载办事指南，并支持按问题检索片段。"""

    def __init__(self, data_dir: Path, embedder: Optional[EmbeddingClient] = None,
                 cache_dir: Optional[Path] = None):
        self.data_dir = Path(data_dir)
        self._docs: Dict[str, str] = {}
        self._index: Dict[str, List[_Entry]] = {}
        for path in sorted(self.data_dir.glob("*.md")):
            key = path.stem.replace("_guide", "")
            text = path.read_text(encoding="utf-8")
            self._docs[key] = text
            self._index[key] = [
                _Entry(heading=heading, text=body,
                       heading_tokens=frozenset(tokenize(heading)),
                       text_tokens=frozenset(tokenize(body)))
                for heading, body in split_chunks(text)
            ]
        # 向量检索是可选增强：默认按环境变量自动装配；未配置时 available 为 False，
        # search() 自动走零依赖的关键词基线，行为与接入前完全一致。
        # 传入 embedder 可直接注入（测试 / 定制）。
        self._embedder = embedder if embedder is not None else EmbeddingClient()
        self._cache_dir = (
            Path(cache_dir) if cache_dir
            else self.data_dir.parent / "runtime" / "knowledge_vectors"
        )
        self._vectors: Dict[str, VectorIndex] = {}    # 已建好的向量索引（按场景缓存）
        self._vector_failed: Dict[str, float] = {}     # 场景 -> 冷却结束时间（过了自动重试）
        # 可注入的时钟与冷却时长：便于测试"端点恢复后自动回归向量"（见 tests）
        self._clock = time.monotonic
        self.vector_retry_cooldown = VECTOR_RETRY_COOLDOWN
        # 轻量计数：让"检索到底有没有生效"可观测（见 stats()）
        self._stats: Dict[str, int] = {
            "searches": 0, "vector_used": 0, "degraded": 0,
            "cache_hits": 0, "embed_calls": 0,
        }

    # ---------- 对外 ----------

    def scenarios(self) -> List[str]:
        """已加载指南的场景键（如 `restaurant` / `enterprise`）。"""
        return sorted(self._docs)

    def search(self, scenario_id: str, query: str, top_k: int = 3) -> List[Chunk]:
        """按问题检索片段，按相关度降序返回；没有命中就返回空列表。

        查询为空时直接返回空——"没问"不该等于"问什么都能匹配"。

        召回分两路：关键词基线永远跑；向量通道启用且可用时，两路结果用 RRF 融合。
        想知道"命中了什么、分从哪来、有没有降级"，用 `explain()`。
        """
        result = self._retrieve(scenario_id, query, top_k)
        return [
            Chunk(scenario_id=scenario_id, heading=hit.entry.heading,
                  text=hit.entry.text, score=hit.score)
            for hit in result.hits
        ]

    def explain(self, scenario_id: str, query: str, top_k: int = 3) -> Dict[str, Any]:
        """检索过程的可观测快照（只读、无副作用），给调试与评估用。

        返回命中的片段、**每个片段的两路分数**、实际走的通道，以及降级原因——
        「配了向量却没生效」看一次就知道是没配置、在冷却、还是构建失败。
        """
        return self._retrieve(scenario_id, query, top_k).to_dict()

    def stats(self) -> Dict[str, int]:
        """累计计数：检索次数 / 向量生效次数 / 降级次数 / 缓存命中 / 向量调用。"""
        return dict(self._stats)

    def _retrieve(self, scenario_id: str, query: str, top_k: int) -> RetrievalResult:
        started = self._clock()
        key = self._doc_key(scenario_id)
        entries = self._index.get(key) or []
        text = (query or "").strip()
        self._stats["searches"] += 1
        model = self._embedder.model if self._embedder else ""
        min_score = self._embedder.min_score if self._embedder else 0.0

        if not entries or not text:
            return self._result(scenario_id, key, text, "keyword", [], "", model,
                                min_score, started)

        keyword = self._keyword_rank(frozenset(tokenize(text)), entries)
        index, degraded = self._ensure_vector(key)
        if index is None:
            self._stats["degraded"] += 1
            return self._result(scenario_id, key, text, "keyword",
                                self._hits(entries, keyword, top_k), degraded, model,
                                min_score, started)

        try:
            query_vector = self._embedder.embed([text])[0]
        except EmbeddingError as exc:
            # 向量是增强项：端点抖动时静默回退关键词基线，别让"咨询"跟着失败
            self._stats["degraded"] += 1
            return self._result(scenario_id, key, text, "keyword",
                                self._hits(entries, keyword, top_k),
                                "查询向量失败：" + (str(exc)[:100] or "未知错误"),
                                model, min_score, started)

        vector = index.search(query_vector, max(1, int(top_k)) * VECTOR_CANDIDATES,
                              min_score=min_score)
        if not vector:
            self._stats["degraded"] += 1
            return self._result(scenario_id, key, text, "keyword",
                                self._hits(entries, keyword, top_k),
                                "向量召回为空（相似度均低于 " + str(min_score) + "）",
                                model, min_score, started)

        self._stats["vector_used"] += 1
        return self._result(scenario_id, key, text, "vector+keyword",
                            self._fuse(entries, vector, keyword, top_k), "", model,
                            min_score, started)

    def _result(self, scenario_id: str, key: str, text: str, channel: str,
                hits: List[_Hit], degraded: str, model: str, min_score: float,
                started: float) -> RetrievalResult:
        return RetrievalResult(
            scenario_id=scenario_id, doc_key=key, query=text, channel=channel,
            hits=hits, degraded=degraded, vector_model=model,
            vector_min_score=min_score,
            elapsed_ms=(self._clock() - started) * 1000.0,
        )

    @staticmethod
    def _hits(entries: Sequence[_Entry], ranked: Sequence[Tuple[int, float]],
              top_k: int) -> List[_Hit]:
        """纯关键词路径的命中（分数即关键词分，标出来供 `explain()` 看）。"""
        return [_Hit(index=index, entry=entries[index], score=score, keyword_score=score)
                for index, score in ranked[:max(1, int(top_k))]]

    @staticmethod
    def _fuse(entries: Sequence[_Entry], vector: Sequence[Tuple[int, float]],
              keyword: Sequence[Tuple[int, float]], top_k: int) -> List[_Hit]:
        """RRF 融合两路召回，并**保留各路的原始分数**（可观测性靠它）。"""
        vector_scores = dict(vector)
        keyword_scores = dict(keyword)
        hits: List[_Hit] = []
        for index, score in rrf_fuse([vector, keyword])[:max(1, int(top_k))]:
            hits.append(_Hit(
                index=index, entry=entries[index], score=score,
                vector_score=vector_scores.get(index),
                keyword_score=keyword_scores.get(index),
            ))
        return hits

    def retrieve(self, scenario_id: str, query: str = "", top_k: int = 3) -> str:
        """检索并拼成文本；查询为空或没有命中时**兜底返回整篇指南**。"""
        chunks = self.search(scenario_id, query, top_k=top_k)
        if chunks:
            return format_chunks(chunks)
        return self._docs.get(self._doc_key(scenario_id), NOT_FOUND)

    # ---------- 内部：关键词通道 ----------

    @staticmethod
    def _score(query_tokens: frozenset, entry: _Entry) -> float:
        title_hits = len(query_tokens & entry.heading_tokens)
        body_hits = len(query_tokens & entry.text_tokens)
        if not title_hits and not body_hits:
            return 0.0
        raw = TITLE_WEIGHT * title_hits + body_hits
        return raw / (1.0 + LENGTH_PENALTY * len(entry.text_tokens))

    def _keyword_rank(self, query_tokens: frozenset,
                      entries: Sequence[_Entry]) -> List[Tuple[int, float]]:
        """关键词基线召回：`[(片段下标, 分数), ...]`，按分数降序。"""
        ranked: List[Tuple[int, float]] = []
        for index, entry in enumerate(entries):
            score = self._score(query_tokens, entry)
            if score > 0:
                ranked.append((index, score))
        ranked.sort(key=lambda item: item[1], reverse=True)
        return ranked

    # ---------- 内部：向量通道 ----------

    def _ensure_vector(self, key: str) -> Tuple[Optional[VectorIndex], str]:
        """取（或构建）该场景的向量索引，返回 `(索引或 None, 降级原因)`。

        降级**不是永久的**：构建失败后进入冷却期，冷却结束会自动再试——
        端点恢复后无需重启进程（旧实现一失败就永久走基线，恢复了也没人知道）。
        """
        if not key:
            return None, "该场景没有指南"
        if self._embedder is None or not self._embedder.available:
            return None, "未配置向量模型（MOMA_EMBED_MODEL）"
        ready = self._vectors.get(key)
        if ready is not None:
            return ready, ""
        now = self._clock()
        retry_at = self._vector_failed.get(key)
        if retry_at is not None:
            if now < retry_at:
                return None, "向量构建失败，冷却中（约 " + str(int(retry_at - now)) + "s 后重试）"
            self._vector_failed.pop(key, None)      # 冷却结束 -> 再试一次
        entries = self._index.get(key) or []
        if not entries:
            return None, "该场景没有可检索片段"
        try:
            vectors = self._build_vectors(key, entries)
        except Exception as exc:
            self._vector_failed[key] = now + self.vector_retry_cooldown
            return None, "向量构建失败：" + (str(exc)[:100] or exc.__class__.__name__)
        if not vectors:
            self._vector_failed[key] = now + self.vector_retry_cooldown
            return None, "向量构建结果为空"
        index = VectorIndex(vectors)
        self._vectors[key] = index
        return index, ""

    def _build_vectors(self, key: str, entries: Sequence[_Entry]) -> List[List[float]]:
        """构建片段向量：优先读缓存（模型 / 文本指纹匹配），否则调端点并落盘。"""
        texts = [self._vector_text(entry) for entry in entries]
        stamp = fingerprint(texts)
        cache_file = self._cache_dir / (key + ".json")
        cached = load_vectors(cache_file, self._embedder.model, stamp)
        if cached is not None:
            self._stats["cache_hits"] += 1
            return cached
        vectors = self._embedder.embed(texts)
        self._stats["embed_calls"] += 1
        save_vectors(cache_file, self._embedder.model, stamp, vectors)
        return vectors

    @staticmethod
    def _vector_text(entry: _Entry) -> str:
        """参与向量化的文本：带上小节标题（标题是有效语义信号）。"""
        return (entry.heading + " " + entry.text).strip() if entry.heading else entry.text

    def _doc_key(self, scenario_id: str) -> str:
        """场景 id -> 指南文件键。

        场景 id 形如 `restaurant_open`，而指南文件名是 `restaurant_guide.md`（键 `restaurant`），
        所以先按原样找，再退化到第一段。
        """
        key = str(scenario_id or "")
        for candidate in (key, key.split("_")[0]):
            if candidate in self._docs:
                return candidate
        return ""
