# AgentHub 重构规划（REBUILD_PLAN）

> 版本：v1.0 · 2026-05-21
> 状态：草案，等待 Operator 审核后开始执行
> 关联文档：
> - `COURSE_PROPOSAL.md` —— 课题原始要求与 4 周路线雏形
> - `docs/ARCHITECTURE.md` —— 已完成的技术架构设计
> - `ai-collab/SPEC.md` —— 已交付（W1）+ 待交付（W2–W4）行为契约
> - `ai-collab/records/20260521-W1.md` —— W1 复盘

---

## 0. 摘要（TL;DR）

**结论**：当前项目**不需要推翻重来**。架构层面（`docs/ARCHITECTURE.md` §4–§7）和课题要求是对齐的；真正的问题是 **W1 只完成了"骨架"，离课题"完整产品"还差 3 个迭代**：

| 课题要求 | 现状 | 差距类型 |
| --- | --- | --- |
| IM 聊天交互（单聊 + 群聊 + 多会话） | 仅单聊 + 单 Agent 占位 | **功能缺失** |
| 主 Agent 协调器 Orchestrator | 完全没有 | **功能缺失** |
| 多 Agent 接入（Claude Code / Codex / OpenCode + 自建） | 只有 `MockAdapter` | **功能缺失** |
| 富媒体消息（code / diff / preview / file / task_status） | 只有 `text` | **功能缺失** |
| 产物预览与编辑（iframe + Monaco + 版本链） | 完全没有 | **功能缺失** |
| 上下文连续（pin 消息） | 表里有 `pinned` 字段但无 UI/API | **功能缺失** |
| @ mention | 表里有 `mentions` 字段但无 UI/路由 | **功能缺失** |
| 部署发布（P2） | 完全没有 | **P2 不在本期** |
| 多端支持（P2） | 仅 Web | **P2 不在本期** |
| AI 协作沉淀（30% 权重） | 骨架已建（`ai-collab/`） | **持续填充** |

**重构核心思路**：

1. **保留**：BFF / Adapter 抽象 / 单写者 WS / 单一真源 reducer / SQLite 持久化 / W1 测试集 —— 这些都是设计正确、可往上长的资产。
2. **改造**：Conversation Service（加群聊语义）、消息内容渲染（从纯文本 → 富媒体卡片）、前端布局（二栏 → 三栏）。
3. **新增**：`server/orchestrator.py`、`server/artifact.py`、`server/adapters/{claude_code,codex,opencode,custom}.py`、`server/api/agents.py`、`server/api/artifacts.py`、`web/src/components/ContentRenderer/*`、Monaco 编辑器、Agent 管理页、Trace 浮窗。
4. **弃用**：终端 5 窗口启动脚本（`scripts/start_team.sh`、`src/launcher/*`）—— 作为 v1 形态归档进 `docs/v1-terminal.md`，新版不再走 AppleScript 路径。
5. **路线**：以 **5 个 Sprint（W2 → W5+B）** 把课题要求一次性兑付，每个 Sprint 必须以 ≥1 个**可演示场景** 收尾。

---

## 目录

