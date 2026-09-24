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
意图路由 → 咨询 → 信息采集 → 条件判定 → 材料提交与核验 → 并联提交 → 各部门事项办理 → 进度查询
```

其中「材料提交与核验」发生在**受理之前**：条件判定先算出要交哪些材料，
用户逐项拍照 / 选文件上传并通过核验后，才允许并联提交（见 `docs/09`）。

## 目录结构

```
one-stop-agent/
├── dev.ps1 / dev.bat        # 一键启动开发环境（后端 + 前端 H5，自动开浏览器）
├── run_demo.py              # 最小可运行演示入口（含进度查询）
├── frontend/                # uni-app 前端（Vue 3 + TS；成品为 App，H5 仅调试）
├── server/                  # FastAPI 服务层（多轮会话 + 事件流）
├── scenarios/               # 场景配置（事项、材料条目、字段、条件规则）
├── data/knowledge/          # 办事指南知识库
├── data/runtime/            # 运行时办理单、材料文件与日志（自动生成，已忽略）
├── docs/                    # 设计文档
├── app/
│   ├── moma/                # MoMA 客户端 + 上下文管理
│   ├── agents/              # 子 Agent（咨询/采集/判定/核验/部门事项/进度）
│   ├── orchestrator/        # 主 Agent 编排 + 意图路由 + 办理流程进度 + 编排事件（flow.py / events.py）
│   ├── materials/           # 材料清单规则、落盘存储、上传通道与核验（spec / store / verify / service）
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
| 知识检索 | 按问题的本地检索基线（切分 + 字符 2-gram + 标题加权，零依赖，见 `docs/11`） | 向量库 + Embedding（BGE 等）RAG + 重排 |
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

# 冒烟测试（无需 pytest），按层组织
python tests/test_condition_routing.py  # 规则层：条件判定矩阵（操作符 / 边界 / 组合 / 反向）
python tests/test_knowledge.py          # 检索层：切分 / 打分 / 场景映射 / 兜底 / 咨询接线
python tests/test_flow.py               # 编排层：MainAgent 闭环 + 流程节点 + 事件
python tests/test_materials.py          # 材料层：清单 / 槽位 / 核验（含视觉核验与降级）/ 补正 / 撤回 / 受理拦截
python tests/test_moma_client.py        # 模型层：MoMA 桩/真实、重试与降级（离线）
python tests/test_server_smoke.py       # 服务层：多轮会话闭环（零第三方依赖）
python tests/test_api_e2e.py            # 接口层：端到端 HTTP + 异常分支

# 启动 API（需先 pip install -r requirements.txt）
uvicorn server.main:app --reload

