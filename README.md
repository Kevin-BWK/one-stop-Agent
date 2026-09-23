# 一件事·一次办 智能体（One-Stop Agent）

基于移动云 **MoMA** 平台，面向“高效办成一件事”政务场景的多 Agent 应用。内置**开办企业**与**开办餐饮店**两个业务场景，二者共用同一套 Agent 编排框架，业务差异全部由 `scenarios/*.json` 配置驱动——新增“一件事”只需加一份场景配置，不改代码。

## 项目概述

- 一个入口、一次填写、并联办理、一次出件。
- 两个业务场景（企业 / 餐饮店）共享编排框架，配置即业务。
- 骨架阶段零第三方依赖，`python run_demo.py` 即可跑通最小闭环。

## 架构概览

```
接入层   uni-app 前端（Vue 3 + TypeScript）：App（成品） / H5（测试用）
编排层   MoMA 多 Agent 编排（主 Agent + 子 Agent 群，含各部门事项 Agent）
能力层   MoMA：多模型调度 · 智能路由 · 上下文管理 · RAG · 工具调用
模型层   九天大模型 + 生态模型（DeepSeek / Qwen / GLM / Qwen-VL）
数据层   知识库 · 材料模板 · 用户档案 · 会话记忆 · 向量库
集成层   政务系统对接（模拟）：市场监管 / 税务 / 消防 / 城管 / 卫健
安全层   RBAC · 数据脱敏 · 审计日志 · 备案合规
```

| 层 | 本仓库对应实现 |
| --- | --- |
| 编排层 | `app/orchestrator/`（主 Agent + 意图路由） |
| 能力层 | `app/moma/`、`app/knowledge/` |
| 数据层 | `data/knowledge/`、`app/storage/`、`app/models/` |
| 集成层 | `app/mock_gov/`（Mock） |
| 安全层 | 遵循项目安全红线（RBAC / 脱敏 / 审计 / 备案合规） |

## 多 Agent 编排

| Agent | 职责 | 调度模型 |
| --- | --- | --- |
| 主 Agent | 意图识别、任务拆解、上下文、结果汇总 | 编排 |
| 咨询 Agent | 解答流程与材料问题 | deepseek-r1 |
| 信息采集 Agent | 多轮采集，生成结构化表单 | qwen-turbo |
| 条件判定 Agent | 按条件产出事项 + 材料清单（智能路由核心） | 规则引擎 |
| 材料核验 Agent | 材料齐全 / 合规校验 | qwen-vl |
| 部门事项 Agent | 办理单个并联事项，办结后回调主 Agent 更新进度（按事项动态创建） | 规则引擎 |
| 进度跟踪 Agent | 办理流程节点 + 并联办理进度查询 | 规则引擎 |

编排闭环：

```
意图路由 → 咨询 → 信息采集 → 条件判定 → 材料核验 → 并联提交 → 各部门事项办理 → 进度查询
```

## 目录结构

```
one-stop-agent/
├── run_demo.py              # 最小可运行演示入口（含进度查询）
├── scenarios/               # 场景配置（事项、字段、条件规则）
├── data/knowledge/          # 办事指南知识库
├── data/runtime/            # 运行时办理单（进度查询持久化，自动生成）
├── docs/                    # 设计文档
├── server/                  # FastAPI 服务层（多轮会话）
├── app/
│   ├── moma/                # MoMA 客户端 + 上下文管理
│   ├── agents/              # 子 Agent（咨询/采集/判定/核验/部门事项/进度）
│   ├── orchestrator/        # 主 Agent 编排 + 意图路由 + 办理流程进度 + 编排事件（flow.py / events.py）
│   ├── knowledge/           # 知识检索
│   ├── mock_gov/            # 政务系统 Mock（并联办理与状态推进）
│   ├── models/              # 数据模型
│   └── storage/             # 存储（内存 / JSON 文件）
└── tests/                   # 冒烟测试
```

## 技术栈

| 层级 | 当前骨架（零依赖） | 目标 / 生产形态 |
| --- | --- | --- |
| 语言 / 运行 | Python 3.10+ 标准库（dataclass） | Python + FastAPI + uvicorn |
| 平台底座 | `MoMAClient`（桩 / 真实可切换） | 移动云 MoMA 多模型调度 / 路由 / 上下文 |
| 模型 | deepseek-r1 / qwen-turbo / qwen-vl / 规则引擎（桩） | 九天大模型 + DeepSeek / Qwen / GLM / Qwen-VL |
| 知识检索 | 整篇 markdown 返回 | 向量库 + Embedding（BGE 等）RAG |
| 上下文 / 数据 | `SessionContext` / `InMemoryRepo` 内存 | Redis + PostgreSQL / MySQL |
| 政务集成 | `MockGovServices` 本地模拟 | 市场监管 / 税务 / 消防 / 城管 / 卫健接口 |
| 前端 | 暂未实现（预留，设计见「前端交互设计」） | uni-app（Vue 3 + TypeScript）：App（成品） / H5（测试用） + 事件推送（App: WebSocket / H5: SSE） |

