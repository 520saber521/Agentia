# AgentHub v1 · 终端 5 窗口形态（已归档）

> **状态**：本形态作为 **v1** 已归档，不再是项目主形态。
> **归档时间**：2026-05-21（重构启动日）
> **当前主形态**：v2 · IM 聊天 + Web 前端，见根目录 [`README.md`](../README.md) 与 [`REBUILD_PLAN.md`](../REBUILD_PLAN.md)。
>
> 保留本文档的目的：
>
> 1. v1 的 Router / Scheduler / Protocol / State / Storage / Validation 等后端模块在 v2 仍**完整复用**，理解 v1 有助于读懂 v2 的下半层（见 `docs/ARCHITECTURE.md §5.4 / §5.5`）。
> 2. v2 路线图中，**复用了**这些模块来支撑群聊 / Orchestrator / Trace 等关键能力。
> 3. 对外部贡献者保留可运行的"v1 命令行版本"作为备份心智模型。
>
> **不要在 v2 开发中再调用 v1 的终端启动脚本**。`scripts/start_team.sh` 等已迁至 `scripts/legacy/`。

---

## v1 是什么

**AgentHub v1** 是一个**终端形态**的多 Agent 协作框架，通过本地 HTTP Router 在 5 个终端窗口（MAIN + A/B/C/D）之间路由消息。

**单条命令**启动完整 AI 开发团队：
- **1 个协调 Agent（MAIN）** —— 任务规划、协调与评审
- **4 个执行 Agent（A/B/C/D）** —— 并行任务执行

像管理人类团队一样管理 AI 协作开发。

---

## v1 的核心能力

### 一键团队启动

```bash
./scripts/legacy/start_team.sh
```

> v2 时代请改用 [`README.md`](../README.md) 中描述的 BFF + Web 启动方式。

- 自动拉起 Router（消息中枢）
- 打开 5 个独立终端窗口
- 生成标准文档模板
- 注入 AI 角色提示词

### 智能任务调度

```bash
team analyze --path . --feature "user login"
team design --requirement "user login with OAuth"
team run --task "implement login" --design-approved
```

- **复杂度判断**：自动识别简单 / 复杂任务
- **任务拆解**：按领域拆分子任务
- **契约优先设计**：先生成接口契约，再写代码
- **专业化分工**：前端 (A) / 后端 (B) / DB (C) / 支援 (D)

### 实时协作

```bash
team board
team progress --task TASK-001 --percent 50 --step "implementing API"
team lock --files "src/api.py" --task TASK-001
team notify --task TASK-001 --interface "POST /api/login" --change-type modify
```

- **进度看板**：所有 Agent 实时可见
- **文件锁**：避免代码冲突
- **变更广播**：接口变化自动通知
- **依赖追踪**：阻塞任务自动告警

### 可靠消息投递

- **ACK 双重确认**（投递 + 应用层）
- **指数退避自动重试**
- **超时检测与处理**
- **幂等去重**

### 完整协作协议

```
analyze → design → confirm → schedule → execute → aggregate
```

标准化 AI-to-AI 通信协议：
- 项目分析 / 影响评估
- 设计文档生成
- 契约优先任务拆解
- 协调下的并行执行
- 结果聚合

### 状态持久化与恢复

- 消息日志（JSONL 格式）
- 收件箱状态持久化
- 崩溃后自动恢复
- Session / Epoch 管理

---

## v1 架构

![Architecture](../images/architecture.png)