# 一键启动开发环境：后端 + uni-app H5 调试端，就绪后自动打开浏览器
dev.bat                     # Windows 双击即可；等价于 powershell -ExecutionPolicy Bypass -File dev.ps1
dev.bat -Stop               # 停止前后端
```

- 要求 Python 3.10+（已在 3.12 验证），核心运行仅用标准库。
- Windows 若无 `python` 命令，可改用 `py` 启动器，如 `py -3 run_demo.py`。
- 接入 Web 前端 / 真实 MoMA 时再安装：`pip install -r requirements.txt`。
- 前端调试端：uni-app（Vue 3 + TS）H5，默认 http://127.0.0.1:5173/ ；首次运行 `dev.bat` 会自动 `npm install`，需 Node 18+。

## 桩实现 → 真实接入

| 模块 | 当前实现 | 真实接入 |
| --- | --- | --- |
| `app/moma/client.py` | ✅ 已支持真实 API（未配置环境变量时回退桩） | 配置 `MOMA_API_BASE` / `MOMA_API_KEY` 即启用 |
| `app/knowledge/retriever.py` | 本地检索基线：两级切分 + 2-gram 打分（见 `docs/11`） | 向量检索 / Embedding + 重排（只换 `search()` 实现，契约不变） |
| `app/mock_gov/services.py` | 本地内存模拟并联办理 | 对接真实政务系统 |
| `app/storage/repo.py` | 内存 / JSON 文件（跨进程查询进度） | PostgreSQL / MySQL |
| `app/agents/consult_agent.py` | 拼固定话术 | MoMA 对话模型（见 `docs/08`） |
| `app/agents/verify_agent.py` | 三级分工：形式校验（格式/体积）→ 本地规则（体积过小、**读文件头判分辨率**）→ 只有“是不是这份材料”才交 `qwen-vl`；模型不可用回落本地结论 | 更细的要素级校验（证号 / 有效期 / 与表单字段比对，见 `docs/09`） |
| `app/agents/item_agent.py` | 直接返回“已办结” | 调用各部门政务系统，异步回调（见 `docs/06`） |
| `app/materials/store.py` | 材料与文件落本地磁盘 `data/runtime/materials/` | 对象存储（OSS / COS）+ 文件编号 |
| 电子证照共享 | **未做**（所有材料都要求上传） | 对接本地电子证照库，材料条目加 `source` 字段（见 `docs/09`） |

## 前端交互设计（uni-app：Vue 3 + TypeScript，事件推送）

前端形态为 **uni-app（Vue 3 + TypeScript）**：**最终成品为 App**，H5 仅用于开发调试，微信小程序已弃用。

交互形态是**对话式办理**：聊天区可输入、可随时插问，表单与对话共享同一份数据；材料在独立区域提交，
提交前做必填校验；Agent 回复一律**自然语言**，不出现 JSON 字面量或内部事项 id。
详见 `docs/08-对话交互设计.md` 与 `docs/09-材料提交与核验设计.md`。
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
- **材料区**：清单、槽位与张数上限全部由后端下发（`GET /api/materials/{intake_id}`），前端只负责渲染与发起拍照 / 选文件；上传走 `uni.uploadFile`（multipart），材料齐备后才允许开始办理（见 `docs/09`）。
- **实时预判**：填表过程中按当前已填字段预判"预计要办什么、交什么"（`POST /api/preview`，只读无副作用，前端 500ms 防抖）；字段采齐后才由 `POST /api/materials/intake` 产出**正式清单**，界面区分"预判"与"最终"（见 `docs/09`）。
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

> 说明：**前端（uni-app）H5 调试端已实现**——聊天 + 动态表单 + 材料区 + 进度看板，H5 走 SSE、App 走 WebSocket（同一份代码，见 `frontend/src/api/stream.ts`）。
> **App 成品端打包待做**（WebSocket 通道、相机权限等衔接问题见 `docs/10-App打包前检查清单.md`）。
> 完整的事件契约与接口定义见 `docs/07-前端交互设计.md`。

## MoMA 真实接入

`app/moma/client.py` 支持“桩 / 真实”一键切换，业务代码无需改动：

- **未配置** → 桩模式：本地模拟回复，Demo 与单测可离线运行。
- **配置后** → 真实模式：调用 OpenAI 兼容接口 `POST {API_BASE}/chat/completions`，5xx / 429 自动重试，失败时回退本地文案。

采用**主 / 子两套端点与模型**，对应 MoMA 的多模型调度：

| 角色 | 用途 | 环境变量 |
| --- | --- | --- |
| 主 Agent | 咨询等主流程推理 | `MOMA_MAIN_API_BASE` / `MOMA_MAIN_API_KEY` / `MOMA_MAIN_MODEL` |
| 子 Agent | 部门事项子 Agent 办理回执 | `MOMA_SUB_API_BASE` / `MOMA_SUB_API_KEY` / `MOMA_SUB_MODEL` |

通用变量：

| 环境变量 | 说明 |
| --- | --- |
| `MOMA_TIMEOUT` | 超时秒数，默认 30 |
| `MOMA_MAX_RETRIES` | 失败重试次数，默认 2 |
| `MOMA_DISABLE_LIVE` | 设为 `1` 时忽略环境变量、强制桩模式（测试 / 离线演示用） |
| `MOMA_MODEL_STRONG` / `_LIGHT` / `_VISION` / `_RULE` | 未配置角色模型时，按任务覆盖内置模型池 |
| `MOMA_API_BASE` / `MOMA_API_KEY` | 兼容旧用法：作为主角色的回退配置 |

**密钥安全（重要）**

- 密钥写入项目根目录 `.env`；该文件**已在 `.gitignore` 中，切勿提交**。
- 也可改用系统环境变量，**环境变量优先于 `.env`**。
- 对外输出（`describe()` / `/health`）**从不包含密钥**。

```powershell
# 方式一（推荐）：在项目根目录建 .env（不进版本库）
#   MOMA_MAIN_API_BASE=https://<主端点>/v1
#   MOMA_MAIN_API_KEY=<主密钥>
#   MOMA_MAIN_MODEL=deepseek-v4-flash-0731
#   MOMA_SUB_API_BASE=https://<子端点>/v1
#   MOMA_SUB_API_KEY=<子密钥>
#   MOMA_SUB_MODEL=zhipu/glm-5.3-flash

python run_demo.py restaurant          # 自动读取 .env，走真实模型
curl.exe http://127.0.0.1:8000/health  # {"status":"ok","moma":"live"}

