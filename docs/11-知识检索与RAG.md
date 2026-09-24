# 11 知识检索与 RAG

> 状态：**已实现 本地检索基线（零依赖）+ 向量检索（可选，配 `MOMA_EMBED_MODEL` 即启用）**；
> 两路结果用 RRF 融合，向量不可用时自动降级基线，**对外契约自始至终不变**（见第 7 节）。

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

**契约稳定**的意思是：换检索实现时只动 `app/knowledge/`（`retriever.py` + `embedding.py`），
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

## 7. 向量检索（可选通道，已实现）

关键词基线解决的是"**字面能对上**"：问"油烟"能找到"油烟净化设施"。
但问"排烟"就找不到了——语义相近、字面不同，正是向量检索的用武之地。
现已在**不改对外契约**的前提下接入（`app/knowledge/embedding.py`）。

### 7.1 开关：配了才启用

| 环境变量 | 说明 |
| --- | --- |
| `MOMA_EMBED_MODEL` | 向量模型名，**配了它才启用向量检索**（如 `bge-large-zh`） |
| `MOMA_EMBED_API_BASE` | 向量端点，默认回退 `MOMA_MAIN_API_BASE` / `MOMA_API_BASE` |
| `MOMA_EMBED_API_KEY` | 向量密钥，默认回退 `MOMA_MAIN_API_KEY` / `MOMA_API_KEY` |
| `MOMA_EMBED_MIN_SCORE` | 余弦相似度下限，低于它的召回直接丢弃，默认 `0.2` |

- 调用的是 OpenAI 兼容的 `POST {API_BASE}/embeddings`，**与 MoMA 同一套地址即可**；
- 未配置时 `EmbeddingClient.available` 为 `False`，`search()` 自动走关键词基线，
  行为与接入前一致（既有测试原样通过）；
- `MOMA_DISABLE_LIVE=1` 同样能强制停用（测试 / 离线演示），与 `MoMAClient` 共用一个总闸。

### 7.2 两路召回 + RRF 融合

```
问题 ──┬─ 关键词基线召回（2-gram，永远跑）──┐
       └─ 向量召回（余弦，配了才跑）     ──┴─ RRF 融合 → top_k
```

不同通道的分数（余弦相似度 vs 关键词权重）量纲不同，**直接相加没有意义**；
RRF 只看"排第几"：`score(d) = Σ 1 / (k + rank(d))`，
天然偏好**两路都命中**的片段。

### 7.3 缓存与降级

- **向量缓存**：片段向量落盘到 `data/runtime/knowledge_vectors/{场景}.json`，
  带模型名 + 文本指纹；模型换了或指南改了自动失效，重启不再重复调用端点；
- **惰性构建**：首次检索该场景时才建索引，不拖慢服务启动；
- **自动降级**：端点超时 / 报错 → 静默回退关键词基线，且**本进程内不再重试**
  （否则每次咨询都要卡一次超时）。检索是增强项，不该让"咨询"跟着失败；
- **密钥安全**：`EmbeddingClient.describe()` 从不包含密钥。

### 7.4 验证

```bash
python tests/test_knowledge_vector.py
```

用一个人造的"概念 one-hot"假模型（**离线、不联网**）验证**链路**而非模型能力：
请求形状（`/embeddings` 的 model / input / 鉴权头）、index 乱序归位、坏返回报错、
4xx 不重试 / 网络抖动重试、**"排烟"→"油烟净化设施"的语义召回**、
RRF 偏好一致命中、缓存复用（重启不重算）、端点失败降级且无重试风暴，
以及**未配置时契约逐字节不变**。

## 8. 再往后的演进

| 环节 | 现在 | 再往后 |
| --- | --- | --- |
| 切分 | 标题 / 段落 / 列表项 | 按 token 数窗口切 + 重叠 |
| 召回 | 关键词 2-gram + 向量（可选） | 纯向量 + 向量库（Milvus / pgvector） |
| 重排 | RRF 融合 | Cross-Encoder 精排 / RRF 叠加 |
| 存储 | 启动读 `data/knowledge/*.md` + 向量落盘缓存 | 文档入库 + 增量更新 |
| 契约 | `search` / `retrieve` | **不变** |
