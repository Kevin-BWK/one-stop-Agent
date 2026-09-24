"""知识检索测试：切分 / 分词 / 打分 / 场景映射 / 兜底 / 与咨询 Agent 的接线。

检索是**零依赖的本地基线**（见 `app/knowledge/retriever.py`），本文件既测
"检索结果对不对"，也测"边界输入不炸"，以及"咨询 Agent 真的用上了它"。

用法：python tests/test_knowledge.py
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

# 本文件测的是**零依赖的关键词基线**：显式停用真实调用，避免本机 .env 配了
# 向量模型 / 端点时把离线断言带偏（向量检索另见 tests/test_knowledge_vector.py）。
os.environ.setdefault("MOMA_DISABLE_LIVE", "1")

from app.knowledge.retriever import (NOT_FOUND, KnowledgeBase, _Entry,
                                     format_chunks, split_chunks, tokenize)

KB = KnowledgeBase(ROOT / "data" / "knowledge")


def _scenario(scenario_id):
    with open(ROOT / "scenarios" / (scenario_id + ".json"), encoding="utf-8-sig") as f:
        return json.load(f)


def _guide_text(scenario_key):
    return (ROOT / "data" / "knowledge" / (scenario_key + "_guide.md")).read_text(encoding="utf-8")


# ---------- 加载与场景映射 ----------

def test_loads_both_guides():
    assert KB.scenarios() == ["enterprise", "restaurant"], KB.scenarios()


def test_scenario_id_maps_to_guide():
    """回归：场景 id 是 `restaurant_open`，而文件名是 `restaurant_guide.md`（键 `restaurant`）。

    早先 `retrieve` 直接按场景 id 取，永远 miss —— 只因为没人调用才没暴露。
    """
    assert KB._doc_key("restaurant_open") == "restaurant"
    assert KB._doc_key("enterprise_open") == "enterprise"
    assert KB._doc_key("restaurant") == "restaurant"      # 短键也认
    assert KB._doc_key("nope") == ""
    assert KB.retrieve("restaurant_open") != NOT_FOUND
    assert KB.retrieve("enterprise_open") != NOT_FOUND


def test_unknown_scenario_returns_not_found():
    assert KB.retrieve("nope_open") == NOT_FOUND
    assert KB.search("nope_open", "材料") == []


# ---------- 切分与分词 ----------

def test_split_chunks_keeps_heading_and_splits_list_items():
    chunks = split_chunks(_guide_text("restaurant"))
    headings = {heading for heading, _ in chunks}
    assert headings == {"开办餐饮店办事指南"}, headings

    texts = [text for _, text in chunks]
    # 段落成块
    assert "所需基础材料：身份证、经营场所证明、平面布局图。" in texts
    # 列表逐条拆开（5 个事项各自独立，检索粒度才够细）
    assert "从业人员健康证（卫健）。" in texts
    assert len([text for text in texts if "营业执照" in text]) == 1, texts
    # 标题不重复进正文
    assert all("办事指南" not in text for text in texts), texts


def test_tokenize_bigrams_and_words():
    tokens = tokenize("油烟 ABC-123")
    assert "油烟" in tokens
    assert "abc" in tokens and "123" in tokens
    assert tokenize("材") == ["材"]        # 单字退化为 1-gram，否则压根没有词
    assert tokenize("") == []
    assert tokenize(None) == []


# ---------- 检索结果 ----------

def test_materials_question_hits_the_materials_chunk():
    hits = KB.search("restaurant_open", "需要什么材料", top_k=1)
    assert len(hits) == 1, hits
    assert "基础材料" in hits[0].text, hits[0].text


def test_specific_fact_is_found():
    hits = KB.search("restaurant_open", "油烟", top_k=1)
    assert len(hits) == 1, hits
    assert "油烟净化设施" in hits[0].text, hits[0].text


def test_enterprise_fact_is_found():
    hits = KB.search("enterprise_open", "营业执照", top_k=1)
    assert hits and "营业执照" in hits[0].text, hits


def test_query_is_scoped_to_scenario():
    """餐饮店的指南里没有"银行开户"，在企业场景里才有。"""
    assert KB.search("restaurant_open", "银行开户预约") == []
    hits = KB.search("enterprise_open", "银行开户")
    assert hits and "银行开户" in hits[0].text, hits


def test_heading_hits_outweigh_body_hits():
    """同一个词，出现在标题上比出现在正文里更相关。"""
    query = frozenset(tokenize("材料"))
    in_heading = _Entry(heading="材料", text="无关内容。",
                        heading_tokens=frozenset(tokenize("材料")),
                        text_tokens=frozenset(tokenize("无关内容。")))
    in_body = _Entry(heading="无关", text="材料",
                     heading_tokens=frozenset(tokenize("无关")),
                     text_tokens=frozenset(tokenize("材料")))
    assert KB._score(query, in_heading) > KB._score(query, in_body)


def test_results_are_sorted_by_score_desc():
    hits = KB.search("restaurant_open", "材料 消防 油烟", top_k=5)
    assert len(hits) >= 2, hits
    scores = [chunk.score for chunk in hits]
    assert scores == sorted(scores, reverse=True), scores


def test_top_k_limits_results():
    assert len(KB.search("restaurant_open", "办理", top_k=2)) <= 2
    assert len(KB.search("restaurant_open", "办理", top_k=1)) == 1
    # top_k 给 0 或负数时至少返回 1 条，避免调用方拿到空
    assert len(KB.search("restaurant_open", "办理", top_k=0)) == 1


def test_format_chunks_dedupes():
    chunks = KB.search("restaurant_open", "材料", top_k=3)
    text = format_chunks(chunks)
    assert text and "材料" in text
    assert format_chunks([]) == ""


# ---------- 兜底与健壮性 ----------

def test_empty_query_returns_whole_doc():
    """没问问题就返回整篇——保持旧 `retrieve(scenario_id)` 调用的行为。"""
    whole = KB.retrieve("restaurant_open")
    assert "个体工商户设立登记" in whole and "油烟净化设施" in whole
    assert KB.search("restaurant_open", "") == []
    assert KB.search("restaurant_open", "   ") == []


def test_unmatched_query_falls_back_to_whole_doc():
    """"没命中"不等于"没答案"：退化成整篇，让调用方仍有内容可用。"""
    assert KB.search("restaurant_open", "zzzzz") == []
    assert KB.retrieve("restaurant_open", "zzzzz") != NOT_FOUND


def test_never_raises_on_weird_input():
    for query in (None, "", "   ", "🙂🙂", "a" * 5000, "'''\"\"\";;--", "％＃＠", "\n\n"):
        KB.search("restaurant_open", query)
        KB.retrieve("restaurant_open", query)
    # 场景 id 异常也不能炸
    assert KB.retrieve(None) == NOT_FOUND
    assert KB.search(None, "材料") == []
    assert KB.retrieve("restaurant_open", "材料", top_k=-3)


# ---------- 与咨询 Agent 的接线（关键：不能"实现了没人调"）----------

def test_consult_agent_appends_guide_to_offline_reply():
    """离线兜底也要带检索依据，否则"接了知识库"在离线时看不出任何变化。"""
    from app.agents.consult_agent import ConsultAgent
    from app.moma.client import MoMAClient
    from app.moma.context import SessionContext

    agent = ConsultAgent(MoMAClient(api_base="", api_key=""), SessionContext())
    reply = agent.answer("油烟怎么处理", _scenario("restaurant_open"), KB)
    assert "油烟净化设施" in reply, reply
    assert "来自办事指南" in reply, reply


def test_consult_agent_feeds_guide_into_model_messages():
    """真实模式：检索到的片段要进 system prompt；不传知识库时行为不变。"""
    from app.agents.consult_agent import ConsultAgent
    from app.moma.client import MoMAClient
    from app.moma.context import SessionContext
    from test_moma_client import FakeSession, no_sleep, ok

    scenario = _scenario("restaurant_open")

    session = FakeSession([ok("模型回答")])
    agent = ConsultAgent(
        MoMAClient(api_base="https://x/v1", api_key="k", session=session, sleep=no_sleep),
        SessionContext(),
    )
    assert agent.answer("油烟怎么处理", scenario, KB) == "模型回答"
    system = session.calls[0]["json"]["messages"][0]["content"]
    assert "办事指南节选" in system, system
    assert "油烟净化设施" in system, system

    # 不传 knowledge -> 与接入前完全一致（system 里没有节选）
    session2 = FakeSession([ok("模型回答")])
    agent2 = ConsultAgent(
        MoMAClient(api_base="https://x/v1", api_key="k", session=session2, sleep=no_sleep),
        SessionContext(),
    )
    agent2.answer("油烟怎么处理", scenario)
    assert "办事指南节选" not in session2.calls[0]["json"]["messages"][0]["content"]


def test_consult_agent_survives_broken_knowledge():
    """检索是增强项：知识库抛异常也不该让"咨询"整个失败。"""
    from app.agents.consult_agent import ConsultAgent
    from app.moma.client import MoMAClient
    from app.moma.context import SessionContext

    class BrokenKnowledge:
        def search(self, *args, **kwargs):
            raise RuntimeError("知识库炸了")

    agent = ConsultAgent(MoMAClient(api_base="", api_key=""), SessionContext())
    reply = agent.answer("需要什么材料", _scenario("restaurant_open"), BrokenKnowledge())
    assert reply and "材料" in reply, reply


# ---------- 检索 query 的上下文（省略句也能检索到，见 docs/11）----------

def test_search_query_brings_recent_user_turns():
    """把最近几轮**用户提问**拼进检索 query；助手的回答不掺进来。"""
    from app.agents.consult_agent import ConsultAgent
    from app.moma.client import MoMAClient
    from app.moma.context import SessionContext

    context = SessionContext()
    context.add_history("user", "我想开一家牛肉面馆")
    context.add_history("assistant", "好的，我来帮您办。")
    agent = ConsultAgent(MoMAClient(api_base="", api_key=""), context)

    query = agent._search_query("那要什么材料")
    assert query == "我想开一家牛肉面馆 那要什么材料", query
    assert "好的，我来帮您办" not in query, query      # 助手的回答不参与检索

    # 只带最近几轮：更早的历史被挤掉，避免 query 越滚越长
    for index in range(10):
        context.add_history("user", "旧问题" + str(index))
    query = agent._search_query("新问题")
    assert query == "旧问题8 旧问题9 新问题", query


def test_search_query_without_context_is_plain_question():
    """没有历史时行为与接入前一致：检索 query 就是原问题。"""
    from app.agents.consult_agent import ConsultAgent
    from app.moma.client import MoMAClient
    from app.moma.context import SessionContext

    agent = ConsultAgent(MoMAClient(api_base="", api_key=""), SessionContext())
    assert agent._search_query("需要什么材料") == "需要什么材料"
    assert agent._search_query("") == ""
    assert agent._search_query(None) == ""


def test_omitted_question_retrieves_with_context():
    """省略句（"那这个呢"）单看检索不到，靠上文才能命中——这就是带上下文的用处。"""
    from app.agents.consult_agent import ConsultAgent
    from app.moma.client import MoMAClient
    from app.moma.context import SessionContext

    scenario = _scenario("restaurant_open")

    bare = ConsultAgent(MoMAClient(api_base="", api_key=""), SessionContext())
    assert "油烟净化设施" not in bare.answer("那这个呢", scenario, KB)

    context = SessionContext()
    context.add_history("user", "油烟净化设施要装吗")
    context.add_history("assistant", "经营热食需要安装。")
    with_context = ConsultAgent(MoMAClient(api_base="", api_key=""), context)
    assert "油烟净化设施" in with_context.answer("那这个呢", scenario, KB)


if __name__ == "__main__":
    test_loads_both_guides()
    test_scenario_id_maps_to_guide()
    test_unknown_scenario_returns_not_found()
    test_split_chunks_keeps_heading_and_splits_list_items()
    test_tokenize_bigrams_and_words()
    test_materials_question_hits_the_materials_chunk()
    test_specific_fact_is_found()
    test_enterprise_fact_is_found()
    test_query_is_scoped_to_scenario()
    test_heading_hits_outweigh_body_hits()
    test_results_are_sorted_by_score_desc()
    test_top_k_limits_results()
    test_format_chunks_dedupes()
    test_empty_query_returns_whole_doc()
    test_unmatched_query_falls_back_to_whole_doc()
    test_never_raises_on_weird_input()
    test_consult_agent_appends_guide_to_offline_reply()
    test_consult_agent_feeds_guide_into_model_messages()
    test_consult_agent_survives_broken_knowledge()
    test_search_query_brings_recent_user_turns()
    test_search_query_without_context_is_plain_question()
    test_omitted_question_retrieves_with_context()
    print("KNOWLEDGE TESTS PASSED")