# 方式二：临时用环境变量（示例，勿写进代码或提交）
$env:MOMA_MAIN_API_BASE = "https://<主端点>/v1"
$env:MOMA_MAIN_API_KEY  = "<主密钥>"
```

> 未配置时自动回退桩模式；配置后无需修改任何业务代码。

## 工作总结与分工

### 已完成工作

- 双场景骨架（开办企业 / 开办餐饮店）共用同一套编排框架。
- 完整编排闭环：意图路由 → 咨询 → 信息采集 → 条件判定 → 材料提交与核验 → 并联提交 → 进度查询。
- 办理进度可推进：流程节点逐个“打勾”（意图识别 → … → 进度跟踪），并联事项由各部门事项子 Agent 办结后回调主 Agent 自动打勾，支持按单号查询进度看板。
- 材料提交与核验：材料条目化（含“为什么交 / 怎么给 / 格式 / 槽位”），支持拍照 / 相册 / 选文件逐项上传，形式校验 + 桩内容核验，需补正可原地重传，必交材料全部通过才允许并联提交（见 `docs/09`）。
- 受理入口统一：表单式（`/apply`）与对话式（`/api/session` + `/api/chat` + `/api/fields`）两条路径**共用同一套 `MainAgent` 编排与材料提交**；多轮会话只负责采集与材料清单，不再自行受理（见 `docs/09`）。
- 对话式办理：聊天区可输入、随时插问；提问走会话（`ensureSession()` + `/api/ask` 带 `session_id`），服务端按会话记住问答，最近 3 轮历史带进模型上下文（见 `docs/08`）。
- 知识检索：咨询时按问题检索办事指南片段作为作答依据（两级切分 + 字符 2-gram + 标题加权，零依赖）；真实/离线两条路径都带依据，不传知识库时行为不变（见 `docs/11`）。
- 文案自然语言化：结构化进度看板只进 CLI / 进度看板，**推给对话区的都是自然语言**；材料与事项一律用中文名，不出现 JSON 字面量、内部 id、模型名（见 `docs/08`）。
- 编排事件出口：`MainAgent.run / query` 支持可选 `on_event` 回调（`app/orchestrator/events.py`），不传时行为完全不变，为 uni-app 前端实时刷新进度预留。
- 配置化条件路由：面积、油烟、生食/冷食、招牌、银行开户、用工人数等按规则增减事项与材料。
- MoMA 三大能力落点（多模型调度 / 智能路由 / 上下文管理）：支持桩 / 真实一键切换（配置 `MOMA_API_BASE` / `MOMA_API_KEY` 即走真实，见「MoMA 真实接入」）。
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
- [x] 前端 H5 调试端（uni-app：Vue 3 + TypeScript，协作 · 以 Anjie 为主）
- [ ] 前端 App 成品端打包（代码适配与依赖冲突均已解决，`npm run build:app` 可出产物；剩**填 `appid`** 与 HBuilderX 真机打包，见 `docs/10`，协作 · 以 Anjie 为主）

#### Anjie（组员）· 场景与业务

- [x] 五个子 Agent 实现
- [x] 场景 JSON + 条件路由规则
- [x] Mock 政务并联办理
- [x] 知识库桩（markdown 检索）
- [x] 冒烟测试
- [x] 进度状态推进（流程节点打勾 + 部门子 Agent 办结回调 + 编排事件出口）
- [x] 材料提交与核验（材料清单 / 逐项上传与核验 / 补正闭环 / 受理前置校验，见 `docs/09`）
- [x] 前端 H5 调试端（uni-app，Vue 3 + TypeScript，主负责 · Kevin 协作）
- [ ] 前端 App 成品端打包（代码适配与依赖冲突均已解决，`npm run build:app` 可出产物；剩**填 `appid`** 与 HBuilderX 真机打包，见 `docs/10`，主负责 · Kevin 协作）
- [x] 知识检索基线（按问题检索指南片段，见 `docs/11`）
- [ ] 向量化检索（Embedding + 向量库 + 重排，见 `docs/11`）
- [x] 多模态材料核验（VerifyAgent 逻辑，MoMA 调度与 Kevin 协作）

## 路线图

- [x] 双场景骨架 + 完整编排闭环 + 条件路由
- [x] 进度状态推进（让“办理进度”可变化）
- [x] uni-app 前端 H5 调试端（聊天 + 动态表单 + 材料区 + 进度看板，SSE 事件推送，见「前端交互设计」）
- [ ] uni-app App 成品端打包（**前端适配与依赖冲突均已解决**：`uni.request` 跨端 + 可配绝对基址 + 条件编译选通道 + 权限声明 + `@vue/shared` override；`npm run build:app` 可出产物，剩**填 `appid`** 与 HBuilderX 真机打包，见 `docs/10-App打包前检查清单.md`）
- [x] 对话式办理（聊天区可输入、随时插问；提问走会话带多轮上下文，见 `docs/08`）
- [x] 材料提交与核验（材料清单 + 逐项上传核验 + 补正闭环 + 受理前置校验，见 `docs/09`）
- [x] 提交前置校验 + 文案自然语言化（去 JSON 字面量与内部 id；结构化看板只进 CLI，对话区只收自然语言，见 `docs/08`）
- [x] MoMA 真实 API 接入（桩/真实一键切换，主/子双角色）
- [x] 知识检索基线（按问题检索指南片段：两级切分 + 字符 2-gram + 标题加权，零依赖，见 `docs/11`）
- [ ] 向量化检索（Embedding + 向量库 + 重排；替换 `search()` 实现即可，契约不变，见 `docs/11`）
- [x] 多模态材料核验（视觉核验器：图片 + 提示词交 `qwen-vl` 判断是否合规件；模型不可用自动回落桩规则，见 `docs/09`）