```
                    Router Server
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

**角色职责：**

| Agent | 角色 | 专业 | 主要职责 |
|:-----:|:----:|:----:|:--------|
| **MAIN** | 协调者 | - | 任务规划、设计评审、问题解决 |
| **A** | 前端专家 | UI/UX | React、Vue、CSS、组件、页面 |
| **B** | 后端专家 | API | FastAPI、业务逻辑、服务层 |
| **C** | 数据库专家 | Data | 数据模型、迁移、查询 |
| **D** | 支援专家 | DevOps | 测试、文档、部署 |

> 在 v2 形态里，这些角色不再绑定到终端窗口，而是变成 `server/adapters/*.py` 下的不同 Adapter 实例，由前端按"联系人"形态展现。详见 [`REBUILD_PLAN.md §4.1`](../REBUILD_PLAN.md)。

---

## v1 消息协议

| 消息类型 | 方向 | 用途 |
|:--------:|:----:|:----|
| `review` | MAIN→Members | 评审文档 / 代码 |
| `report` | Members→MAIN | 反馈评审结果 |
| `assign` | MAIN→Members | 分派任务 |
| `clarify` | Members→MAIN | 提问澄清 |
| `answer` | MAIN→Members | 回答问题 |
| `verify` | MAIN→Members | 验证变更 |
| `done` | Members→MAIN | 任务完成 |
| `fail` | Members→MAIN | 任务失败 |

完整规范见 [`docs/main-members-workflow.md`](main-members-workflow.md)。
v2 中这些协议消息**继续复用**，只是会被包装在 `ChatMessage` 内部，前端以 IM 消息呈现。

---

## v1 快速开始（仅供参考）

### 前置依赖

- **macOS**（Linux 支持在 v1 时未完成）
- **Python 3.8+**
- **Terminal.app 或 iTerm2**
- **AI CLI 工具**（Codex / Claude Code 等）

### 安装

```bash
git clone https://github.com/Dmatut7/AgentHub.git
cd AgentHub
```

### 启动 AI 团队（v1 形态）

```bash
./scripts/legacy/start_team.sh
```

将自动：
1. 启动 Router（默认端口 8765）
2. 生成标准文档模板
3. 为每个 Agent 打开一个终端窗口

---

## v1 常用命令

```bash
# === 系统管理 ===
./scripts/legacy/start_team.sh          # 启动系统
./scripts/legacy/status_team.sh         # 查状态
./scripts/legacy/stop_team.sh           # 停止系统

# === 智能任务流 ===
team analyze --path . --feature "new feature"
team design --requirement "feature description"
team run --task "feature" --design-approved
team schedule --task "feature description"

# === 协作 ===
team board
team progress --task T1 --percent 50 --step "..."
team lock --files "src/api.py" --task T1
team notify --task T1 --interface "API" -c modify

# === 消息 ===
team say --from MAIN --to A --text "Start task"
team review --to A,B,C,D --task T1 --file doc.md
team assign --to B --task T1 --files "src/*"

# === 监控 ===
team status --tasks
team trace --task T1
curl http://127.0.0.1:8765/status | jq
```

---

## v1 环境变量

| 环境变量 | 说明 | 默认值 |
|:--------|:----|:------|
| `TERMINAL_ADAPTER` | 终端类型 (`terminal`/`iterm`) | `terminal` |
| `CODEX_PATH` | AI CLI 可执行文件路径 | `codex` |

---

## v1 → v2 迁移说明

| v1 概念 | v2 对应 | 文件 |
|:-------|:-------|:-----|
| 5 个终端窗口 | Web 三栏 IM 界面 | `web/src/App.tsx` |
| MAIN Agent | Orchestrator（群聊主持人 Bot） | `server/orchestrator.py`（W3 新建） |
| A/B/C/D Agent | 多个 Adapter 实例（Claude / Codex / OpenCode / 自建） | `server/adapters/*.py` |
| `scripts/legacy/start_team.sh` | `scripts/dev.ps1` / `scripts/dev.sh`（W2 新建）| 一键 BFF + Web |
| `team say --from --to` CLI | 浏览器输入框 + `@mention` | `web/src/components/Composer.tsx` |
| Router HTTP `:8765` | **保留**；v2 群聊路径仍走它 | `src/router/router.py` |
| Scheduler `analyze/design/decompose` | **保留**；被 `server/orchestrator.py` 包装 | `src/scheduler/` |
| JSONL 持久化 | **保留**作为 Router 端持久化；v2 会话与消息使用 SQLite | `src/storage/` ＋ `server/db/` |
| `team trace --task` 命令行 | `TraceViewer.tsx` Mermaid 浮窗（W5 新建） | `web/src/components/TraceViewer.tsx` |

---

## v1 原始文档索引

| 文档 | 用途 |
|:-----|:----|
| [`docs/design.md`](design.md) | v1 系统架构设计 |
| [`docs/main-members-workflow.md`](main-members-workflow.md) | v1 协议规范 |
| [`EXAMPLES.md`](../EXAMPLES.md) | v1 使用案例 |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | 贡献指南 |
| [`SUPPORT.md`](../SUPPORT.md) | 帮助与排错 |
| [`CHANGELOG.md`](../CHANGELOG.md) | 版本历史 |

---

## License

[MIT License](../LICENSE) © 2026 [Dmatut7](https://github.com/Dmatut7)
