# AgentHub · 多 Agent 协作平台

> **课题**：通过对话式交互创建网页 / Workflow / 文档等产物的"多 Agent 协作平台"。
> **形态**：IM 聊天（飞书 / 微信式）+ 三栏 Web 前端 + 可插拔 Agent Adapter。
> **状态**：W1 骨架已闭环；W2 起按 [`REBUILD_PLAN.md`](REBUILD_PLAN.md) 推进至完整产品形态。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![React 18](https://img.shields.io/badge/react-18-61dafb.svg)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/fastapi-0.110+-009688.svg)](https://fastapi.tiangolo.com/)

---

## 一、产品一句话

像在飞书 / 微信里和人聊天一样，**新建会话 → 选 Agent → 单聊或群聊**，由 Orchestrator 自动拆任务、多个 Agent 并发干活，**产物（代码 / 网页 / 文档）直接在聊天流里预览、编辑、版本化**。

## 二、为什么是这个项目

AgentHub 原本是一个**本地 5 终端窗口**的多 Agent 后端，已经具备完整的 Router / Scheduler / Protocol / State 能力。本次重构**不重写后端**，只把"5 个终端"换成"IM Web 前端 + BFF"，让课题要求的 IM 形态自然落地。详见 [`COURSE_PROPOSAL.md §一`](COURSE_PROPOSAL.md)。

| 课题概念 | AgentHub 原概念 | 处理 |
| --- | --- | --- |
| Orchestrator 主持人 | MAIN Agent | 包装 `src/scheduler/` 为 `server/orchestrator.py`（W3） |
| 联系人 / 群成员 | A/B/C/D Agent | 拆为 `server/adapters/{claude_code,codex,opencode,custom}.py` |
| 群聊消息总线 | Router | **零改动**复用 `src/router/router.py`（W3 接入） |
| 群聊历史 / pin | JSONL 持久化 | 上层补 SQLite 会话表；JSONL 作为 Router 端持久化 |
| 实时推送 | HTTP 长轮询 `pop_inbox` | 升级为 WebSocket（W1 已落地） |

---

## 三、当前进度（W1 已交付）

| 模块 | 路径 | 状态 |
| --- | --- | --- |
| 产品规格 / 验收 | [`ai-collab/SPEC.md`](ai-collab/SPEC.md) | W1 6 个 Feature 全部 `Done` |
| 技术架构 | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 持续更新 |
| **重构规划** | [**`REBUILD_PLAN.md`**](REBUILD_PLAN.md) | **5 个 Sprint，W2 即将启动** |
| 4 周课题路线图 | [`COURSE_PROPOSAL.md`](COURSE_PROPOSAL.md) | 已重新对齐 |
| BFF（FastAPI + SQLite） | [`server/`](server/) | pytest **26** + smoke **5 套** 全绿 |
| Web 前端（React + Vite） | [`web/`](web/) | build 158 kB / gzip 51 kB；vitest **15** 全绿 |
| AI 协作沉淀 | [`ai-collab/`](ai-collab/) | SPEC / skills × 3 / rules × 3 / records × 1 |
| Cursor 硬约束 | [`.cursor/rules/`](.cursor/rules/) | 自动加载，同源于 `ai-collab/rules/` |
| W1 复盘 | [`ai-collab/records/20260521-W1.md`](ai-collab/records/20260521-W1.md) | 5 个关键决策 + 真实协作片段 |

**W1 能力闭环**：浏览器与 Mock Agent 流式对话 → SQLite 持久化 → 单聊会话 CRUD → WS 心跳 + 指数退避重连 → cancel 即时停 → reducer 纯函数化。

---

## 四、一键体验 v2

### Windows / PowerShell

```powershell
# 1) 起 BFF（默认 :8788）
cd server
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn main:app --host 127.0.0.1 --port 8788 --app-dir .

# 2) 起 Web（默认 :5173），新开一个 PowerShell
cd web
npm install
npm run dev

# 3) 浏览器打开 http://localhost:5173/

# 4) 一键端到端验收
server\.venv\Scripts\python.exe server\tests\smoke_w1.py
```

### macOS / Linux

```bash
# 1) 起 BFF
cd server && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8788 --app-dir .

# 2) 起 Web
cd web && npm install && npm run dev

# 3) 浏览器打开 http://localhost:5173/
```

> v1 的 `scripts/start_team.sh` 已迁至 [`scripts/legacy/`](scripts/legacy/README.md)，本目录已**不再**作为主入口。

---

## 五、5 个 Sprint 路线（W2 → 答辩）

> 每个 Sprint = 1 工作周；每个 Sprint 末必产出 ≥1 可录屏 demo + 1 份 `ai-collab/records/*`。
> 全部细节见 [`REBUILD_PLAN.md`](REBUILD_PLAN.md)。

| Sprint | 目标 | 关键交付 | demo 场景 |
| --- | --- | --- | --- |
| **W2** | Adapter + 群聊 | 拆 `main.py` · 接 ClaudeAdapter · 群聊 fan-out · `@mention` · 三栏布局 | "群聊里 `@Claude` 和 `@Mock` 同时写排序代码" |
| **W3** | Orchestrator + 任务卡片 | Router 接入 · `server/orchestrator.py` · `task` 表 + 状态机 · `TaskStatusCard` · 第二个真 Adapter（Codex/OpenCode） | "`@Orchestrator` 做 OAuth 登录页 + 后端 API，看到任务卡片 + 进度条 + 汇总" |
| **W4** | 富媒体 + 产物 | 6 类卡片 schema · `artifact` 表 + 版本链 · Monaco 编辑器 · iframe 预览 · Diff 卡片 | "Claude 写 Login.tsx → 预览 → Monaco 改样式 → Diff → 一键应用" |
| **W5** | 自建 Agent + 打磨 | `POST /api/agents` · `CustomAgentAdapter` · pin / 搜索 / 归档 · Trace Mermaid 浮窗 · 圈选改 | "对话式创建 PM Bot → 回群聊 @ 他 → trace 看链路" |
| **B**  | 答辩交付 | 3 分钟 demo 视频 · 答辩 deck · README 定稿 · 全套 records | — |

---

## 六、目录结构（v2 终态）

```
AgentHub/
├── REBUILD_PLAN.md          ★ 5 个 Sprint 重构规划
├── COURSE_PROPOSAL.md       4 周课题路线雏形
├── README.md                ← 当前文件
├── server/                  v2 BFF（FastAPI + WS + SQLite）
│   ├── main.py / ws.py / handlers/    （W2-D1 拆分）
│   ├── orchestrator.py                （W3 新增）
│   ├── adapters/{base,mock,claude_code,codex,opencode,custom}.py
│   ├── api/ services/ db/ tests/
│   └── ...
├── web/                     v2 前端（React + Vite + Tailwind + Zustand）
│   └── src/{App,pages,components,stores,ws,api}
├── src/                     v1 后端（机器对机器，v2 复用）
│   ├── router/  scheduler/  protocol/  state/  storage/  validation/
│   └── cli/  launcher/      （保留但不再作为入口）
├── ai-collab/               AI 协作沉淀（评分 30% 权重）
│   ├── SPEC.md  README.md
│   ├── skills/ rules/ records/
├── docs/
│   ├── ARCHITECTURE.md      v2 技术架构权威版本
│   ├── v1-terminal.md       v1 终端形态归档
│   ├── design.md  main-members-workflow.md
├── scripts/
│   ├── legacy/              v1 启动脚本（已归档）
│   └── (W2-D1 起新建 dev.ps1 / dev.sh)
├── prompts/                 v1 Agent 角色提示词（v2 仍可参考）
├── fixtures/                协议黄金样本
└── images/                  README 与 ARCHITECTURE 用图
```

---

## 七、核心文档导航

| 想了解 | 看哪里 |
| --- | --- |
| **课题要求 + 4 周路线** | [`COURSE_PROPOSAL.md`](COURSE_PROPOSAL.md) |
| **重构规划（保留 / 改造 / 新增 / 弃用）** | [`REBUILD_PLAN.md`](REBUILD_PLAN.md) |
| **技术架构（分层 / 数据模型 / 协议）** | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| **行为契约（EARS / Given-When-Then）** | [`ai-collab/SPEC.md`](ai-collab/SPEC.md) |
| **怎么加 Adapter / 消息类型** | [`ai-collab/skills/`](ai-collab/skills/) |
| **代码硬约束（前 / 后 / Adapter）** | [`ai-collab/rules/`](ai-collab/rules/) ↔ [`.cursor/rules/`](.cursor/rules/) |
| **真实开发协作片段** | [`ai-collab/records/`](ai-collab/records/) |
| **BFF 接口与测试** | [`server/README.md`](server/README.md) |
| **前端工程与组件** | [`web/README.md`](web/README.md) |
| **v1 终端形态历史归档** | [`docs/v1-terminal.md`](docs/v1-terminal.md) |

---

## 八、技术栈

### 后端

| 类别 | 选型 |
| --- | --- |
| Web 框架 | FastAPI 0.110+ |
| ASGI Server | uvicorn |
| ORM | SQLAlchemy 2.x async + aiosqlite |
| 数据库 | SQLite（默认） / PostgreSQL 15+（可切） |
| HTTP Client | httpx (async) |
| 校验 | pydantic v2 |
| 任务编排 | `src/scheduler/*`（v1 沉淀） |
| 测试 | pytest + pytest-asyncio |

### 前端

| 类别 | 选型 |
| --- | --- |
| 框架 / 构建 | React 18 + TypeScript 5 + Vite 6 |
| 样式 | TailwindCSS 3 |
| 状态 | Zustand 5 + 自研 reducer |
| 编辑器（W4） | `@monaco-editor/react` |
| Markdown（W4） | `react-markdown` + `rehype-highlight` + `remark-gfm` |
| 实时 | 原生 WebSocket（自研重连 + 心跳） |
| 测试 | Vitest + Testing Library |

---

## 九、贡献与协作

- **改 reducer / state 之前**：必须先在 `web/src/stores/reducer.test.ts` 写一个失败用例。
- **加 Adapter / 消息类型之前**：必须按 [`ai-collab/skills/`](ai-collab/skills/) 走完 SOP。
- **任何对协议字段 / 数据库表 / Adapter 接口的修改**：必须在 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) 留 changelog。
- **每个 Sprint 收尾**：必须产出一份 `ai-collab/records/YYYYMMDD-Wx.md`，含 ≥2 段真实协作片段。
- **贡献指南**：[`CONTRIBUTING.md`](CONTRIBUTING.md)

