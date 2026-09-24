"""知识检索：把办事指南按问题切成片段、按相关度返回。

**当前实现是零依赖的本地基线**（字符 2-gram + 标题加权打分），不引入任何第三方库，
两个场景的指南只有十几行，这个基线足够用；真实形态是把 `search()` 换成
向量检索 / Embedding（BGE 等），**对外契约不变**：

    search(scenario_id, query, top_k) -> [Chunk, ...]   命中片段（按相关度降序）
    retrieve(scenario_id, query, top_k) -> str          拼成文本；无命中时兜底整篇

换实现时只改本文件，`ConsultAgent` 等调用方不用动。

零依赖的中文检索为什么用 2-gram：中文没有空格，没有分词器时按"相邻两字"切
已经能覆盖绝大多数中文词组（"油烟"、"材料"、"营业执照"），且不需要词典。
"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

NOT_FOUND = "未找到该场景办事指南。"

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


class KnowledgeBase:
    """按场景加载办事指南，并支持按问题检索片段。"""

    def __init__(self, data_dir: Path):
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

    # ---------- 对外 ----------

    def scenarios(self) -> List[str]:
        """已加载指南的场景键（如 `restaurant` / `enterprise`）。"""
        return sorted(self._docs)

    def search(self, scenario_id: str, query: str, top_k: int = 3) -> List[Chunk]:
        """按问题检索片段，按相关度降序返回；没有命中就返回空列表。

        查询为空（没有可用的词）时直接返回空——"没问"不该等于"问什么都能匹配"。
        """
        entries = self._index.get(self._doc_key(scenario_id)) or []
        query_tokens = frozenset(tokenize(query))
        if not entries or not query_tokens:
            return []

        scored: List[Chunk] = []
        for entry in entries:
            score = self._score(query_tokens, entry)
            if score > 0:
                scored.append(Chunk(scenario_id=scenario_id, heading=entry.heading,
                                    text=entry.text, score=score))
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:max(1, int(top_k))]

    def retrieve(self, scenario_id: str, query: str = "", top_k: int = 3) -> str:
        """检索并拼成文本；查询为空或没有命中时**兜底返回整篇指南**。"""
        chunks = self.search(scenario_id, query, top_k=top_k)
        if chunks:
            return format_chunks(chunks)
        return self._docs.get(self._doc_key(scenario_id), NOT_FOUND)

    # ---------- 内部 ----------

    @staticmethod
    def _score(query_tokens: frozenset, entry: _Entry) -> float:
        title_hits = len(query_tokens & entry.heading_tokens)
        body_hits = len(query_tokens & entry.text_tokens)
        if not title_hits and not body_hits:
            return 0.0
        raw = TITLE_WEIGHT * title_hits + body_hits
        return raw / (1.0 + LENGTH_PENALTY * len(entry.text_tokens))

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