## 快速开始

```bash
# 跑通两个场景的最小闭环（零第三方依赖）
python run_demo.py                # 两个场景都跑，并演示并联办理进度推进
python run_demo.py restaurant     # 只跑餐饮店
python run_demo.py enterprise     # 只跑企业

# 按办理单号查询办理进度看板
python run_demo.py --query YJS0001

# 冒烟测试（无需 pytest）
python tests/test_flow.py
python tests/test_moma_client.py   # MoMA 客户端（离线）
python tests/test_server_smoke.py   # 服务层多轮会话闭环（零第三方依赖）

# 启动 API（需先 pip install -r requirements.txt）
uvicorn server.main:app --reload
```

- 要求 Python 3.10+（已在 3.12 验证），核心运行仅用标准库。
- Windows 若无 `python` 命令，可改用 `py` 启动器，如 `py -3 run_demo.py`。
- 接入 Web 前端 / 真实 MoMA 时再安装：`pip install -r requirements.txt`。

## 桩实现 → 真实接入

| 模块 | 当前实现 | 真实接入 |
| --- | --- | --- |
| `app/moma/client.py` | ✅ 已支持真实 API（未配置环境变量时回退桩） | 配置 `MOMA_API_BASE` / `MOMA_API_KEY` 即启用 |
| `app/knowledge/retriever.py` | 整篇返回 markdown 指南 | 向量检索 / RAG |
| `app/mock_gov/services.py` | 本地内存模拟并联办理 | 对接真实政务系统 |
| `app/storage/repo.py` | 内存 / JSON 文件（跨进程查询进度） | PostgreSQL / MySQL |

## 前端交互设计（uni-app：Vue 3 + TypeScript，事件推送）

前端形态为 **uni-app（Vue 3 + TypeScript）**：**最终成品为 App**，H5 仅用于开发调试，微信小程序已弃用。
进度看板要反映**真实办理进度**，因此不做“回放动画”（对办事人无意义），
也不做前端轮询（空转多、有延迟），而是由后端**服务端推送**：

```
前端 uni-app（App 成品 / H5 测试）          后端 FastAPI + 编排层
        |  POST /apply  ------------------->  主 Agent 启动编排
        |                                       节点完成 / 部门子 Agent 回调
        |  <-- event: flow_node   {node, done, total}
        |  <-- event: item_done   {item}
        |  <-- event: finished    {case_id, flow}
        |  流结束
```

- **进度是真实办理进度**：后端每完成一个节点 / 每收到一次部门子 Agent 回调，立即推一条事件，看板增量刷新——进度零延迟、无空转。
- **动态表单**：表单区消费 `scenarios/*.json` 的 `collect_fields` 自动渲染控件，新增“一件事”不改前端。
- **事件负载复用现有结构**：`flow_node` 取 `FlowProgress.snapshot()`，`item_done` 取部门回调结果，`case_created` / `finished` 取 `CaseRecord`。

事件与前端处理的对应：

| 事件 | 负载 | 前端处理 |
| --- | --- | --- |
| `message` | `stage`, `text` | 聊天区追加气泡 |
| `flow_node` | `key/name/status/detail` + `done/total` | 看板更新节点 + 进度条 |
| `case_created` | `case_id` / `items` / `materials` | 显示办理单号与事项清单 |
| `item_done` | 部门 / 事项 / 状态 / 出件 | 看板更新并联事项 |
| `finished` | 最终 `flow` / `item_status` | 结束态 |
| `error` | `code` / `message` | 提示并恢复界面 |

> 说明：**前端尚未实现**；其依赖的编排事件出口（`MainAgent.run / query` 的可选 `on_event` 回调，`Event.to_dict()` 可直接序列化为事件 JSON）已就绪，服务层推送即可（App: WebSocket；H5: SSE）。完整的工程结构、事件契约与接口定义见 `docs/07-前端交互设计.md`。

## MoMA 真实接入

`app/moma/client.py` 支持“桩 / 真实”一键切换，业务代码无需改动：