- [1. 现状盘点](#1-现状盘点)
- [2. 与课题要求的差距矩阵](#2-与课题要求的差距矩阵)
- [3. 重构原则](#3-重构原则)
- [4. 模块级保留 / 改造 / 新增 / 弃用清单](#4-模块级保留--改造--新增--弃用清单)
- [5. 重构路线图（5 个 Sprint）](#5-重构路线图5-个-sprint)
  - [Sprint W2 · Adapter + 群聊](#sprint-w2--adapter--群聊)
  - [Sprint W3 · Orchestrator + 任务卡片](#sprint-w3--orchestrator--任务卡片)
  - [Sprint W4 · 富媒体与产物](#sprint-w4--富媒体与产物)
  - [Sprint W5 · 用户自建 Agent + 打磨](#sprint-w5--用户自建-agent--打磨)
  - [Sprint B（Buffer）· 答辩与交付物](#sprint-b-buffer--答辩与交付物)
- [6. 交付物与评分对应](#6-交付物与评分对应)
- [7. 验收路径（一键 smoke）](#7-验收路径一键-smoke)
- [8. 风险与备份方案](#8-风险与备份方案)
- [9. 立即可启动的下一步](#9-立即可启动的下一步)
- [附录 A：重构后目录结构（终态）](#附录-a重构后目录结构终态)
- [附录 B：术语与现有概念对照](#附录-b术语与现有概念对照)

---

## 1. 现状盘点

### 1.1 已交付能力（W1）

| 层 | 模块 | 状态 | 关键文件 |
| --- | --- | --- | --- |
| Web 前端 | 二栏布局（会话列表 + 消息流） + 流式渲染 + 心跳重连 + 单一真源 reducer | ✅ | `web/src/{App.tsx, components/*, stores/*, ws/client.ts}` |
| BFF | FastAPI + WS Hub（单写者池） + REST `/api/conversations` × 4 + 流式转发 + cancel | ✅ | `server/main.py`、`server/api/rest.py` |
| Adapter 层 | 抽象基类 + `MockAdapter`（按 token 切流，支持 cancel） | ✅ | `server/adapters/{base.py, mock.py, __init__.py}` |
| Service 层 | conversation / message CRUD（事务一致、显式时间戳） | ✅ | `server/services/*.py` |
| DB | 四张表：`conversation` / `conversation_member` / `message` / `agent` | ✅ | `server/db/models.py` |
| 测试 | pytest 26 + Vitest 15 + 5 套 smoke | ✅ | `server/tests/*.py`、`web/src/stores/reducer.test.ts` |
| AI 协作沉淀 | SPEC / Skills × 3 / Rules × 3 / Records × 1 | ✅ | `ai-collab/*` |

### 1.2 现有可复用资产（来自原 AgentHub v1）

| 模块 | 用途 | 路径 | 重构后用法 |
| --- | --- | --- | --- |
| Router | 机器对机器消息总线，ACK / 重试 / Trace | `src/router/*.py` | **Sprint W3 接入**，承载群聊与 Orchestrator 分派 |
| Scheduler | analyze / design / decompose / aggregate | `src/scheduler/*.py` | **Sprint W3 包装为 `server/orchestrator.py`** |
| Protocol | 消息构造与校验 | `src/protocol/*.py` | **Sprint W3 扩展** 3 个可选字段（见 §4.2） |
| State / Storage | JSONL 持久化 + 崩溃恢复 | `src/state/*.py`、`src/storage/*.py` | 复用，作为 Router 端持久化 |
| Validation | schema 校验 | `src/validation/validator.py` | 复用 |

### 1.3 待弃用 / 归档

| 模块 | 路径 | 处理 |
| --- | --- | --- |
| 终端 5 窗口启动 | `scripts/start_team.sh`、`src/launcher/*` | **归档**：迁进 `docs/v1-terminal.md`，新版不再依赖 |
| 旧 README 主体 | `README.md` 半部分仍写 v1 | **重写** README，把 v1 内容降级为"历史形态"折叠章节 |
| `src/cli/team.py`（75 KB） | CLI 命令面板 | 保留但不再作为主入口；新版主入口是 BFF + Web |

---

## 2. 与课题要求的差距矩阵

> 用"必须 / 应该 / 可以"标注课题要求强度（M / S / C，对应 MoSCoW）。

| # | 课题要求 | 强度 | 现状 | 重构动作 | 计划 Sprint |
| --- | --- | --- | --- | --- | --- |
| 1 | IM 三栏布局：会话列表 / 消息流 / 侧栏 | M | 仅二栏 | 前端拆 `Sidebar/`，新增 `TaskPanel` + `ArtifactPanel` + `MemberPanel` | **W2** |
| 2 | 新建对话时选择 Agent | M | 模态可建，但只能选 mock | 新建会话模态读取 `/api/agents`，多选 → 写 `conversation_member` | **W2** |
| 3 | 单聊 1v1 与单个 Agent 对话 | M | ✅ 但只对 Mock | 接入 ≥1 个真 Adapter（Claude/Codex/OpenCode 任选一） | **W2** |
| 4 | 群聊：多 Agent 在同一会话 | M | DB 支持，BFF/前端无 | BFF 按 `mentions` 多路 fan-out；前端按 sender 渲染不同头像 | **W2** |
| 5 | @ mention 提示器 | M | 无 | 前端 Composer 加 `MentionPopover` + 后端按 `mentions` 路由 | **W2** |
| 6 | Orchestrator 自动拆任务 + 分派 | M | 无 | 新建 `server/orchestrator.py`，包装 `src/scheduler/scheduler.py` | **W3** |
| 7 | 任务进度卡片（subtasks 实时更新） | M | 无 | 消息 `content_type = task_status` + `task_update` WS 事件 | **W3** |
| 8 | 富媒体消息：text / code / diff / preview / file | M | 仅 text | 前端 `ContentRenderer/`，后端 `card_type` 字段、JSON 校验 | **W4** |
| 9 | 内联代码块（复制、应用） | M | 无 | `CodeBlock.tsx`，`react-markdown` + `rehype-highlight` | **W4** |
| 10 | Diff 卡片（before / after） | M | 无 | `DiffCard.tsx` + Monaco `DiffEditor` | **W4** |
| 11 | 网页预览卡片（iframe） | M | 无 | `PreviewCard.tsx`，BFF `/preview/{artifact_id}/...` 静态托管 | **W4** |
| 12 | 文件附件（上传 / 下载） | S | 无 | `POST /api/upload` + `FileCard.tsx` | **W4** |
| 13 | 产物预览与编辑（Monaco） | M | 无 | `ArtifactEditor.tsx`，落 `artifact` 表 + 版本链 | **W4** |
| 14 | 对话式局部修改（圈选改） | S | 无 | Monaco 选区 → 浮动按钮 → 引用注入 Composer | **W5** |
| 15 | 上下文连续 + pin 消息 | M | DB 支持，UI 无 | 消息气泡右键菜单 pin / unpin，pin 列优先注入到 prompt | **W5** |
| 16 | 用户自建 Agent（对话式） | M | 无 | `POST /api/agents`、`AgentManage.tsx`、`CustomAgentAdapter` | **W5** |
| 17 | 多 Agent 接入（≥2 类外部） | M | 无 | Claude（W2）、Codex / OpenCode（W3 至少一种） | **W2 + W3** |
| 18 | 重新生成 / 复制代码 / 一键应用 Diff | S | 无 | 气泡操作菜单 | **W4** |
| 19 | 可观测：trace 时序图 | S | Router 已有 `/trace`，前端无 | `TraceViewer.tsx` + Mermaid | **W5** |
| 20 | 部署发布（P2） | C | 无 | **不在本期范围**，仅在文档里留章节 | — |
| 21 | 多端（P2） | C | 无 | **不在本期范围** | — |
| 22 | AI 协作规范沉淀（30% 权重） | M | 骨架已搭 | 每个 Sprint 必产 ≥1 份 record + ≥1 份 skill | 持续 |

**关键判定**：MoSCoW 中标 **M**（17 项）必须本期兑付；**S**（5 项）尽量兑付；**C**（2 项）演进路线留口、不投入实现。

---

## 3. 重构原则

> 这一段以"反例 + 正解"形式写。每条都是 W1 已经踩过坑、或者从课题要求直接反推的硬约束。

### P-1 · 协议优先（先 SPEC，再代码）

- **反例**：W1 Day3 一开始想"先加个字段试试"，结果改完发现协议泄漏到 4 层。
- **正解**：任何"新事件 / 新消息类型 / 新字段"必须先在 `ai-collab/SPEC.md` 写一段 EARS 验收，再开始改代码。
- 落点：`ai-collab/SPEC.md` 是行为契约的**唯一权威**。

### P-2 · 单聊不绕 Router，群聊必走 Router

- **反例**：把单聊也强行走 Router，链路长、延迟高、调试复杂。
- **正解**：
  - 单聊：`BFF → Adapter → BFF`（W1 现有路径）。
  - 群聊 / @Orchestrator：`BFF → Router → Orchestrator → 多 Adapter → Router → BFF`。
- 落点：`server/main.py` 的 `_handle_send_message` 路由分支化。

### P-3 · Adapter 五条契约（来自 `ai-collab/rules/adapter.mdc`）

1. 无状态。
2. 流式 yield，不允许整段返回。
3. 取消是 `return`，不是 `raise`。
4. 错误也要 yield 出 `error` chunk，不要 `raise`。
5. 注册到工厂，不要在 `main.py` 里 import。

> 新增任何 Adapter（Claude / Codex / OpenCode / Custom）都必须过这 5 条 + `ai-collab/skills/new-adapter.md` Step 5 的 5 类单测。

### P-4 · 富媒体消息的 schema 集中管理

- **反例**：每加一类卡片就在前端 + 后端各自硬编码 type。
- **正解**：
  - 前端：`web/src/types.ts` 定义 `MessageContent` 联合类型。
  - 后端：`server/protocol/content.py`（新建）用 Pydantic v2 校验 `content` JSON。
  - 二者按 `card_type` 枚举字段一一对应；新增类型必须**同时**改两边 + 加一个 reducer 单测。
- 落点：`ai-collab/skills/new-message-type.md` 已经有 SOP，按它走。

### P-5 · 产物是一等公民

- **反例**：把代码塞进消息 `content.code`，导致大代码刷整屏 + 无版本回溯。
- **正解**：所有"可被预览 / 编辑 / 下载"的对象必须落 `artifact` 表，消息 `content` 里只放 `artifact_id` + 预览元数据。
- 落点：`server/services/artifact.py`、`server/artifacts/`（FS）、`docs/ARCHITECTURE.md §5.7`。

### P-6 · 任何"AI 协作可沉淀"的瞬间，立刻沉淀

- **反例**：W1 R-B-3 那种"flush 前 created_at 是 None"的坑，如果不写进 rules，下次还会踩。
- **正解**：每写完一个 Sprint，复盘必须产出 ≥1 条新 rule / ≥1 个新 skill / ≥1 份 record。
- 落点：`ai-collab/records/YYYYMMDD-Wx.md`。

### P-7 · 单文件 ≤ 250 行，超了就拆

- 已写进 `ai-collab/rules/frontend.mdc` R-F-8 / 隐含在后端实践里。
- 重构期间新写的 Python / TS 文件**都**适用。
- 例外：`server/main.py` 当前 449 行，需要在 W2 拆出 `server/ws.py`（事件分发） + `server/handlers/*.py`（每类 ClientEvent 一个文件）。

### P-8 · 可演示优先于完整覆盖

- 每个 Sprint 必须有 1 个**端到端可演示场景**（写 demo 脚本 + 录屏占位）。
- "全特性 80% 但没法演" 不如"主线 60% 但能跑通"。
- 落点：每个 Sprint 在 §5 给出 **Demo 场景** 段落。

---

## 4. 模块级保留 / 改造 / 新增 / 弃用清单

### 4.1 后端（`server/`）

| 文件 / 目录 | 现状 | 重构动作 | Sprint |
| --- | --- | --- | --- |
| `server/main.py` | 449 行，事件 dispatch + WS Hub + handler 全部在一起 | **拆分**：保留 `app` 与 lifespan；事件 dispatch → `server/ws.py`；每个 handler → `server/handlers/*.py` | W2-D1 |
| `server/handlers/send_message.py` | 不存在 | **新增**：根据是否带 `mentions` 路由到 single / group 路径 | W2 |
| `server/handlers/join.py` | 不存在 | **新增**：抽离 W1 既有 join 逻辑 | W2-D1 |
| `server/handlers/cancel.py` | 不存在 | **新增**：抽离 W1 既有 cancel 逻辑 | W2-D1 |
| `server/handlers/mention.py` | 不存在 | **新增**：按 mentions 列表 fan-out 给多个 Adapter | W2 |
| `server/orchestrator.py` | 不存在 | **新增**：包装 `src/scheduler/scheduler.py`，状态机见 §5 W3 | W3 |
| `server/router_client.py` | 不存在 | **新增**：异步 HTTP 客户端，对接 `src/router/router.py` 的 REST | W3 |
| `server/protocol/content.py` | 不存在 | **新增**：Pydantic 校验 6 类消息 content schema | W4-D1 |
| `server/services/artifact.py` | 不存在 | **新增**：artifact CRUD + 版本链 | W4 |
| `server/services/agent.py` | 不存在 | **新增**：agent CRUD（用户自建 Agent） | W5 |
| `server/services/task.py` | 不存在 | **新增**：task CRUD（subtask 状态机） | W3 |
| `server/api/rest.py` | 4 个端点 | **扩展**：新增 `/api/agents`、`/api/artifacts`、`/api/upload`、`/api/trace/{message_id}` | W3 / W4 / W5 |
| `server/api/preview.py` | 不存在 | **新增**：`/preview/{artifact_id}/...` 静态托管 | W4 |
| `server/db/models.py` | 4 张表 | **扩展**：新增 `artifact`、`task` 两张表 + 索引 | W3 / W4 |
| `server/db/seed.py` | 仅 mock + demo conv | **扩展**：注入 Claude / Codex / Orchestrator 三个内置 Agent | W2 / W3 |
| `server/adapters/base.py` | ✅ | 保留 | — |
| `server/adapters/mock.py` | ✅ | 保留作为 CI 离线测试用 | — |
| `server/adapters/claude_code.py` | 不存在 | **新增**：Anthropic Messages API + SSE | W2 |
| `server/adapters/codex.py` | 不存在 | **新增**：OpenAI Chat Completions / Responses API | W3 |
| `server/adapters/opencode.py` | 不存在 | **新增**：OpenCode 后端 HTTP | W3（可降级到 W5） |
| `server/adapters/custom.py` | 不存在 | **新增**：通用 OpenAI 兼容 + user-defined system_prompt | W5 |

### 4.2 复用 / 扩展的旧代码（`src/`）

| 模块 | 改动 | Sprint |
| --- | --- | --- |
| `src/router/*` | **零改动**直接复用 | W3 |
| `src/scheduler/*` | **零改动**包装为 Orchestrator | W3 |
| `src/protocol/builders.py` | **小扩展**：构造函数加 3 个可选字段 `conversation_id` / `card_type` / `artifact_id`（默认 None） | W3 |
| `src/protocol/enums.py` | **小扩展**：新增 `CardType` 枚举：`text/code/diff/preview/file/task_status` | W3 |
| `src/validation/validator.py` | **同步更新**：放行 3 个新字段 | W3 |
| `src/launcher/*` | **归档**，新版不调用 | W2-D1 |
| `scripts/start_team.sh` | **归档**到 `scripts/legacy/`，新版用 `scripts/dev.ps1` | W2-D1 |

### 4.3 前端（`web/src/`）

| 文件 / 目录 | 现状 | 重构动作 | Sprint |
| --- | --- | --- | --- |
| `App.tsx` | 二栏（260 + 1fr） | **改造**为三栏（260 + 1fr + 320），中栏可独占（窄屏） | W2 |
| `components/ConversationListPanel.tsx` | 仅展示 | **扩展**：右键菜单（pin / archive） + 搜索框 | W5 |
| `components/MessagePanel.tsx` | 仅渲染文本 | **拆分**：内层换 `<MessageStream>`，bubble 内容由 `<ContentRenderer>` 分派 | W4 |
| `components/MessageBubble.tsx` | 仅 text | **重写**：根据 `content.type` 调用 `ContentRenderer/*` | W4 |
| `components/ContentRenderer/TextBubble.tsx` | 不存在 | **新增** | W4-D1 |
| `components/ContentRenderer/CodeBlock.tsx` | 不存在 | **新增**：`rehype-highlight` + 复制按钮 | W4 |
| `components/ContentRenderer/DiffCard.tsx` | 不存在 | **新增**：Monaco `DiffEditor` | W4 |
| `components/ContentRenderer/PreviewCard.tsx` | 不存在 | **新增**：iframe + 缩略图 | W4 |
| `components/ContentRenderer/FileCard.tsx` | 不存在 | **新增** | W4 |
| `components/ContentRenderer/TaskStatusCard.tsx` | 不存在 | **新增**：订阅 `task_update` 事件，subtask 状态条 | W3 |
| `components/Composer.tsx` | 纯文本输入 | **扩展**：`@` 触发 `MentionPopover`、附件按钮、引用条 | W2 / W4 |
| `components/MentionPopover.tsx` | 不存在 | **新增** | W2 |
| `components/Sidebar/TaskPanel.tsx` | 不存在 | **新增**：当前会话的任务列表 | W3 |
| `components/Sidebar/ArtifactPanel.tsx` | 不存在 | **新增**：会话内所有 artifact 缩略图列表 | W4 |
| `components/Sidebar/MemberPanel.tsx` | 不存在 | **新增**：群聊成员列表 + 在线状态 | W2 |
| `components/AgentPicker.tsx` | 不存在 | **新增**：新建会话 / 群聊邀请用 | W2 |
| `components/ArtifactEditor.tsx` | 不存在 | **新增**：全屏 Monaco 编辑 + 保存新版本 | W4 |
| `components/TraceViewer.tsx` | 不存在 | **新增**：Mermaid 渲染 trace | W5 |
| `pages/AgentManage.tsx` | 不存在 | **新增**：自建 Agent 表单 | W5 |
| `stores/useChatStore.ts` | ✅ | 保留，按需添加 `taskMap` / `artifactMap` 切片 | W3 / W4 |
| `stores/reducer.ts` | ✅ | **扩展**：新增 `task_update` / `artifact_ready` 两个 case | W3 / W4 |

### 4.4 文档与协作沉淀（`ai-collab/` + `docs/`）

| 文件 | 现状 | 重构动作 |
| --- | --- | --- |
| `ai-collab/SPEC.md` | W1 已完成 6 个 Feature；W2-W4 仅占位 | 每个 Sprint 启动**前**先补完 Feature 验收（Acceptance Criteria） |
| `ai-collab/skills/new-adapter.md` | ✅ | 持续填充，W2 接 Claude 时回填一段真实片段 |
| `ai-collab/skills/new-message-type.md` | ✅ | W4 接 Diff / Preview 时验证 + 修订 |
| `ai-collab/skills/orchestrator-flow.md` | 不存在 | **新增**：状态机 + 失败降级 SOP（W3） |
| `ai-collab/skills/artifact-lifecycle.md` | 不存在 | **新增**：版本链、回滚、删除（W4） |
| `ai-collab/rules/orchestrator.mdc` | 不存在 | **新增**：群聊主持人约束（W3） |
| `ai-collab/records/*` | 仅 W1 一份 | 每个 Sprint 收尾产出一份 + 至少 2 段真实协作片段 |
| `docs/ARCHITECTURE.md` | ✅ 已对齐课题 | 每个 Sprint 同步更新 §5–§7 |
| `docs/REBUILD_PLAN.md` | 本文件 | 是规划文档；执行过程中如发生方向变化，**回填 changelog**，不偷改 |
| `docs/v1-terminal.md` | 不存在 | **新增**：v1 终端形态归档，附迁移说明 |

---

## 5. 重构路线图（5 个 Sprint）

> 时间假设：每个 Sprint = 1 工作周（5 个工作日 + 1 个 buffer 日）。
> 每个 Sprint 必须在最后一天交付一个**可录屏的端到端 demo**。
> 所有 Sprint 共享一条铁律：**任何代码变更前，先在 `ai-collab/SPEC.md` 写完验收**。

### 总体甘特

```
   W1 (Done)         W2              W3              W4              W5              B(Buffer)
   骨架 ✅            Adapter+群聊    Orch+任务卡片    富媒体+产物      自建Agent+打磨   答辩交付
   |----已完成----|---真Adapter----|--Router接入---|--Diff/Preview-|--AgentManage-|---视频+稿---|
```

---

### Sprint W2 · Adapter + 群聊

**目标**：让 AgentHub 第一次真正"和外部 Agent 聊起来"，并支持 N 个 Agent 同处一个会话。

#### W2 必交付（M）

| # | 任务 | 验收 | 文件 |
| --- | --- | --- | --- |
| W2-T1 | **拆分 `server/main.py`**：抽 `server/ws.py` + `server/handlers/*.py` | 行数 ≤ 250；pytest 仍 26 全绿 | `server/main.py`、`server/ws.py`、`server/handlers/{join,send_message,cancel}.py` |
| W2-T2 | **接入 `ClaudeCodeAdapter`** | 单元 5 类 + smoke 跑通；按 token 流式；cancel 即时停 | `server/adapters/claude_code.py`、`server/tests/test_adapter_claude.py` |
| W2-T3 | **群聊语义：mentions fan-out** | `send_message.mentions=["agent_claude","agent_codex"]` 触发 N 路并行 Adapter 调用，按到达顺序写消息 | `server/handlers/send_message.py`、`server/services/conversation.py` |
| W2-T4 | **前端 `MentionPopover`** | Composer 输入 `@` 弹出会话成员列表，键盘上下 + Enter 选择，写入 `mentions` 字段 | `web/src/components/MentionPopover.tsx`、`web/src/components/Composer.tsx` |
| W2-T5 | **三栏布局 + `MemberPanel`** | 群聊会话右栏显示成员；单聊隐藏 | `web/src/App.tsx`、`web/src/components/Sidebar/MemberPanel.tsx` |
| W2-T6 | **新建会话支持多 Agent** | 模态可多选 Agent，写入 `conversation_member` | `web/src/components/NewConversationDialog.tsx`、`server/api/rest.py` |

#### W2 应交付（S）

- 把 `ai-collab/skills/new-adapter.md` 接 Claude 那次的真实协作片段回填进去。
- 新增 `ai-collab/records/20260528-W2.md`。

#### W2 SPEC 待补（启动 Sprint 时第一件事）

- F-W2-1 多 Agent 群聊 fan-out
- F-W2-2 Claude Adapter 接入
- F-W2-3 @mention 提示器
- F-W2-4 三栏布局与成员侧栏

#### W2 Demo 场景

> "在群聊里 `@Claude` 和 `@Mock` 同时让他俩写一段 Python 排序代码，看到两份回复按到达顺序串行打字出现。"

---

### Sprint W3 · Orchestrator + 任务卡片

**目标**：兑付课题最关键的"主 Agent 协调器自动拆解任务 → 分派 → 聚合"。

#### W3 必交付（M）

| # | 任务 | 验收 | 文件 |
| --- | --- | --- | --- |
| W3-T1 | **Router 接入** | BFF 启动时连本机 8765 Router；群聊消息按 `to=[agent_x]` 投递成功；`GET /trace/<id>` 能拉回完整链路 | `server/router_client.py`、`server/main.py` |
| W3-T2 | **`server/orchestrator.py`** | 接到 `@Orchestrator` 消息后：3 s 内推 `task_status` 卡片；按 `complexity.score()` 拆 ≥2 子任务；并发 dispatch；全 done 后 aggregate | `server/orchestrator.py`、`server/services/task.py` |
| W3-T3 | **`task` 表 + 状态机** | `pending → running → done/failed`；每次状态变化推 `task_update` WS 事件 | `server/db/models.py`、`server/services/task.py` |
| W3-T4 | **前端 `TaskStatusCard`** | 订阅 `task_update`，subtask 进度条实时跳动；点击子任务跳到对应消息 | `web/src/components/ContentRenderer/TaskStatusCard.tsx`、`web/src/stores/reducer.ts` |
| W3-T5 | **Sidebar `TaskPanel`** | 当前会话的任务列表 + 折叠子任务 | `web/src/components/Sidebar/TaskPanel.tsx` |
| W3-T6 | **CodexAdapter（或 OpenCodeAdapter）任一** | 5 类单测 + smoke | `server/adapters/codex.py` 或 `opencode.py` |
| W3-T7 | **`src/protocol/builders.py` 扩展 3 字段** | 现有 fixtures 全部仍能 validate（向后兼容） | `src/protocol/*` |

#### W3 应交付（S）

- `ai-collab/skills/orchestrator-flow.md`：状态机图 + 失败降级 SOP。
- `ai-collab/rules/orchestrator.mdc`：群聊主持人约束（含"failed 子任务最多重试 1 次"等）。
- `ai-collab/records/20260604-W3.md`。

#### W3 SPEC 待补

- F-W2-1 → 在 §阶段 W2 → 提升为完整 EARS（W1 文档里只有节选）。
- F-W3-1 Orchestrator 任务卡片
- F-W3-2 任务并发 fan-out + 失败降级
- F-W3-3 第二个真 Adapter（Codex / OpenCode）

#### W3 Demo 场景

> "群聊里 `@Orchestrator 做一个支持 OAuth 的登录页 + 后端 API`，看到任务卡片 3 s 内出现，Claude 和 Codex 在群里并发干活，进度条动，最后 Orchestrator 发汇总卡片。"

---

### Sprint W4 · 富媒体与产物

**目标**：把课题"产物预览与编辑"的所有 M 项一次性交付。

#### W4 必交付（M）

| # | 任务 | 验收 | 文件 |
| --- | --- | --- | --- |
| W4-T1 | **消息 content schema 集中校验** | Pydantic 校验 6 类卡片；非法 content 返回 422 | `server/protocol/content.py`、`server/services/message.py` |
| W4-T2 | **`artifact` 表 + 服务** | CRUD + 版本链；本地 FS 落盘 | `server/db/models.py`、`server/services/artifact.py`、`server/api/artifacts.py` |
| W4-T3 | **`POST /api/upload`** | multipart 上传 → 写 artifact → 返回 `artifact_id` | `server/api/rest.py` |
| W4-T4 | **`/preview/{artifact_id}/...` 静态托管** | iframe 能加载 HTML/JS/CSS 包 | `server/api/preview.py` |
| W4-T5 | **前端 `ContentRenderer/*` 5 个组件** | 6 类消息全部能正确渲染 | `web/src/components/ContentRenderer/*.tsx` |
| W4-T6 | **`ArtifactEditor.tsx`（Monaco）** | 全屏编辑 + 保存为新版本 + 自动生成 Diff 卡片回插会话 | `web/src/components/ArtifactEditor.tsx` |
| W4-T7 | **Sidebar `ArtifactPanel`** | 会话所有产物列表，点击展开预览 | `web/src/components/Sidebar/ArtifactPanel.tsx` |
| W4-T8 | **Adapter 产物输出 chunk** | Adapter 在产出代码时 yield `artifact` chunk，BFF 落盘 + 发 `artifact_ready` | `server/adapters/*.py`、`server/main.py` |

#### W4 应交付（S）

- 一键应用 Diff：DiffCard 按钮 → BFF 复制 artifact → 触发新 preview。
- 重新生成 / 复制代码气泡操作。
- `ai-collab/skills/artifact-lifecycle.md`。
- `ai-collab/records/20260611-W4.md`。

#### W4 SPEC 待补

- F-W4-1 消息卡片 schema 严格化
- F-W4-2 artifact 版本链
- F-W4-3 Monaco 编辑 + 一键应用 Diff
- F-W4-4 Preview iframe

#### W4 Demo 场景

> "群聊里让 Claude 写 Login.tsx，消息流里出现 Preview 卡片（iframe），点开 Monaco 改样式，保存自动生成 Diff 卡片，点'应用'后预览即时刷新。"

---

### Sprint W5 · 用户自建 Agent + 打磨

**目标**：兑付剩余 M 项（自建 Agent、pin、trace、圈选改）+ 拉满产品感。

#### W5 必交付（M）

| # | 任务 | 验收 | 文件 |
| --- | --- | --- | --- |
| W5-T1 | **`POST /api/agents`** | 创建用户自建 Agent，写 DB；返回带 capabilities 的 agent 对象 | `server/api/rest.py`、`server/services/agent.py` |
| W5-T2 | **`CustomAgentAdapter`** | 任意 OpenAI 兼容 endpoint + system_prompt + 用户指定 model | `server/adapters/custom.py` |
| W5-T3 | **`pages/AgentManage.tsx`** | 表单：名称 / 头像 / system_prompt / capabilities / API 配置；左侧"我的 Agent"列表 | `web/src/pages/AgentManage.tsx` |
| W5-T4 | **pin 消息** | 气泡右键 → pin/unpin；pin 消息优先注入到 prompt 上下文 | `web/src/components/MessageBubble.tsx`、`server/services/message.py` |
| W5-T5 | **会话搜索 + 归档** | 左栏搜索框；右键菜单 archive；archived 默认隐藏 | `web/src/components/ConversationListPanel.tsx` |

#### W5 应交付（S）

| # | 任务 | 验收 |
| --- | --- | --- |
| W5-T6 | **`TraceViewer.tsx`（Mermaid）** | 任意 Agent 消息右上角"查看 trace"，浮窗渲染时序图 |
| W5-T7 | **圈选改** | Monaco 选区 → 浮动按钮 → 引用片段进 Composer |
| W5-T8 | **多 Agent 投票模式（创新点）** | `/vote 这两个方案哪个好` → 所有在场 Agent 各发一次意见 → 用户决策 |
| W5-T9 | **Agent 头像悬浮卡（创新点）** | hover 显示能力标签 + 最近任务 + token 用量 |

#### W5 SPEC 待补

- F-W5-1 用户自建 Agent
- F-W5-2 Pin 消息长上下文
- F-W5-3 Trace 时序图
- F-W5-4 圈选改对话式编辑
- F-W5-5 多 Agent 投票（创新）

#### W5 Demo 场景

> "在 AgentManage 页面用对话式创建一个'前端 Code Reviewer'，回到群聊里 @ 他，他能基于现有 Login.tsx 给出 review 评论；点 trace 看完整链路；圈选 review 评论里的某段代码 → 在聊天里描述改法。"

---

### Sprint B (Buffer) · 答辩与交付物

**目标**：把所有 Sprint 的成果打包为评分材料 + 录制 3 分钟 demo。

#### B 必交付（M）

| # | 任务 | 产物 |
| --- | --- | --- |
| B-T1 | **3 分钟 demo 视频** | 录屏 + 字幕；脚本见 `COURSE_PROPOSAL.md §八` |
| B-T2 | **答辩 deck（10–15 页）** | 问题陈述 / 产品定位 / 架构 / 创新点 / 评分自评 |
| B-T3 | **README 重写** | 把 v1 内容降级为折叠章节；v2 一键启动放最上面 |
| B-T4 | **完整 ai-collab/ 检视** | 5 份 records / 8 份 skills / ≥4 份 rules / SPEC 全绿 |
| B-T5 | **Trace 时序图 × 3** | 单聊 / 群聊 / Orchestrator 拆解 各一张 |
| B-T6 | **"吃自己狗粮"叙事** | `ai-collab/records/dogfooding.md`：用 AgentHub 自己开发 AgentHub 的群聊截图集 |

---

## 6. 交付物与评分对应

> 参考 `COURSE_PROPOSAL.md §八` 的评分维度。

| 维度 | 权重 | 交付物 | 落点 |
| --- | --- | --- | --- |
| **AI 协作能力** | 30% | `ai-collab/` 整目录（SPEC + Skills + Rules + Records） | 每个 Sprint 必产 1 份 record；持续填充 |
| **功能完整度** | 25% | W2–W5 全部 M 项 + ≥1/3 的 S 项 | 见 §5 各 Sprint 验收 |
| **生成效果质量** | 20% | ≥2 个真实 Adapter 跑通 demo（Claude / Codex 或 OpenCode） | W2 / W3 |
| **代码理解度** | 15% | `docs/ARCHITECTURE.md` 持续更新 + Mermaid trace 时序图 | W3 后定稿、W5 加 trace |
| **创新与产品感** | 10% | 投票模式 / 头像悬浮卡 / "吃自己狗粮"叙事 / 圈选改 / Trace 可视化 | W5 + B |

---

## 7. 验收路径（一键 smoke）

每个 Sprint 末必须**追加**对应的 smoke 脚本，且 `smoke_all.py` 一键跑通：

```text
server/tests/
├── smoke_w1.py   ✅ Day1-Day5 总验收（W1 已交付）
├── smoke_w2.py   📌 W2 末追加：群聊 fan-out + Claude Adapter
├── smoke_w3.py   📌 W3 末追加：@Orchestrator 全链路（含 Router）
├── smoke_w4.py   📌 W4 末追加：上传 → 产物 → 预览 → 编辑 → Diff
├── smoke_w5.py   📌 W5 末追加：自建 Agent + Pin + Trace
└── smoke_all.py  📌 Sprint B 串联所有
```

铁律：**新增任何 ServerEvent / ClientEvent 类型 → 必须先在 smoke_wX.py 加一个 case 让它失败 → 再写代码让它通过**。

---

## 8. 风险与备份方案

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| Claude / Codex Token 申请被延误 | W2-T2 / W3-T6 卡住 | **备份**：用 OpenRouter / 自有 OpenAI key 顶上；`CustomAgentAdapter` 提前到 W2 写 |
| Router 改造比预期复杂 | W3-T1 推迟 | **备份**：先用"BFF 直连多 Adapter"做群聊（绕过 Router），W4 再回填 Router；课题验收只看现象 |
| Monaco DiffEditor 性能差 | W4-T6 卡住 | **备份**：先用 `react-diff-viewer-continued`，能演示 Diff 即可 |
| W4 工作量超预期（5 个新组件） | 整体推迟 1 周 | **备份**：把 `FileCard` / `ArtifactPanel` 降到 S 级；优先保 code / diff / preview / task_status |
| `src/scheduler/*` 包装为 Orchestrator 时遇到隐藏耦合 | W3-T2 卡住 | **备份**：在 BFF 实现一个**最小 Orchestrator**（只跑 analyze + decompose + 静态 dispatch），不依赖 scheduler 的复杂状态机 |
| AI 协作沉淀流于形式 | 直接拿不到 30% | 每个 Sprint 收尾前 1 天**强制留 0.5 天**写 record + skill + rule，code lock |
| 答辩前未跑通 smoke_all | demo 翻车 | Sprint B Day1 就跑 `smoke_all.py`，留 4 天修复 |

---

## 9. 立即可启动的下一步

> 优先级降序，每一项都列出"明确动作"，便于直接喂给 AI 执行。

1. **【今天 / D0】** 审核本规划：操作员确认 §3 重构原则、§5 Sprint 划分；如有异议，先改本文件再启动。
2. **【今天 / D0】** 把 v1 终端形态归档：
   - 新建 `docs/v1-terminal.md`，复制 `README.md` 中 v1 部分。
   - 修改 `README.md` 把 v1 章节折叠成 `<details>`。
   - 移动 `scripts/start_team.sh` 等到 `scripts/legacy/`。
3. **【W2-D1】** 在 `ai-collab/SPEC.md` 写完 F-W2-1 ~ F-W2-4 的完整 EARS。
4. **【W2-D1】** 拆 `server/main.py`（W2-T1）。**这是后续所有 Sprint 的前置**，必须先做。
5. **【W2-D2】** 启动 W2-T2 接 Claude；如 token 没就绪，先用 `CustomAgentAdapter` + OpenRouter 替代。
6. **【W2-D3 ~ D4】** 跑通群聊 fan-out（W2-T3 + W2-T4 + W2-T5）。
7. **【W2-D5】** 写 `ai-collab/records/20260528-W2.md` + 录 W2 demo 短视频（≤1 分钟）。

---

## 附录 A：重构后目录结构（终态）

> 用 `★` 标记 **本期新增**，`◇` 标记**本期改造**，无标记表示**复用 / 保留**。

```
AgentHub/
├── src/                                  # v1 后端（机器对机器）
│   ├── router/                           # 复用 0 改动
│   ├── scheduler/                        # 复用 0 改动
│   ├── protocol/                         # ◇ 小扩展 3 字段
│   ├── state/  storage/  validation/     # 复用 0 改动
│   ├── api/                              # 复用
│   ├── cli/team.py                       # 保留（不再作为主入口）
│   └── launcher/                         # ⛔ 归档
│
├── server/                               # v2 BFF
│   ├── main.py                           # ◇ 拆薄，只剩 app + lifespan
│   ├── ws.py                             # ★ WS 端点 + 事件分发
│   ├── handlers/                         # ★ 每类 ClientEvent 一个文件
│   │   ├── join.py
│   │   ├── send_message.py
│   │   ├── cancel.py
│   │   └── mention.py
│   ├── orchestrator.py                   # ★ 包装 src/scheduler/
│   ├── router_client.py                  # ★ 连 src/router/ 的 HTTP 客户端
│   ├── protocol/
│   │   └── content.py                    # ★ Pydantic 校验 6 类卡片
│   ├── api/
│   │   ├── rest.py                       # ◇ 端点扩充
│   │   ├── preview.py                    # ★ /preview/{artifact_id}
│   │   └── upload.py                     # ★ multipart 上传
│   ├── services/
│   │   ├── conversation.py               # ◇ +群聊语义
│   │   ├── message.py                    # 复用
│   │   ├── agent.py                      # ★
│   │   ├── task.py                       # ★
│   │   └── artifact.py                   # ★
│   ├── adapters/
│   │   ├── base.py                       # 复用
│   │   ├── mock.py                       # 复用（CI 离线）
│   │   ├── claude_code.py                # ★ W2
│   │   ├── codex.py                      # ★ W3
│   │   ├── opencode.py                   # ★ W3
│   │   └── custom.py                     # ★ W5
│   ├── db/
│   │   ├── models.py                     # ◇ +artifact +task
│   │   └── seed.py                       # ◇ +Claude/Codex/Orchestrator
│   └── tests/
│       ├── test_db.py / test_rest.py     # ◇ 持续扩
│       ├── smoke_w1.py                   # 复用
│       ├── smoke_w2.py …  smoke_w5.py    # ★
│       └── smoke_all.py                  # ★
│
├── web/                                  # v2 前端
│   ├── src/
│   │   ├── App.tsx                       # ◇ 二栏 → 三栏
│   │   ├── pages/
│   │   │   ├── Chat.tsx                  # ★（W2 抽离）
│   │   │   ├── AgentManage.tsx           # ★ W5
│   │   │   └── Settings.tsx              # ★ W5（最小）
│   │   ├── components/
│   │   │   ├── ConversationListPanel.tsx # ◇
│   │   │   ├── MessagePanel.tsx          # ◇
│   │   │   ├── MessageBubble.tsx         # ◇
│   │   │   ├── Composer.tsx              # ◇
│   │   │   ├── MentionPopover.tsx        # ★ W2
│   │   │   ├── AgentPicker.tsx           # ★ W2
│   │   │   ├── ArtifactEditor.tsx        # ★ W4
│   │   │   ├── TraceViewer.tsx           # ★ W5
│   │   │   ├── ContentRenderer/         # ★ W4
│   │   │   │   ├── TextBubble.tsx
│   │   │   │   ├── CodeBlock.tsx
│   │   │   │   ├── DiffCard.tsx
│   │   │   │   ├── PreviewCard.tsx
│   │   │   │   ├── FileCard.tsx
│   │   │   │   └── TaskStatusCard.tsx
│   │   │   └── Sidebar/                 # ★
│   │   │       ├── TaskPanel.tsx
│   │   │       ├── ArtifactPanel.tsx
│   │   │       └── MemberPanel.tsx
│   │   ├── stores/
│   │   │   ├── useChatStore.ts           # ◇ +taskMap +artifactMap
│   │   │   └── reducer.ts                # ◇ +task_update +artifact_ready
│   │   ├── ws/client.ts                  # 复用
│   │   └── api/client.ts                 # ◇ 端点扩
│   ├── package.json                      # ◇ +monaco +mermaid +react-markdown
│   └── vitest.config.ts
│
├── ai-collab/                            # AI 协作沉淀（30% 权重）
│   ├── SPEC.md                           # ◇ 持续填充
│   ├── README.md
│   ├── skills/
│   │   ├── new-adapter.md                # ◇ W2 回填
│   │   ├── new-message-type.md           # ◇ W4 回填
│   │   ├── debug-ws-flow.md              # 复用
│   │   ├── orchestrator-flow.md          # ★ W3
│   │   └── artifact-lifecycle.md         # ★ W4
│   ├── rules/
│   │   ├── frontend.mdc                  # 复用
│   │   ├── backend.mdc                   # 复用
│   │   ├── adapter.mdc                   # 复用
│   │   └── orchestrator.mdc              # ★ W3
│   └── records/
│       ├── 20260521-W1.md                # ✅
│       ├── 20260528-W2.md                # ★
│       ├── 20260604-W3.md                # ★
│       ├── 20260611-W4.md                # ★
│       ├── 20260618-W5.md                # ★
│       └── dogfooding.md                 # ★（持续追加）
│
├── docs/
│   ├── ARCHITECTURE.md                   # ◇ 持续更新
│   ├── REBUILD_PLAN.md                   # ★ 本文（如果决定挪到 docs/）
│   ├── v1-terminal.md                    # ★ v1 形态归档
│   ├── design.md                         # 复用
│   └── main-members-workflow.md          # 复用
│
├── scripts/
│   ├── dev.ps1                           # ★ Windows 一键启动
│   ├── dev.sh                            # ★ macOS/Linux 一键启动
│   └── legacy/start_team.sh              # ⛔ 归档
│
├── COURSE_PROPOSAL.md
├── REBUILD_PLAN.md                       # ★ 本文件
└── README.md                             # ◇ 重写
```

---

## 附录 B：术语与现有概念对照

> 用户视角的"IM 概念" ⇄ 后端实际名字。

| 用户看到的 | 后端实际名字 | 文件 |
| --- | --- | --- |
| 联系人 | `agent` 行 | `server/db/models.py:Agent` |
| 群聊主持人 / 群主 | `Orchestrator`（id 固定 `agent_orchestrator`） | `server/orchestrator.py` |
| 会话 | `conversation` 行 | `server/db/models.py:Conversation` |
| 群聊 / 单聊 | `conversation.type ∈ {single, group}` | 同上 |
| 群成员 | `conversation_member` 行 | `server/db/models.py:ConversationMember` |
| 聊天历史 | `message` 表按 `conversation_id + created_at` 查询 | `server/services/conversation.py:list_messages` |
| 群里 @某人 | `message.mentions` JSON 数组 | `server/db/models.py:Message.mentions` |
| 任务进度卡片 | `message.content_type = "task_status"` + `task` 表 | `server/services/task.py` |
| 网页预览 | `message.content_type = "preview"` + `artifact` 表 | `server/services/artifact.py` |
| Diff 视图 | `message.content_type = "diff"` + 两个 `artifact_id` | 同上 |
| "对方正在输入..." | WS `agent_typing` 事件 | `server/main.py:_run_agent_reply` |
| "正在写代码..." | WS `task_update` 事件（`status=running`） | `server/services/task.py`（W3 起） |
| 重新生成 | 客户端 `cancel` + 新建一条 send_message（带 `reply_to`） | W4 实现 |
| 查看链路 | `GET /api/trace/{message_id}` → Mermaid | `server/api/rest.py`（W5 起） |

---

> **本文件状态**：草案。
> **下一步**：等操作员审核 → 在本文件底部追加 changelog → 开始 Sprint W2-D1。
> **修改约定**：任何对本规划的实质修改（删 Sprint / 改优先级 / 删 M 项）必须在文末写一行 changelog；细节修订（错别字、补语料）不必。

## Changelog

- 2026-05-21 v1.0 初稿（基于 W1 复盘 + `docs/ARCHITECTURE.md` + `COURSE_PROPOSAL.md`）。
- 2026-05-21 D0 执行：
  - 新建 `docs/v1-terminal.md`，搬运 README 中全部 v1 内容并补 v1→v2 迁移对照表。
  - `scripts/{start_team.sh, stop_team.sh, status_team.sh, test_full.sh, test_messaging.py, iterm2/, terminal/}` → `scripts/legacy/`，附 `scripts/legacy/README.md` 说明不应再作主入口。
  - 重写 `README.md`：v2 信息（一句话定位 / W1 进度 / 5 Sprint 路线 / 一键启动 / 文档导航）置顶；v1 折叠为 `<details>` 块，指向 `docs/v1-terminal.md`。
  - 留痕：`ai-collab/records/20260521-D0-archive-v1.md`。
