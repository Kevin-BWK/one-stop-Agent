# 一件事·一次办 智能体（One-Stop Agent）

基于移动云 **MoMA** 平台，面向“高效办成一件事”政务场景的多 Agent 应用。内置**开办企业**与**开办餐饮店**两个业务场景，二者共用同一套 Agent 编排框架，业务差异全部由 `scenarios/*.json` 配置驱动——新增“一件事”只需加一份场景配置，不改代码。

## 项目概述

- 一个入口、一次填写、并联办理、一次出件。
- 两个业务场景（企业 / 餐饮店）共享编排框架，配置即业务。
- 骨架阶段零第三方依赖，`python run_demo.py` 即可跑通最小闭环。

## 架构概览

```
接入层   uni-app 前端：微信小程序 · H5 · App（预留）
编排层   MoMA 多 Agent 编排（主 Agent + 5 个子 Agent）
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
| 进度跟踪 Agent | 并联办理进度查询 | 规则引擎 |

编排闭环：

```
意图路由 → 咨询 → 信息采集 → 条件判定 → 材料核验 → 并联提交 → 进度查询
```

## 目录结构

```
one-stop-agent/
├── run_demo.py              # 最小可运行演示入口
├── scenarios/               # 场景配置（事项、字段、条件规则）
├── data/knowledge/          # 办事指南知识库
├── docs/                    # 设计文档
├── app/
│   ├── moma/                # MoMA 客户端 + 上下文管理
│   ├── agents/              # 五个子 Agent
│   ├── orchestrator/        # 主 Agent 编排 + 意图路由
│   ├── knowledge/           # 知识检索
│   ├── mock_gov/            # 政务系统 Mock
│   ├── models/              # 数据模型
│   └── storage/             # 存储
└── tests/                   # 冒烟测试
```

## 技术栈

| 层级 | 当前骨架（零依赖） | 目标 / 生产形态 |
| --- | --- | --- |
| 语言 / 运行 | Python 3.10+ 标准库（dataclass） | Python + FastAPI + uvicorn |
| 平台底座 | `MoMAClient` 桩 | 移动云 MoMA 多模型调度 / 路由 / 上下文 |
| 模型 | deepseek-r1 / qwen-turbo / qwen-vl / 规则引擎（桩） | 九天大模型 + DeepSeek / Qwen / GLM / Qwen-VL |
| 知识检索 | 整篇 markdown 返回 | 向量库 + Embedding（BGE 等）RAG |
| 上下文 / 数据 | `SessionContext` / `InMemoryRepo` 内存 | Redis + PostgreSQL / MySQL |
| 政务集成 | `MockGovServices` 本地模拟 | 市场监管 / 税务 / 消防 / 城管 / 卫健接口 |
| 前端 | 暂未实现（预留） | uni-app（Vue 3 + TS）：微信小程序 / H5 / App |

## 快速开始

```bash
# 跑通两个场景的最小闭环（零第三方依赖）
python run_demo.py                # 两个场景都跑
python run_demo.py restaurant     # 只跑餐饮店
python run_demo.py enterprise     # 只跑企业

# 冒烟测试（无需 pytest）
python tests/test_flow.py
```

- 要求 Python 3.10+（已在 3.12 验证），核心运行仅用标准库。
- Windows 若无 `python` 命令，可改用 `py` 启动器，如 `py -3 run_demo.py`。
- 接入 Web / 真实 MoMA 时再安装：`pip install -r requirements.txt`。

## 桩实现 → 真实接入

| 模块 | 当前实现 | 真实接入 |
| --- | --- | --- |
| `app/moma/client.py` | 返回模拟回复与模型名 | 调用 MoMA API（多模型调度 / 路由） |
| `app/knowledge/retriever.py` | 整篇返回 markdown 指南 | 向量检索 / RAG |
| `app/mock_gov/services.py` | 本地内存模拟并联办理 | 对接真实政务系统 |
| `app/storage/repo.py` | 内存字典 | PostgreSQL / MySQL |

## 工作总结与分工

### 子路线图（分工自查）

> 已完成标记 `[x]`，未完成标记 `[ ]`；两端工作量保持均衡，可逐项自查。
> 本分工已定稿，后续变更不再调整分工。

#### Kevin（组长）· 架构与编排

- [x] 总体架构设计 + 双场景共用框架
- [x] 主 Agent 编排 + 意图路由
- [x] MoMA 三能力落点（桩）
- [x] 数据模型 / 存储 / 配置 / 演示入口
- [x] README / 设计文档 / GitHub 发布
- [ ] FastAPI 服务层 + 多轮会话改造
- [ ] MoMA 真实 API 接入
- [ ] 移动端 / 小程序前端（uni-app，协作 · 以 Anjie 为主）

#### Anjie（组员）· 场景与业务

- [x] 五个子 Agent 实现
- [x] 场景 JSON + 条件路由规则
- [x] Mock 政务并联办理
- [x] 知识库桩（markdown 检索）
- [x] 冒烟测试
- [ ] 移动端 / 小程序前端（uni-app，主负责 · Kevin 协作）
- [ ] 进度状态推进
- [ ] 向量化知识库与 RAG
- [ ] 多模态材料核验（VerifyAgent 逻辑，MoMA 调度与 Kevin 协作）