- **未配置环境变量** → 桩模式：本地模拟回复，Demo 与单测可离线运行。
- **配置环境变量** → 真实模式：调用 OpenAI 兼容接口 `POST {MOMA_API_BASE}/chat/completions`，5xx / 429 自动重试，失败时可用本地回退。

| 环境变量 | 说明 |
| --- | --- |
| `MOMA_API_BASE` | 服务地址，例如 `https://moma.example.com/v1` |
| `MOMA_API_KEY` | 访问密钥（Bearer） |
| `MOMA_TIMEOUT` | 超时秒数，默认 30 |
| `MOMA_MAX_RETRIES` | 失败重试次数，默认 2 |
| `MOMA_MODEL_STRONG` / `_LIGHT` / `_VISION` / `_RULE` | 按需覆盖模型池 |

```powershell
# Windows PowerShell：配置后即走真实 MoMA
$env:MOMA_API_BASE = "https://moma.example.com/v1"
$env:MOMA_API_KEY  = "<你的密钥>"
python run_demo.py restaurant

# 健康检查会返回当前模式（需先启动服务）
curl.exe http://127.0.0.1:8000/health   # {"status":"ok","moma":"live"}
```

> 未拿到真实凭证时保持桩模式即可；配置后无需修改任何业务代码。

## 工作总结与分工

### 已完成工作

- 双场景骨架（开办企业 / 开办餐饮店）共用同一套编排框架。
- 完整编排闭环：意图路由 → 咨询 → 信息采集 → 条件判定 → 材料核验 → 并联提交 → 进度查询。
- 办理进度可推进：流程节点逐个“打勾”（意图识别 → … → 进度跟踪），并联事项由各部门事项子 Agent 办结后回调主 Agent 自动打勾，支持按单号查询进度看板。
- 编排事件出口：`MainAgent.run / query` 支持可选 `on_event` 回调（`app/orchestrator/events.py`），不传时行为完全不变，为 uni-app 前端实时刷新进度预留。
- 配置化条件路由：面积、油烟、生食/冷食、招牌、银行开户、用工人数等按规则增减事项与材料。
- MoMA 三大能力落点（多模型调度 / 智能路由 / 上下文管理），当前为桩实现。
- Mock 政务并联办理与进度状态，冒烟测试一键验证。
- 零第三方依赖可运行 Demo，附设计文档与场景配置。

### 分工（两人均衡）

| 成员 | 负责方向 | 主要工作 |
| --- | --- | --- |
| Kevin（组长） | 架构与编排 | 总体架构设计、主 Agent 编排与意图路由、MoMA 三能力落点、项目统筹与文档、GitHub 发布 |
| Anjie（组员） | 场景与业务 | 五个子 Agent 实现、场景 JSON 与条件路由规则、Mock 政务与知识库桩、冒烟测试 |

### 子路线图（分工自查）

> 已完成标记 `[x]`，未完成标记 `[ ]`；两端工作量保持均衡，可逐项自查。
> 本分工已定稿，后续变更不再调整分工。

#### Kevin（组长）· 架构与编排

- [x] 总体架构设计 + 双场景共用框架
- [x] 主 Agent 编排 + 意图路由
- [x] MoMA 三能力落点（桩）
- [x] 数据模型 / 存储 / 配置 / 演示入口
- [x] README / 设计文档 / GitHub 发布
- [x] FastAPI 服务层 + 多轮会话改造
- [x] MoMA 真实 API 接入
- [ ] 前端（uni-app：App（成品） / H5（测试用），协作 · 以 Anjie 为主）

#### Anjie（组员）· 场景与业务

- [x] 五个子 Agent 实现
- [x] 场景 JSON + 条件路由规则
- [x] Mock 政务并联办理
- [x] 知识库桩（markdown 检索）
- [x] 冒烟测试
- [x] 进度状态推进（流程节点打勾 + 部门子 Agent 办结回调 + 编排事件出口）
- [ ] 前端（uni-app，Vue 3 + TypeScript，App（成品） / H5（测试用），主负责 · Kevin 协作）
- [ ] 向量化知识库与 RAG
- [ ] 多模态材料核验（VerifyAgent 逻辑，MoMA 调度与 Kevin 协作）

## 路线图

- [x] 双场景骨架 + 完整编排闭环 + 条件路由
- [x] 进度状态推进（让“办理进度”可变化）
- [ ] uni-app 前端（Vue 3 + TypeScript，App（成品） / H5（测试用）：聊天 + 动态表单 + 进度看板，事件推送，见「前端交互设计」）
- [x] MoMA 真实 API 接入
- [ ] 向量化知识库与 RAG 检索
- [ ] 多模态材料核验