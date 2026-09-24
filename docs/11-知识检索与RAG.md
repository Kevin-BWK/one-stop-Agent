# 11 知识检索与 RAG

> 状态：**已实现本地检索基线**（零依赖）；真实形态换成向量检索 / Embedding，**对外契约不变**。

## 1. 先修一个潜伏 bug：知识库此前是"摆设"

`KnowledgeBase` 在 5 处被构造、被存进 `MainAgent.knowledge` 与 `AgentService.knowledge`，
但 `retrieve()` **全项目 0 个调用点**——和 `SessionContext.history()` 一样，属于"接好了线但没人用"。

而且即使调用也会 miss：

```python
key = p.stem.replace("_guide", "")     # -> "restaurant"
# 调用方传的是 scenario["id"] -> "restaurant_open"
self._docs.get("restaurant_open")      # -> None -> "未找到该场景办事指南。"
```

现已用 `_doc_key()` 兼容：先按原样找，再退化到第一段（`restaurant_open` → `restaurant`）。

## 2. 对外契约

```python
KnowledgeBase(data_dir)

scenarios()                                  # 已加载的指南键，如 ["enterprise", "restaurant"]
search(scenario_id, query, top_k=3)          # -> [Chunk]，按相关度降序；无命中返回 []
retrieve(scenario_id, query="", top_k=3)     # -> str，拼成文本；无命中/无查询时兜底整篇
```

**契约稳定**的意思是：接真实 RAG 时只改 `app/knowledge/retriever.py` 内部，
调用方（`ConsultAgent`）一行不用动。

`retrieve` 的兜底行为是刻意保留的——旧调用方（`retrieve(scenario_id)` 只要整篇）
不必改就能继续工作；"没命中"也不等于"没答案"，退化成整篇比返回空更有用。

## 3. 切分：两级切，列表逐条拆

```
markdown
 └─ 按标题分节（标题存进 heading，参与打分但不重复进正文）
     └─ 按空行分段
         └─ 列表项逐行拆开
```

办事指南里的"事项 / 材料 / 条件"几乎都是列表，**每条独立成块**检索粒度才够细——
问"健康证"就该命中那一条，而不是把整个事项列表一起捞回来。

`restaurant_guide.md` 因此切成 10 块（标题 1 + 概述 1 + 事项 5 + 材料 1 + 条件标题 1 + 条件 3，
其中空行与列表边界决定具体条数）。

## 4. 打分：字符 2-gram + 标题加权

零依赖、不引第三方库、不需要词典。

| 环节 | 做法 | 为什么 |
| --- | --- | --- |
| 分词 | 中文取**相邻两字**（2-gram）；单字退化取该字；英文数字按词 | 中文无空格，没有分词器时 2-gram 已能覆盖绝大多数词组（油烟 / 材料 / 营业执照） |
| 打分 | `(3 × 标题命中数 + 正文命中数) / (1 + 0.05 × 正文词数)` | 词出现在标题上更相关；长度归一避免长段落仅因"字多"就压过短而精准的条目 |

两个场景的指南只有十几行，这个基线足够；语料变大后，把 `search()` 换成向量召回 + 重排即可。

## 5. 接线：咨询 Agent 真的用它

```python
ConsultAgent.answer(question, scenario, knowledge=None)
```

- 传 `knowledge` → 先 `search()` 取 top-3 片段：
  - **真实模式**：片段作为【办事指南节选】拼进 system prompt，让模型有依据作答；
  - **离线兜底**：片段附在回答末尾（`（来自办事指南）`），否则"接了知识库"在离线时看不出任何变化。
- 不传 `knowledge` → **行为与接入前完全一致**。
- 检索抛异常 → 静默跳过（检索是增强项，不该让"咨询"整个失败）。

调用链：

| 入口 | 传递路径 |
| --- | --- |
| CLI / Demo | `MainAgent._run` → `consult.answer(utterance, scenario, self.knowledge)` |
| 对话式 | `AgentService.handle_message` → `consult.answer(message, scenario, self.knowledge)` |
| 对话区提问 | `POST /api/ask` → `stream.answer_question(..., knowledge=service.knowledge)` |

## 6. 测试

```bash
python tests/test_knowledge.py
```

覆盖：两个场景加载、**场景 id → 指南文件的映射回归**、标题与列表切分、分词（2-gram / 单字 / 英文数字）、
命中质量（材料问题命中材料条、具体事实命中具体条、**跨场景不串**）、标题命中权重高于正文、
结果按分降序、`top_k` 边界、**空查询返回整篇**（向后兼容）、未命中兜底整篇、
异常输入不炸（None / 空 / emoji / 超长 / 特殊字符 / 非法 top_k），
以及**咨询 Agent 的接线**（离线回答带依据、真实模式进 system prompt、不传知识库时行为不变、知识库抛异常不影响咨询）。

## 7. 换成真实 RAG 时

| 环节 | 现在 | 真实形态 |
| --- | --- | --- |
| 切分 | 标题 / 段落 / 列表项 | 按 token 数窗口切 + 重叠 |
| 召回 | 2-gram 重叠打分 | Embedding（BGE 等）+ 向量库（Milvus / pgvector） |
| 重排 | 无 | Cross-Encoder 重排 / RRF 融合 |
| 存储 | 启动时读 `data/knowledge/*.md` | 文档入库 + 增量更新 |
| 契约 | `search` / `retrieve` | **不变** |
