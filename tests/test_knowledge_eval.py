"""知识检索的**评估回归集**：固定一组标注问题，量化检索质量并设回归门槛。

为什么要有它：
- `test_knowledge.py` / `test_knowledge_vector.py` 验的是**行为**（切分对不对、
  降级会不会炸、融合有没有生效），回答不了"改完之后检索是变好还是变坏"；
- 这里把 (场景, 问题) → 期望命中的片段固定下来，算 recall@1 / recall@k / MRR，
  并设**门槛断言**——改动切分、打分、融合策略后跑一下就知道有没有退步。

默认**离线**评估关键词基线（确定性、无需密钥、可重复）；设 `KNOWLEDGE_EVAL_LIVE=1`
且本机配了 `MOMA_EMBED_MODEL` 时，追加跑一遍向量通道做对比。

用法：python tests/test_knowledge_eval.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LIVE = os.environ.get("KNOWLEDGE_EVAL_LIVE") == "1"
if not LIVE:
    # 默认离线：关键词基线是确定性的，评估结果可重复（不会被本机 .env 带偏）
    os.environ.setdefault("MOMA_DISABLE_LIVE", "1")

from app.knowledge.embedding import EmbeddingClient
from app.knowledge.retriever import KnowledgeBase

DATA = ROOT / "data" / "knowledge"
CACHE = ROOT / "data" / "runtime" / "knowledge_eval_cache"

# 回归门槛：当前基线在这组用例上表现良好，留一点余量；
# 低于它就说明检索质量退步了，需要查是切分、打分还是融合的问题。
MIN_RECALL_AT_1 = 0.9
MIN_RECALL_AT_3 = 1.0
MIN_MRR = 0.9

# (场景 id, 用户问题, 期望命中的片段里应出现的关键内容, 用例说明)
CASES = (
    ("restaurant_open", "需要准备什么材料", "基础材料", "材料问题应命中材料条"),
    ("restaurant_open", "油烟怎么处理", "油烟净化设施", "条件问题应命中具体条件"),
    ("restaurant_open", "生食冷食怎么办", "专间", "条件问题应命中具体条件"),
    ("restaurant_open", "健康证", "健康证", "事项名应命中该事项"),
    ("restaurant_open", "消防安全检查", "消防安全检查", "事项名应命中该事项"),
    ("restaurant_open", "要设置招牌", "招牌", "事项名应命中该事项"),
    ("restaurant_open", "营业执照去哪领", "营业执照", "事项名应命中该事项"),
    ("enterprise_open", "银行开户预约", "银行开户", "企业独有事项"),
    ("enterprise_open", "税务登记", "税务登记", "事项名应命中该事项"),
    ("enterprise_open", "社保登记", "社保登记", "事项名应命中该事项"),
    ("enterprise_open", "公章怎么刻", "公章刻制", "事项名应命中该事项"),
    ("enterprise_open", "要交什么材料", "基础材料", "材料问题应命中材料条"),
)


def _stub_embedder():
    """强制关键词基线：显式空配置 + 不读 .env，评估结果与机器环境无关。"""
    return EmbeddingClient(api_base="", api_key="", model="", load_env=False)


def evaluate(kb, top_k=3):
    """跑一遍用例，返回指标与逐条明细。"""
    total = len(CASES)
    hit1 = hitk = 0
    reciprocal = 0.0
    detail = []
    for scenario, query, expect, note in CASES:
        chunks = kb.search(scenario, query, top_k=top_k)
        rank = 0
        for index, chunk in enumerate(chunks, start=1):
            if expect in chunk.text:
                rank = index
                break
        hit1 += 1 if rank == 1 else 0
        hitk += 1 if rank else 0
        reciprocal += (1.0 / rank) if rank else 0.0
        detail.append((scenario, query, expect, rank, note))
    return {
        "n": total,
        "recall@1": hit1 / total,
        "recall@k": hitk / total,
        "mrr": reciprocal / total,
        "top_k": top_k,
    }, detail


def _report(title, metrics, detail):
    print("\n=== " + title + " ===")
    print("用例 " + str(metrics["n"])
          + " ｜ recall@1 = " + format(metrics["recall@1"], ".3f")
          + " ｜ recall@" + str(metrics["top_k"]) + " = " + format(metrics["recall@k"], ".3f")
          + " ｜ MRR = " + format(metrics["mrr"], ".3f"))
    for scenario, query, expect, rank, note in detail:
        mark = ("命中 top" + str(rank)) if rank else "未命中"
        print("  [" + mark + "] " + scenario + " ｜ " + query
              + " ｜ 期望含「" + expect + "」 ｜ " + note)


def test_keyword_baseline_meets_threshold():
    """关键词基线（默认离线）：指标必须不低于门槛，否则视为检索质量退步。"""
    kb = KnowledgeBase(DATA, embedder=_stub_embedder(), cache_dir=CACHE)
    metrics, detail = evaluate(kb)
    _report("关键词基线", metrics, detail)
    assert metrics["recall@1"] >= MIN_RECALL_AT_1, metrics
    assert metrics["recall@k"] >= MIN_RECALL_AT_3, metrics
    assert metrics["mrr"] >= MIN_MRR, metrics


def test_live_vector_channel_if_configured():
    """可选：本机配了真实向量模型时，追加跑一遍做对比（默认跳过，不联网）。"""
    if not LIVE:
        print("\n（跳过真实向量对比：设 KNOWLEDGE_EVAL_LIVE=1 且配好 MOMA_EMBED_MODEL 可启用）")
        return
    client = EmbeddingClient()
    if not client.available:
        print("\n（跳过真实向量对比：未配置 MOMA_EMBED_MODEL）")
        return
    kb = KnowledgeBase(DATA, embedder=client)
    metrics, detail = evaluate(kb)
    _report("真实向量 + RRF 融合", metrics, detail)


def main():
    test_keyword_baseline_meets_threshold()
    test_live_vector_channel_if_configured()
    print("\nKNOWLEDGE EVAL PASSED")


if __name__ == "__main__":
    main()
