"""知识检索：把办事指南按问题切成片段、按相关度返回。

检索有**两条召回通道**，对外契约完全一致：

    search(scenario_id, query, top_k) -> [Chunk, ...]   命中片段（按相关度降序）
    retrieve(scenario_id, query, top_k) -> str          拼成文本；无命中时兜底整篇

1. **关键词基线**（零依赖）：字符 2-gram + 标题加权打分，永远可用，离线可跑；
2. **向量召回**（可选）：配了 ``MOMA_EMBED_MODEL`` 才启用，语义相近即可命中
   （问"排烟"也能找到"油烟净化设施"），见 `app/knowledge/embedding.py`。

两路结果用 **RRF（倒数排名融合）** 合并——向量懂语义、关键词抓字面，互补后更稳。
向量端点不可用时**自动降级**到关键词基线，检索（进而咨询）不会因此失败。
`ConsultAgent` 等调用方一行都不用改。

零依赖的中文检索为什么用 2-gram：中文没有空格，没有分词器时按"相邻两字"切
已经能覆盖绝大多数中文词组（"油烟"、"材料"、"营业执照"），且不需要词典。
"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .embedding import (EmbeddingClient, EmbeddingError, VectorIndex, fingerprint,
                        load_vectors, save_vectors)

NOT_FOUND = "未找到该场景办事指南。"

# RRF（Reciprocal Rank Fusion）常数：越大越"平滑"，60 是常用默认值
RRF_K = 60
# 向量召回候选倍数：先多召回一些再融合，给 RRF 留出排序空间
VECTOR_CANDIDATES = 4

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
        self._vectors: Dict[str, VectorIndex] = {}   # 已建好的向量索引（按场景缓存）
        self._vector_failed: set = set()             # 构建失败的场景：本进程内不再重试

    # ---------- 对外 ----------

    def scenarios(self) -> List[str]:
        """已加载指南的场景键（如 `restaurant` / `enterprise`）。"""
        return sorted(self._docs)

    def search(self, scenario_id: str, query: str, top_k: int = 3) -> List[Chunk]:
        """按问题检索片段，按相关度降序返回；没有命中就返回空列表。

        查询为空时直接返回空——"没问"不该等于"问什么都能匹配"。

        召回分两路：关键词基线永远跑；向量通道启用且可用时，两路结果用 RRF 融合。
        """
        key = self._doc_key(scenario_id)
        entries = self._index.get(key) or []
        text = (query or "").strip()
        if not entries or not text:
            return []

        keyword = self._keyword_rank(frozenset(tokenize(text)), entries)
        index = self._ensure_vector(key)
        if index is None:
            return self._to_chunks(scenario_id, entries, keyword, top_k)

        try:
            query_vector = self._embedder.embed([text])[0]
        except EmbeddingError:
            # 向量是增强项：端点抖动时静默回退关键词基线，别让"咨询"跟着失败
            return self._to_chunks(scenario_id, entries, keyword, top_k)

        vector = index.search(query_vector, max(1, int(top_k)) * VECTOR_CANDIDATES,
                              min_score=self._embedder.min_score)
        if not vector:
            return self._to_chunks(scenario_id, entries, keyword, top_k)
        return self._to_chunks(scenario_id, entries, rrf_fuse([vector, keyword]), top_k)

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

    @staticmethod
    def _to_chunks(scenario_id: str, entries: Sequence[_Entry],
                   ranked: Sequence[Tuple[int, float]], top_k: int) -> List[Chunk]:
        """把 `[(下标, 分数)]` 还原成 `Chunk` 列表（截断到 top_k）。"""
        chunks: List[Chunk] = []
        for index, score in ranked[:max(1, int(top_k))]:
            entry = entries[index]
            chunks.append(Chunk(scenario_id=scenario_id, heading=entry.heading,
                                text=entry.text, score=score))
        return chunks

    # ---------- 内部：向量通道 ----------

    def _ensure_vector(self, key: str) -> Optional[VectorIndex]:
        """取（或构建）该场景的向量索引；未启用 / 构建失败时返回 None（走基线）。"""
        if not key or self._embedder is None or not self._embedder.available:
            return None
        if key in self._vectors:
            return self._vectors[key]
        if key in self._vector_failed:
            return None
        entries = self._index.get(key) or []
        if not entries:
            return None
        try:
            vectors = self._build_vectors(key, entries)
            index = VectorIndex(vectors) if vectors else None
        except Exception:
            index = None
        if index is None:
            # 端点不可用：本进程内不再重试，避免每次咨询都卡一次超时
            self._vector_failed.add(key)
            return None
        self._vectors[key] = index
        return index

    def _build_vectors(self, key: str, entries: Sequence[_Entry]) -> List[List[float]]:
        """构建片段向量：优先读缓存（模型 / 文本指纹匹配），否则调端点并落盘。"""
        texts = [self._vector_text(entry) for entry in entries]
        stamp = fingerprint(texts)
        cache_file = self._cache_dir / (key + ".json")
        cached = load_vectors(cache_file, self._embedder.model, stamp)
        if cached is not None:
            return cached
        vectors = self._embedder.embed(texts)
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