---

## 十、Roadmap（P2 / 不在课题本期）

- [ ] 部署发布（一键预览 URL / 容器化）
- [ ] 桌面端（本地文件访问 + Agent 进程管理）
- [ ] 移动端轻量 IM（查看 + 审批 + 产物预览）
- [ ] 多机分布式 Router

---

## 附：v1 终端形态（已归档）

<details>
<summary><b>展开查看 v1 历史形态简介</b>（5 终端窗口 + 本地 Router，详细文档见 <a href="docs/v1-terminal.md"><code>docs/v1-terminal.md</code></a>）</summary>

AgentHub v1 是一个 **macOS 终端形态**的多 Agent 协作框架：

```
                    Router Server (:8765)
        (Message Routing / State Management / Delivery)

                    │
    ┌───────┬───────┼───────┬───────┐
    │       │       │       │       │
┌───▼───┐ ┌─▼───┐ ┌─▼───┐ ┌─▼───┐ ┌─▼───┐
│ MAIN  │ │  A  │ │  B  │ │  C  │ │  D  │
│Coord. │ │Exec │ │Exec │ │Exec │ │Exec │
│Agent  │ │Agent│ │Agent│ │Agent│ │Agent│
└───────┘ └─────┘ └─────┘ └─────┘ └─────┘
```

