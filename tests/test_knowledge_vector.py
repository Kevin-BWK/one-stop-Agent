"""向量检索测试：Embedding 客户端 / 向量召回 / RRF 融合 / 缓存 / 降级 / 契约不变。

**全部离线运行**（注入 FakeSession），不需要真实网络或密钥——用一个人造的
"概念 one-hot"假模型代替真实 Embedding，专门验证链路而不是模型能力：

- 请求形状对不对（OpenAI 兼容 `/embeddings` 的 model / input / 鉴权头）；
- 返回解析稳不稳（index 乱序归位、坏返回报错、4xx 不重试）；
- 语义召回是否真的补上了关键词的盲区（"排烟" → "油烟净化设施"）；
- 两路召回 RRF 融合、缓存复用、端点失败自动降级；
- 未配置时**行为与接入前完全一致**（契约不变）。

用法：python tests/test_knowledge_vector.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

# 本文件自带"假模型"，但要先把可能污染环境变量的项清掉（本机 .env 里若配了真端点，
# MOMA_EMBED_MIN_SCORE 之类会改变断言）；随后一律显式传参构造客户端。
for _name in ("MOMA_EMBED_MODEL", "MOMA_EMBED_API_BASE", "MOMA_EMBED_API_KEY",
              "MOMA_EMBED_MIN_SCORE", "MOMA_DISABLE_LIVE"):
    os.environ.pop(_name, None)

from app.knowledge.embedding import (EmbeddingClient, EmbeddingError, VectorIndex,
                                     cosine, load_vectors, save_vectors)
from app.knowledge.retriever import KnowledgeBase, rrf_fuse
from test_moma_client import FakeResponse, FakeSession

DATA = ROOT / "data" / "knowledge"

# 概念表：同一概念下的词互为"近义词"，字面可以完全不同。
# 用它模拟一个"懂语义"的向量模型——注意"油烟"与"排烟"同概念但字面不同，
# 关键词基线抓不到，向量能抓到，这正是要验证的差异。
CONCEPTS = (
    ("油烟", ("油烟", "排烟", "烟道")),
    ("材料", ("材料", "证件", "资料")),
    ("银行", ("银行", "开户", "对公账户")),
    ("健康证", ("健康证", "体检")),
    ("消防", ("消防", "灭火")),
    ("招牌", ("招牌", "店招")),
)


def _vector_of(text):
    """把文本映射成概念 one-hot 向量（确定性，便于断言）。"""
    return [1.0 if any(word in text for word in words) else 0.0
            for _name, words in CONCEPTS]


class FakeEmbeddingSession:
    """替代 requests 会话：按输入文本**现场算向量**，并记录调用参数。

    与 `FakeSession`（按顺序弹预设响应）不同：这里回复由输入决定，所以能验证
    "片段建索引"与"问题查询"两次调用各自的内容。
    """

    def __init__(self, fail_times=0):
        self.calls = []
        self.fail_times = fail_times

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ConnectionError("boom")
        inputs = list(json["input"])
        data = [{"index": index, "embedding": _vector_of(text)}
                for index, text in enumerate(inputs)]
        return FakeResponse(200, {"data": data})


def _live_client(session, **kwargs):
    """一个"已配置"的向量客户端（走 FakeSession，不联网）。"""
    return EmbeddingClient(api_base="https://embed.example.com/v1", api_key="k",
                           model="fake-emb", session=session, load_env=False,
                           sleep=lambda _seconds: None, **kwargs)


def _stub_client():
    """一个"未配置"的向量客户端（强制走关键词基线）。"""
    return EmbeddingClient(api_base="", api_key="", model="", load_env=False)


def _with_cache(fn):
    """给用例一个隔离的向量缓存目录，跑完清理。"""
    tmp = tempfile.mkdtemp()
    try:
        fn(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _scenario():
    import json
    with open(ROOT / "scenarios" / "restaurant_open.json", encoding="utf-8-sig") as f:
        return json.load(f)


# ---------- 基础算法 ----------

def test_cosine_basics():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0     # 维度不一致
    assert cosine([], [1.0]) == 0.0
    assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0           # 零向量
    assert 0.0 < cosine([1.0, 1.0], [1.0, 0.0]) < 1.0


def test_vector_index_orders_and_filters_by_threshold():
    index = VectorIndex([[1.0, 0.0], [0.8, 0.6], [0.0, 1.0]])
    hits = index.search([1.0, 0.0], top_k=3, min_score=0.5)
    assert [i for i, _score in hits] == [0, 1], hits        # 第三个低于阈值被丢
    assert hits[0][1] >= hits[1][1]
    assert index.search([1.0, 0.0], top_k=2, min_score=0.99) == [(0, 1.0)]
    assert index.search([1.0, 0.0], top_k=2, min_score=2.0) == []


def test_rrf_fuse_prefers_agreement():
    """两路都命中的片段，融合分数应高于只被一路命中的片段。"""
    fused = rrf_fuse([[(0, 0.9), (1, 0.8)], [(1, 0.7), (2, 0.6)]])
    assert fused[0][0] == 1, fused
    assert fused[0][1] > fused[1][1]
    assert rrf_fuse([]) == []


# ---------- Embedding 客户端 ----------

def test_embed_sends_openai_compatible_payload():
    session = FakeEmbeddingSession()
    client = _live_client(session)
    assert client.available is True and client.mode() == "live"
    vectors = client.embed(["油烟", "材料"])
    assert len(vectors) == 2 and len(vectors[0]) == len(CONCEPTS)
    call = session.calls[0]
    assert call["url"] == "https://embed.example.com/v1/embeddings"
    assert call["headers"]["Authorization"] == "Bearer k"
    assert call["json"]["model"] == "fake-emb"
    assert call["json"]["input"] == ["油烟", "材料"]
    assert call["timeout"] == 30.0
    assert client.embed([]) == []                            # 空输入不打请求
    assert len(session.calls) == 1


def test_parse_reorders_by_index():
    """OpenAI 兼容返回带 index 且不保证顺序，必须按 index 归位。"""
    session = FakeSession([FakeResponse(200, {"data": [
        {"index": 1, "embedding": [0.0, 1.0]},
        {"index": 0, "embedding": [1.0, 0.0]},
    ]})])
    assert _live_client(session).embed(["a", "b"]) == [[1.0, 0.0], [0.0, 1.0]]


def test_parse_rejects_bad_payload():
    for payload in ({"data": [{"index": 0}]}, {"data": []}, {}, {"data": "x"}):
        session = FakeSession([FakeResponse(200, payload)])
        try:
            _live_client(session).embed(["a"])
            raise AssertionError("应当抛出 EmbeddingError：" + str(payload))
        except EmbeddingError:
            pass


def test_4xx_fails_fast_without_retry():
    session = FakeSession([FakeResponse(401, text="unauthorized")])
    try:
        _live_client(session, max_retries=2).embed(["a"])
        raise AssertionError("4xx 应当直接失败")
    except EmbeddingError:
        pass
    assert len(session.calls) == 1, "4xx 不应重试"


def test_transient_error_retries_then_succeeds():
    """网络抖动要重试；重试成功后照常返回向量。"""
    session = FakeEmbeddingSession(fail_times=1)
    assert len(_live_client(session, max_retries=2).embed(["油烟"])) == 1
    assert len(session.calls) == 2, session.calls       # 一次失败 + 一次成功


def test_unavailable_client_refuses_and_reports():
    client = _stub_client()
    assert client.available is False and client.mode() == "stub"
    try:
        client.embed(["a"])
        raise AssertionError("未配置模型应当拒绝向量化")
    except EmbeddingError:
        pass


def test_describe_never_leaks_key():
    client = EmbeddingClient(api_base="https://x/v1", api_key="super-secret",
                             model="m", load_env=False)
    info = client.describe()
    assert "super-secret" not in str(info)
    assert info["model"] == "m" and info["mode"] == "live" and info["min_score"] == 0.2


# ---------- 向量缓存 ----------

def test_cache_roundtrip_and_invalidation():
    def run(tmp):
        path = Path(tmp) / "restaurant.json"
        assert save_vectors(path, "m", "fp1", [[1.0, 0.0]]) is True
        assert load_vectors(path, "m", "fp1") == [[1.0, 0.0]]
        assert load_vectors(path, "m", "fp2") is None      # 文本指纹变了
        assert load_vectors(path, "m2", "fp1") is None     # 模型变了
        assert load_vectors(Path(tmp) / "missing.json", "m", "fp1") is None
        (Path(tmp) / "broken.json").write_text("{ not json", encoding="utf-8")
        assert load_vectors(Path(tmp) / "broken.json", "m", "fp1") is None

    _with_cache(run)


# ---------- 检索：语义召回 / 融合 / 降级 / 契约 ----------

def test_vector_recall_covers_keyword_blind_spot():
    """核心用例：问"排烟"，关键词基线抓不到（字面不同），向量能命中"油烟净化设施"。"""
    def run(tmp):
        baseline = KnowledgeBase(DATA, embedder=_stub_client(), cache_dir=tmp)
        assert baseline.search("restaurant_open", "排烟") == []

        session = FakeEmbeddingSession()
        kb = KnowledgeBase(DATA, embedder=_live_client(session), cache_dir=tmp)
        hits = kb.search("restaurant_open", "排烟", top_k=1)
        assert hits and "油烟净化设施" in hits[0].text, hits

    _with_cache(run)


def test_results_sorted_by_score_desc_with_vector():
    def run(tmp):
        kb = KnowledgeBase(DATA, embedder=_live_client(FakeEmbeddingSession()), cache_dir=tmp)
        hits = kb.search("restaurant_open", "材料 油烟 消防", top_k=5)
        assert len(hits) >= 2, hits
        scores = [chunk.score for chunk in hits]
        assert scores == sorted(scores, reverse=True), scores

    _with_cache(run)


def test_vector_cache_avoids_reembedding_on_restart():
    def run(tmp):
        first = FakeEmbeddingSession()
        KnowledgeBase(DATA, embedder=_live_client(first), cache_dir=tmp).search(
            "restaurant_open", "油烟", top_k=1)
        # 首次：建索引一次（批量）+ 查询一次
        assert len(first.calls) == 2, len(first.calls)

        second = FakeEmbeddingSession()
        KnowledgeBase(DATA, embedder=_live_client(second), cache_dir=tmp).search(
            "restaurant_open", "油烟", top_k=1)
        # 第二次：索引来自磁盘缓存，只剩查询那一次
        assert len(second.calls) == 1, len(second.calls)

    _with_cache(run)


def test_vector_failure_degrades_to_baseline_without_retry_storm():
    def run(tmp):
        session = FakeEmbeddingSession(fail_times=99)
        kb = KnowledgeBase(DATA, embedder=_live_client(session, max_retries=0), cache_dir=tmp)
        # 基线能命中的问题：向量端点挂了也应照常返回
        hits = kb.search("restaurant_open", "油烟", top_k=1)
        assert hits and "油烟净化设施" in hits[0].text, hits
        assert len(session.calls) == 1, session.calls
        # 已标记失败：本进程内不再重试（否则每次咨询都卡一次超时）
        kb.search("restaurant_open", "材料", top_k=1)
        assert len(session.calls) == 1, session.calls

    _with_cache(run)


def test_unconfigured_kb_keeps_old_behavior():
    """契约不变：未启用向量时，行为与接入前完全一致。"""
    def run(tmp):
        stub = _stub_client()
        kb = KnowledgeBase(DATA, embedder=stub, cache_dir=tmp)
        assert stub.available is False
        assert kb.search("restaurant_open", "排烟") == []           # 向量才有的能力
        hits = kb.search("restaurant_open", "油烟", top_k=1)
        assert hits and "油烟净化设施" in hits[0].text, hits
        assert kb.search("restaurant_open", "") == []
        assert kb.search("nope_open", "材料") == []

    _with_cache(run)


def test_consult_agent_uses_vector_knowledge():
    """接线：咨询 Agent 从 KnowledgeBase 拿到的片段应包含向量召回的语义命中。"""
    from app.agents.consult_agent import ConsultAgent
    from app.moma.client import MoMAClient
    from app.moma.context import SessionContext

    def run(tmp):
        kb = KnowledgeBase(DATA, embedder=_live_client(FakeEmbeddingSession()), cache_dir=tmp)
        agent = ConsultAgent(MoMAClient(api_base="", api_key=""), SessionContext())
        reply = agent.answer("排烟怎么处理", _scenario(), kb)
        assert "油烟净化设施" in reply, reply
        assert "来自办事指南" in reply, reply

    _with_cache(run)


def main():
    test_cosine_basics()
    test_vector_index_orders_and_filters_by_threshold()
    test_rrf_fuse_prefers_agreement()
    test_embed_sends_openai_compatible_payload()
    test_parse_reorders_by_index()
    test_parse_rejects_bad_payload()
    test_4xx_fails_fast_without_retry()
    test_transient_error_retries_then_succeeds()
    test_unavailable_client_refuses_and_reports()
    test_describe_never_leaks_key()
    test_cache_roundtrip_and_invalidation()
    test_vector_recall_covers_keyword_blind_spot()
    test_results_sorted_by_score_desc_with_vector()
    test_vector_cache_avoids_reembedding_on_restart()
    test_vector_failure_degrades_to_baseline_without_retry_storm()
    test_unconfigured_kb_keeps_old_behavior()
    test_consult_agent_uses_vector_knowledge()
    print("KNOWLEDGE VECTOR TESTS PASSED")


if __name__ == "__main__":
    main()