**核心能力**：

- 一键 `./scripts/legacy/start_team.sh` 拉起 Router + 5 个终端窗口
- 标准化协议：`review / report / assign / clarify / answer / verify / done / fail`
- 智能任务调度：`analyze → design → decompose → schedule → execute → aggregate`
- 双 ACK 可靠投递、指数退避重试、JSONL 持久化、崩溃恢复

**v1 在 v2 里仍发挥的作用**：

| v1 模块 | v2 用途 |
| --- | --- |
| `src/router/` | **零改动**复用作消息总线，承载群聊 + Orchestrator 分派（W3 接入） |
| `src/scheduler/` | **包装**为 `server/orchestrator.py`，群聊主持人复用其拆任务逻辑 |
| `src/protocol/` | **小扩展** 3 个可选字段（`conversation_id` / `card_type` / `artifact_id`） |
| `src/state/` + `src/storage/` | **复用**作为 Router 端持久化与崩溃恢复 |
| `src/validation/` | **复用** schema 校验 |
| `prompts/agent_*.txt` | v2 Adapter 的 system prompt 参考 |

完整 v1 说明（含 `team` CLI 命令清单、消息协议表、架构图）见 [`docs/v1-terminal.md`](docs/v1-terminal.md)。

</details>

---

## License

[MIT License](LICENSE) © 2026 [Dmatut7](https://github.com/Dmatut7)

---

<div align="center">

**AgentHub** · Making AI team collaboration as natural as a group chat.

[GitHub](https://github.com/Dmatut7/AgentHub) · [Issues](https://github.com/Dmatut7/AgentHub/issues) · [Discussions](https://github.com/Dmatut7/AgentHub/discussions)

</div>
