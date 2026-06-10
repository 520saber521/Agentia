# AgentHub 技术架构文档

> 版本：v1.0（2026-05-21）
> 适用对象：研发团队、答辩评委、二次贡献者
> 关联文档：
> - 课题方案：`COURSE_PROPOSAL.md`
> - 主从协作协议：`docs/main-members-workflow.md`
> - 原有终端版设计：`docs/design.md`
> - 角色提示词：`prompts/agent_*.txt`

---

## 目录

- [0. 摘要（TL;DR）](#0-摘要tldr)
- [1. 背景与目标](#1-背景与目标)
- [2. 系统范围与约束](#2-系统范围与约束)
- [3. 设计原则](#3-设计原则)
- [4. 总体架构](#4-总体架构)
- [5. 分层职责详细设计](#5-分层职责详细设计)
- [6. 数据模型](#6-数据模型)
- [7. 通信协议](#7-通信协议)
- [8. 核心流程时序](#8-核心流程时序)
- [9. 关键模块设计](#9-关键模块设计)
- [10. 跨切面关注点](#10-跨切面关注点)
- [11. 技术栈选型](#11-技术栈选型)
- [12. 目录结构](#12-目录结构)
- [13. 部署架构](#13-部署架构)
- [14. 演进路线](#14-演进路线)
- [15. 风险与权衡](#15-风险与权衡)
- [附录 A：与现有 AgentHub 模块对照表](#附录-a与现有-agenthub-模块对照表)
- [附录 B：术语表](#附录-b术语表)

---

## 0. 摘要（TL;DR）

AgentHub v2 是在现有"终端窗口 + 本地 Router"多 Agent 协作后端之上，**保留底层消息总线与调度器、重写交互外壳为 IM 聊天前端**的产品形态升级。

整体由 7 层构成：

```
Web 前端  →  BFF/Gateway  →  Conversation Service ─┐
                          ↘                        ├─→ Artifact Store
                            AgentHub Router  ──→ Orchestrator ─→ Adapter ─→ 外部 Agent API
```

- **复用度**：`src/router/`、`src/scheduler/`、`src/protocol/`、`src/state/`、`src/storage/` 等核心模块零改动或最小扩展。
- **新建工作量集中在**：`web/`（React 前端）、`server/`（BFF + 会话服务 + Adapter 层 + 产物管理）。
- **关键创新点**：`AgentAdapter` 抽象层、群聊语义化的 `Orchestrator`、富媒体消息卡片（Diff / Preview / TaskStatus）、"吃自己狗粮"的协作叙事。

---

## 1. 背景与目标

### 1.1 课题背景

课题要求构建**对话式多 Agent 协作平台**，以 IM（即时通讯）为交互范式，支撑：

- 多 Agent 实时协同（Claude Code / Codex / OpenCode / 自建 Agent）。
- 任务自动拆解、并行执行、结果聚合。
- 富媒体消息（代码、Diff、网页预览、文件附件、任务进度卡片）。
- AI 协作规范的沉淀与复用（Spec / Skills / Rules / Records）。

### 1.2 项目现状

`AgentHub` 现有版本是**本地多终端窗口形态**：MAIN/A/B/C/D 五个角色各占一个 Terminal/iTerm2/tmux 窗口，通过本地 HTTP Router 完成消息路由与可靠投递。其后端能力（Router、Scheduler、Protocol、Storage、State）已基本完备，但缺少 Web 前端与会话级抽象。

### 1.3 目标

| 维度 | 目标 |
|---|---|
| 交互形态 | 飞书 / 微信式三栏 IM 界面 |
| 协议复用 | 复用 AgentHub 现有 review/assign/done/fail/clarify/answer 协议族 |
| 实时性 | 端到端 WebSocket，流式 Token 推送延迟 < 200 ms |
| 多 Agent | 至少接入 Claude Code、Codex、OpenCode 三种外部 Agent + 1 类自建 Agent |
| 富媒体 | 文本、代码块、Diff、Preview、文件、TaskStatus 六类消息 |
| 可观测 | 任意一条消息可在 UI 上回溯到 trace 时序图 |
| 离线 | 所有产物落本地 FS，断网仍可浏览历史 |

### 1.4 非目标

- 不在本期实现多机集群部署（保留架构口，但不投入实现）。
- 不实现端到端加密、复杂权限模型（演示场景单租户）。
- 不替代任何 Agent 平台本身的能力，AgentHub 只做编排与通信。

---

## 2. 系统范围与约束

### 2.1 范围（In Scope）

- Web 端：会话列表、消息流、富媒体卡片、Monaco 编辑器、产物预览。
- BFF：WebSocket 长连接、协议翻译、鉴权、流式转发。
- 会话服务：Conversation / Message / Agent / Artifact / Task 五张核心表的 CRUD 与查询。
- Orchestrator：包装现有 scheduler，提供群聊语义的任务拆解与聚合。
- Adapter 层：统一 4+ 类 Agent 后端的对接。
- 产物管理：本地 FS + 元数据表 + iframe 预览。

### 2.2 不在范围（Out of Scope）

- 移动端 App、桌面 App。
- 多机分布式 Router、跨地域消息总线。
- 复杂 RBAC、SSO、审计合规模块。
- 模型微调、训练 / 评测平台。

### 2.3 约束（Constraints）

- 后端语言保持 **Python 3.10+**（与现有代码栈一致；提案中标注 3.8+，新模块可放宽到 3.10+ 以使用 `match`、`|` 类型语法）。
- Router 端口、消息协议字段保持**向后兼容**；新字段通过扩展位添加，不破坏现有 `body_encoding=json` 约定。
- 演示环境单机运行；存储默认 SQLite + 本地 FS。
- 不引入 Kafka / Redis / etcd 等外部依赖以保持"开箱即跑"。

---

## 3. 设计原则

| # | 原则 | 含义 |
|---|---|---|
| P1 | **最大化复用** | 现有 `router/scheduler/protocol/state/storage/validation` 模块作为既成事实，不重写、只包装。 |
| P2 | **协议优先** | 任何一条新消息类型先定义 schema，再写实现；Router 透传扩展字段。 |
| P3 | **流式优先** | 所有 Agent 输出按 token / chunk 流式推送，不允许"等完整再发"。 |
| P4 | **机器/人解耦** | Router 服务"机器对机器"，BFF 才面向"人"；不让前端直连 Router。 |
| P5 | **离线友好** | 产物、消息、Trace 全部落本地 JSONL/FS，断网可恢复。 |
| P6 | **可观测** | 每条消息可追溯发起者、链路、耗时；UI 上可一键查看 trace。 |
| P7 | **Adapter 收口** | 接入新 Agent 等价于"写一个新文件实现 `AgentAdapter`"，不污染上层。 |
| P8 | **AI 协作可沉淀** | 开发过程中产生的 Skill / Rule / Spec 视为一类交付物，而非附属。 |

---

## 4. 总体架构

### 4.1 架构总览图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      L1 · Web 前端 (React + TS + Vite)                  │
│  ┌──────────┬──────────────────────┬──────────────────────────────┐    │
│  │ 会话列表  │  消息流 (虚拟列表)    │  侧栏: 任务 / 产物 / Agent     │    │
│  │  单聊    │  · 文本气泡            │  · 任务进度卡片                │    │
│  │  群聊    │  · 代码块 + 复制       │  · 产物预览 (iframe)           │    │
│  │  搜索    │  · Diff / Preview     │  · @ 提示器                    │    │
│  └──────────┴──────────────────────┴──────────────────────────────┘    │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ WebSocket (主) + HTTPS (REST / 上传)
┌───────────────────────────────▼─────────────────────────────────────────┐
│                    L2 · BFF / Gateway (FastAPI + WS)                    │
│  · 鉴权 / Session 管理                                                  │
│  · WS 长连接池 (每用户一条)                                              │
│  · 协议翻译：ChatMessage  ⇌  AgentHub Protocol Message                  │
│  · 流式分片转发 (token chunk → ws frame)                                │
└──────┬───────────────────────────────────────────┬──────────────────────┘
       │ (聊天 CRUD / 鉴权 / 上传)                  │ (Agent 通信)
       ▼                                           ▼
┌──────────────────┐                ┌──────────────────────────────────┐
│ L3 Conversation  │                │     L4 · AgentHub Router         │
│       Service    │                │      (复用现有 src/router/*)     │
│  · 会话元数据    │                │  REST: /messages /acks /inbox    │
│  · 消息持久化    │                │        /presence /trace          │
│  · pin / 搜索    │                │  · 投递 / 重试 / ACK / Trace    │
│  · SQLite/PG     │                │  · JSONL 持久化 + 崩溃恢复       │
└──────────────────┘                └──────┬───────────────────────────┘
                                           │
                ┌──────────────────────────┼──────────────────────────┐
                │                          │                          │
                ▼                          ▼                          ▼
       ┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
       │ L5 Orchestrator  │      │   L6 Adapter     │      │   L6 Adapter     │
       │   (主持人 Bot)   │      │  ClaudeCode      │      │     Codex        │
       │ 包装 scheduler/  │      │ ─ HTTP/SDK 直连  │      │ ─ HTTP/SDK 直连  │
       │  decomposer      │      └──────────────────┘      └──────────────────┘
       └──────────────────┘                │                          │
                                           └────────────┬─────────────┘
                                                        ▼
                                            ┌──────────────────────┐
                                            │ L7 · Artifact Store  │
                                            │  代码 / 网页 / 文件   │
                                            │  本地 FS + 元数据表   │
                                            └──────────────────────┘
```

### 4.2 关键架构决策（ADR 摘录）

| 决策 | 选择 | 理由 |
|---|---|---|
| 前后端通信主通道 | **WebSocket**（双向 + 流式）；REST 仅做幂等 CRUD 与文件上传 | 流式 token 推送必须 server push；HTTP 长轮询延迟与开销不可接受 |
| 是否让前端直连 Router | **不直连**，强制走 BFF | Router 是机器对机器协议，无鉴权、无会话语义、无协议翻译 |
| 会话存储 | **SQLite（默认）**，可选 PostgreSQL | 单机演示足够；SQLAlchemy 抽象后切换零成本 |
| Orchestrator 实现 | **包装现有 scheduler**，不重写 | 现有 analyze/design/decompose/aggregate 已完备 |
| Adapter 形态 | **HTTP/SDK 直连**，不再启动终端窗口 | 终端窗口形态无法被 BFF 编程化捕获流式输出 |
| 产物存储 | **本地 FS + 元数据表**，每产物有版本号与父版本 | 支持 Diff、回滚、离线浏览 |
| 实时推送 | WebSocket 主通道；SSE 作为只读旁路（可选） | WS 已足够，SSE 仅作降级 |

---

## 5. 分层职责详细设计

### 5.1 L1 · Web 前端（新建，工作量最大）

**技术栈**

| 类别 | 选择 |
|---|---|
| 框架 | React 18 + TypeScript |
| 构建 | Vite 5 |
| 样式 | TailwindCSS + shadcn/ui |
| 状态 | Zustand（轻量、可分片） |
| 路由 | React Router v6 |
| 数据获取 | TanStack Query（REST 缓存） + 自研 WS 中间层 |
| 编辑器 | `@monaco-editor/react`（含 DiffEditor） |
| Markdown | `react-markdown` + `rehype-highlight` + `remark-gfm` |
| 虚拟滚动 | `@tanstack/react-virtual` |
| 实时 | 原生 `WebSocket` + 自研重连 / 心跳 |

**目录结构**

```
web/src/
├── pages/
│   ├── Chat.tsx           # 主聊天页（三栏布局）
│   ├── AgentManage.tsx    # Agent 管理页
│   └── Settings.tsx
├── components/
│   ├── ConversationList.tsx
│   ├── MessageStream.tsx          # 虚拟列表 + 滚动控制
│   ├── MessageBubble.tsx
│   ├── ContentRenderer/
│   │   ├── TextBubble.tsx
│   │   ├── CodeBlock.tsx          # 含复制 / 全屏 / 应用按钮
│   │   ├── DiffCard.tsx           # Monaco DiffEditor
│   │   ├── PreviewCard.tsx        # iframe + 缩略图
│   │   ├── FileCard.tsx
│   │   └── TaskStatusCard.tsx     # 任务进度，订阅 task_update
│   ├── ArtifactEditor.tsx         # 全屏 Monaco
│   ├── AgentPicker.tsx
│   ├── MentionPopover.tsx         # @ 提示
│   └── Sidebar/
│       ├── TaskPanel.tsx
│       ├── ArtifactPanel.tsx
│       └── MemberPanel.tsx
├── stores/
│   ├── conversation.ts
│   ├── message.ts
│   ├── artifact.ts
│   ├── task.ts
│   └── ws.ts
├── ws/
│   ├── client.ts                  # WS 客户端 + 重连
│   └── handlers.ts                # ServerEvent 分发
└── api/                           # REST 客户端
```

**关键交互能力**

- 流式消息：`stream_chunk` 帧到达后增量拼接到对应气泡，避免整条消息抖动。
- 虚拟滚动：长会话（> 1000 条）保持 60fps；新消息自动停留在底部或维持当前阅读位置。
- 圈选改：Monaco 选中代码 → 浮动按钮"在聊天中描述修改" → 将选中代码作为引用插入输入框。
- 任务卡片：订阅 `task_update` WS 事件，进度条实时更新。
- 可观测：每条 Agent 消息可点击"查看 trace"打开 Mermaid 时序图浮窗。

### 5.2 L2 · BFF / Gateway 层（新建，薄层）

**职责**

1. **连接管理**：维护用户 ↔ 服务端的 WS 长连接池；按 `user_id` 索引，支持多端登录推送广播。
2. **鉴权**：登录后下发 JWT；WS 握手阶段校验 `Sec-WebSocket-Protocol` 中的 token。
3. **协议翻译**：
   - 前端 `ChatMessage` → AgentHub `Protocol Message`（填充 `v/session/epoch/seq/from/to/type/action/body`）。
   - Router 投递事件 / Agent 流式输出 → `ServerEvent` WS 帧。
4. **流式转发**：Adapter 的 `AsyncIterator[dict]` 输出按 chunk 包装为 `stream_chunk` 帧；保持顺序、保证最终 `message_done`。
5. **限流与配额**：单用户单 Agent 并发上限、token 用量统计（与 Adapter 配合）。
6. **文件上传**：multipart 上传到 `Artifact Store`，返回 `artifact_id` 供后续消息引用。

**模块组织**

```
server/
├── main.py            # FastAPI app + 路由注册
├── ws.py              # WebSocket endpoint + 连接池
├── auth.py            # JWT / Session
├── translator.py      # ChatMessage ⇌ Protocol Message
├── stream.py          # 流式分片与背压
└── upload.py          # 文件上传
```

**为什么 BFF 必须存在**：

- Router 仅做 agent-to-agent 路由，没有"用户"概念，无法直接给浏览器返回流式数据。
- 前端协议要面向人（含 UI 富媒体卡片），后端协议要面向机器（含 `seq/epoch/corr/ack` 等）。中间必须有一层适配。

### 5.3 L3 · Conversation Service（新建）

**职责**

- 五张核心表（`conversation` / `conversation_member` / `message` / `agent` / `artifact` / `task`）的 CRUD。
- 消息分页查询（按 `conversation_id + created_at` 倒序、游标分页）。
- 全文检索（SQLite FTS5 / PG `to_tsvector`，可选）。
- 置顶 / 归档 / pin 消息。
- 与 AgentHub Router 的双向 ID 映射：`message.agenthub_msg_id ↔ Router.message.id`。

**接口风格**：内部 Python API（FastAPI router），不暴露到前端的接口需通过 BFF 收口。

**模块组织**

```
server/
├── conversation.py        # 会话与成员 CRUD
├── message.py             # 消息 CRUD + 查询
├── agent.py               # Agent 注册表
├── task.py                # 任务管理（与 AgentHub task 同步）
└── db/
    ├── engine.py
    ├── models.py          # SQLAlchemy ORM
    └── migrations/        # Alembic
```

### 5.4 L4 · AgentHub Router（复用）

**复用范围（零改动或最小扩展）**

| 模块 | 用途 | 改动 |
|---|---|---|
| `src/router/router.py` | HTTP 路由器主体、ACK、重试、Trace | 0 |
| `src/router/store.py` | 内存索引 + JSONL 持久化 | 0 |
| `src/router/presence.py` | 在线状态 / 心跳 | 0 |
| `src/protocol/builders.py` | 协议消息构造 | **小扩展**：新增 `card_type` / `conversation_id` / `artifact_id` 三个可选字段 |
| `src/protocol/enums.py` | 枚举常量 | 新增 `card_type` 枚举 |
| `src/state/recovery.py` | 崩溃恢复 | 0 |
| `src/validation/validator.py` | schema 校验 | 同步更新校验规则 |

**对外接口（已存在）**

| Method | Path | 说明 |
|---|---|---|
| POST | `/messages` | 提交一条消息（异步路由到目标 inbox） |
| GET | `/inbox/{agent}` | 拉取并 ACK accepted |
| POST | `/acks` | 客户端主动 ACK |
| GET | `/presence` | 在线状态 |
| GET | `/trace/{message_id}` | 链路追踪 |

### 5.5 L5 · Orchestrator（复用 + 包装）

**包装策略**：在 `server/orchestrator.py` 提供一个面向群聊的"主持人 Bot"，内部调用现有 `src/scheduler/scheduler.py` 的 `analyze → design → schedule → execute → aggregate`。

**触发条件**

- 群聊中显式 `@Orchestrator`。
- 用户在群聊发起的消息被 `analyzer.classify_complexity()` 判定为"复杂任务"（依据复杂度分 / 子任务数 / 是否跨能力）。

**对外输出**

- 群聊里以**任务卡片消息（`type:'task_status'`）**形式发布拆解结果与进度。
- 每个子任务通过 Router `POST /messages` 投递 `assign` 给目标 Agent。
- 收到所有子任务 `done` 后通过 `aggregator.aggregate()` 在群里发"汇总卡片"。

**状态机**

```
[idle] ─(收到 @Orchestrator)→ [analyzing]
[analyzing] ─(complex)→ [designing] ─→ [decomposing] ─→ [scheduling]
[scheduling] ─→ [executing] ─(全部 done)→ [aggregating] ─→ [done]
[executing] ─(任意子任务 fail)→ [recovering] ─(重试 / 退化)→ [executing] | [failed]
```

**与现有 scheduler 的对照**

| 群聊语义 | scheduler 既有能力 | 文件 |
|---|---|---|
| 任务拆解 | `decomposer.decompose()` / `enhanced_decomposer.py` | `src/scheduler/decomposer.py` |
| 复杂度判定 | `complexity.score()` | `src/scheduler/complexity.py` |
| 契约生成 | `contracts.generate()` | `src/scheduler/contracts.py` |
| 设计方案 | `design.draft()` | `src/scheduler/design.py` |
| 调度执行 | `scheduler.schedule()` | `src/scheduler/scheduler.py` |
| 结果汇总 | `aggregator.aggregate()` | `src/scheduler/aggregator.py` |
| 协作策略 | `collaboration.py` | `src/scheduler/collaboration.py` |

### 5.6 L6 · Agent Adapter 层（新建·关键创新）

**抽象基类（`server/adapters/base.py`）**

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator, List, Optional

class AgentAdapter(ABC):
    """统一 Agent 适配器接口"""

    @abstractmethod
    async def send(
        self,
        messages: List[dict],
        tools: Optional[List[dict]] = None,
        artifacts_context: Optional[dict] = None,
        stream: bool = True,
    ) -> AsyncIterator[dict]:
        """流式返回 yield {type: 'text'|'tool_call'|'artifact'|'error', ...}"""
        ...

    @abstractmethod
    def capabilities(self) -> List[str]:
        """能力声明: ['code', 'web', 'image', 'tool_use'...]"""
        ...

    async def cancel(self, message_id: str) -> None:
        """可选：用户取消正在生成的消息"""
```

**内置实现**

| Adapter | 后端 | 实现要点 |
|---|---|---|
| `ClaudeCodeAdapter` | Anthropic Messages API | SSE 流式解析，tool_use 透传 |
| `CodexAdapter` | OpenAI Responses / GPT-5 API | function_call → tool_call 映射 |
| `OpenCodeAdapter` | OpenCode 开源后端 | 本地或远端 HTTP |
| `CustomAgentAdapter` | 通用 OpenAI 兼容 | 用户配置 base_url + api_key + system_prompt |
| `MockAdapter` | 离线 | 仅 W1 链路打通用 |

**注册中心**

```python
ADAPTER_REGISTRY: dict[str, type[AgentAdapter]] = {
    "claude_code": ClaudeCodeAdapter,
    "codex": CodexAdapter,
    "opencode": OpenCodeAdapter,
    "custom": CustomAgentAdapter,
    "mock": MockAdapter,
}

def build_adapter(agent_row: AgentORM) -> AgentAdapter:
    cls = ADAPTER_REGISTRY[agent_row.adapter_type]
    return cls(config=json.loads(agent_row.config))
```

### 5.7 L7 · Artifact Store（新建）

**职责**：保存所有由 Agent 产出的"可被预览 / 编辑 / 下载"的二进制或文本对象，并维护版本链。

**存储布局**

```
<workspace>/.agenthub/artifacts/
├── art_001/
│   ├── meta.json        # {id, type, title, parent_id, created_by, ...}
│   ├── v1/
│   │   └── content.tsx
│   └── v2/
│       └── content.tsx
└── art_002/
    └── ...
```

**支持类型**：`code_file` / `web_page`（HTML/JS/CSS 包） / `doc` / `ppt` / `zip` / `image`。

**Preview**：BFF 为 `web_page` 类型产物挂载只读静态服务（如 `GET /preview/{artifact_id}/...`），前端通过 iframe 引用。

---

## 6. 数据模型

### 6.1 ER 关系

```
   user ──< conversation_member >── conversation ──< message
                                          │             │
                                          │             ├── artifact (优 attachment)
                                          │             └── task (group 触发)
                                          │
                                          └──< agent (作为成员)
```

### 6.2 DDL（SQLite，PG 兼容）

```sql
-- 6.2.1 会话
CREATE TABLE conversation (
    id              TEXT PRIMARY KEY,        -- conv_<uuid>
    title           TEXT NOT NULL,
    type            TEXT NOT NULL,           -- 'single' | 'group'
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL,
    pinned          INTEGER DEFAULT 0,
    archived        INTEGER DEFAULT 0,
    last_msg_preview TEXT,
    owner_user_id   TEXT NOT NULL
);

-- 6.2.2 会话成员
CREATE TABLE conversation_member (
    conversation_id TEXT NOT NULL,
    member_id       TEXT NOT NULL,           -- user_xxx 或 agent_xxx
    member_type     TEXT NOT NULL,           -- 'user' | 'agent'
    role            TEXT,                    -- 'orchestrator' | 'worker' | 'observer'
    joined_at       INTEGER NOT NULL,
    PRIMARY KEY (conversation_id, member_id)
);

-- 6.2.3 消息
CREATE TABLE message (
    id              TEXT PRIMARY KEY,        -- msg_<uuid>
    conversation_id TEXT NOT NULL,
    sender_id       TEXT NOT NULL,
    sender_type     TEXT NOT NULL,
    content_type    TEXT NOT NULL,           -- 'text'|'code'|'diff'|'preview'|'file'|'task_status'
    content         TEXT NOT NULL,           -- JSON (见 7.3)
    reply_to        TEXT,                    -- 引用消息 id
    mentions        TEXT,                    -- JSON array
    pinned          INTEGER DEFAULT 0,
    artifact_id     TEXT,
    agenthub_msg_id TEXT,                    -- 与 Router id 双向映射
    created_at      INTEGER NOT NULL
);
CREATE INDEX idx_msg_conv ON message(conversation_id, created_at DESC);
CREATE INDEX idx_msg_agenthub ON message(agenthub_msg_id);

-- 6.2.4 Agent 注册表
CREATE TABLE agent (
    id              TEXT PRIMARY KEY,        -- agent_<uuid>
    name            TEXT NOT NULL,
    avatar          TEXT,
    adapter_type    TEXT NOT NULL,           -- 'claude_code'|'codex'|'opencode'|'custom'|'mock'
    config          TEXT NOT NULL,           -- JSON
    capabilities    TEXT,                    -- JSON array
    owner_user_id   TEXT,                    -- NULL 表示系统内置
    created_at      INTEGER NOT NULL
);

-- 6.2.5 产物
CREATE TABLE artifact (
    id              TEXT PRIMARY KEY,        -- art_<uuid>
    type            TEXT NOT NULL,
    title           TEXT,
    file_path       TEXT,
    preview_url     TEXT,
    version         INTEGER DEFAULT 1,
    parent_id       TEXT,                    -- 上一版本 artifact_id
    conversation_id TEXT,
    created_by      TEXT,
    created_at      INTEGER NOT NULL
);
CREATE INDEX idx_art_conv ON artifact(conversation_id, created_at DESC);

-- 6.2.6 任务（与 AgentHub task_id 一致）
CREATE TABLE task (
    id              TEXT PRIMARY KEY,        -- 对应 Router 的 task_id
    conversation_id TEXT NOT NULL,
    parent_msg_id   TEXT,
    title           TEXT NOT NULL,
    status          TEXT NOT NULL,           -- 'pending'|'running'|'done'|'failed'
    assignee        TEXT,
    progress        INTEGER DEFAULT 0,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL
);
CREATE INDEX idx_task_conv ON task(conversation_id, updated_at DESC);
```

### 6.3 ID 规则

| 实体 | 形态 | 生成时机 |
|---|---|---|
| `conversation.id` | `conv_<uuid4>` | 创建会话 |
| `message.id` | `msg_<uuid4>` | BFF 接收消息时 |
| `message.agenthub_msg_id` | `<session>-<epoch>-<seq>` | Router 自动生成 |
| `agent.id` | `agent_<uuid4>` | 注册 Agent 时 |
| `artifact.id` | `art_<uuid4>` | Adapter 产出 / 用户上传 |
| `task.id` | `task_<uuid4>` 或沿用 Router 的 task_id | Orchestrator 拆解时 |

---

## 7. 通信协议

### 7.1 三层协议关系

```
┌────────────────────────────────────────────────────────────┐
│  前端 ⇌ BFF   :   ChatMessage / ClientEvent / ServerEvent  │ ← WebSocket
├────────────────────────────────────────────────────────────┤
│  BFF ⇌ Router :  AgentHub Protocol Message (v1)            │ ← HTTP
├────────────────────────────────────────────────────────────┤
│  BFF ⇌ Adapter : OpenAI-style messages + 流式 chunk          │ ← Python AsyncIterator
└────────────────────────────────────────────────────────────┘
```

### 7.2 WebSocket 协议（Client ⇌ Server）

```typescript
// Client → Server
type ClientEvent =
  | { type: 'auth', token: string }
  | { type: 'join', conversation_id: string }
  | { type: 'leave', conversation_id: string }
  | { type: 'send_message',
      conversation_id: string,
      content: MessageContent,
      mentions?: string[],
      reply_to?: string }
  | { type: 'typing', conversation_id: string }
  | { type: 'cancel', message_id: string }
  | { type: 'ping' };

// Server → Client
type ServerEvent =
  | { type: 'auth_ok', user_id: string }
  | { type: 'message_created', message: Message }
  | { type: 'stream_chunk', message_id: string, delta: string }
  | { type: 'message_done', message_id: string, final_content: MessageContent }
  | { type: 'agent_typing', agent_id: string, conversation_id: string }
  | { type: 'task_update', task: Task }
  | { type: 'artifact_ready', artifact: Artifact, message_id: string }
  | { type: 'presence', agent_id: string, online: boolean }
  | { type: 'error', code: string, message: string, message_id?: string }
  | { type: 'pong' };
```

**可靠性**

- 客户端：心跳 25 s，连续 2 次 `pong` 缺失触发重连；指数退避 1s/2s/5s/10s/30s。
- 服务端：每条 `stream_chunk` 携带 `seq`（消息内单调），客户端按 `seq` 排序拼接。
- 断线重连后客户端发 `join + last_known_message_id`，服务端补发缺失消息。

### 7.3 ChatMessage `content` Schema

```typescript
type MessageContent =
  | { type: 'text', text: string }
  | { type: 'code', language: string, code: string, filename?: string }
  | { type: 'diff',
      filename: string,
      before_artifact_id: string,
      after_artifact_id: string,
      stats: { additions: number, deletions: number } }
  | { type: 'preview',
      preview_url: string,
      title: string,
      thumbnail?: string,
      artifact_id: string }
  | { type: 'file', filename: string, size: number, url: string, mime: string }
  | { type: 'task_status',
      task_id: string,
      title: string,
      subtasks: Array<{
        id: string,
        title: string,
        assignee: string,
        status: 'pending' | 'running' | 'done' | 'failed',
        progress?: number
      }> };
```

### 7.4 AgentHub Protocol Message（复用 + 扩展）

字段保持 `docs/design.md §7` 既有定义；本期**新增三个可选字段**：

| 字段 | 类型 | 含义 |
|---|---|---|
| `conversation_id` | string | 关联会话 ID，便于 BFF 反查与广播 |
| `card_type` | enum | `text/code/diff/preview/file/task_status` 之一；为空兼容老协议 |
| `artifact_id` | string | 关联产物 ID |

Router 透传扩展字段，不做强校验；BFF 与 Adapter 解析。

### 7.5 Adapter 输出 Chunk Schema

```python
# Adapter.send() yield 的每个 chunk
ChunkText      = {"type": "text",     "delta": str}
ChunkToolCall  = {"type": "tool_call","name": str, "args": dict, "call_id": str}
ChunkArtifact  = {"type": "artifact", "artifact": {...}}  # 产物落盘后回写
ChunkUsage     = {"type": "usage",    "input_tokens": int, "output_tokens": int}
ChunkError     = {"type": "error",    "code": str, "message": str}
ChunkDone      = {"type": "done"}
```

BFF 负责把上述 chunk 映射成 WS `stream_chunk` / `artifact_ready` / `message_done` 事件。

---

## 8. 核心流程时序

### 8.1 流程 A：单聊发送消息（最短路径）

```
User           Web            BFF             Adapter         DB
 │              │              │                │              │
 │ 输入"写一个登录页" │             │                │              │
 ├─────────────►│              │                │              │
 │              │ WS send_message│                │              │
 │              ├─────────────►│ ① 写 message(content=text) │   │
 │              │              ├──────────────────────────────►│
 │              │              │ ② adapter.send(messages=[...]) │
 │              │              ├───────────────►│              │
 │              │              │                │ 调 Anthropic │
 │              │              │ WS agent_typing│              │
 │              │◄─────────────┤                │              │
 │              │              │                │ 流式 chunk   │
 │              │              │◄───────────────┤              │
 │              │ WS stream_chunk│              │              │
 │              │◄─────────────┤                │              │
 │              │              │ ③ 完成: 产物落盘 + 写 DB        │
 │              │              ├──────────────────────────────►│
 │              │ WS message_done│                            │
 │              │◄─────────────┤                              │
```

**说明**：单聊路径**不一定经过 Router**——简单单聊由 BFF 直接调 Adapter，链路短、延迟低。只有群聊或涉及多 Agent 协作时才走 Router。

### 8.2 流程 B：群聊 @Orchestrator + 多 Agent 协作

```
User → "@Orchestrator 做一个支持 OAuth 的登录页 + 后端 API"
   │
   ▼
BFF 写 message 表 ── POST /messages ──► AgentHub Router
                                          to=["agent_orchestrator"]
                                          conversation_id=conv_001
   │
   ▼
Router 投递到 Orchestrator inbox
   │
   ▼
Orchestrator (包装 scheduler):
   1. analyze:   complexity.score = high
   2. design:    生成契约 (前端组件接口 + 后端 API schema)
   3. decompose:
        ├─ 子任务 1: 前端登录页    → assign to agent_claude
        └─ 子任务 2: 后端 OAuth API → assign to agent_codex
   4. 把 "task_status 卡片" 作为群聊消息 push 回会话 (经 BFF WS)
   │
   ▼
Router 并行投递 assign 消息给 Claude / Codex
   │
   ▼
各 Adapter 调用外部 API → 流式产出 → BFF 转发为群聊消息
   │   (前端实时看到群聊里两个 Agent 依次/并行发言)
   ▼
两个子任务 done → Orchestrator.aggregate() → 群里发"汇总卡片"
```

### 8.3 流程 C：Diff 与代码二次编辑

```
1. Agent 产出 Login.tsx → 保存 artifact art_001 (v1)
2. 消息流插入 preview 卡片（点击全屏 Monaco）
3. 用户在 Monaco 编辑保存 → art_002 (v2, parent=art_001)
4. 用户在聊天框：圈选某段代码 → "把按钮换成圆角"
5. BFF 把 (选中片段 + 用户描述 + art_002 上下文) 打包为 prompt
6. Adapter 返回 patch → BFF 生成 art_003 (v3) 与 Diff 元数据
7. 推送 diff 卡片 (before=art_002, after=art_003)
8. 用户点"应用 Diff" → BFF 落盘 → artifact_ready → 新 preview
```

### 8.4 流程 D：崩溃恢复

```
1. BFF/Router 重启 → 触发 state/recovery.py:
     · 读取 meta/session.json
     · 读取 state/router.json → 取 last_epoch+1
     · 回放 logs/messages-<epoch>.jsonl 重建 inbox
     · 回放 state/tasks.json 重建任务状态
2. 待投递消息重新入队
3. 客户端通过 WS `join + last_known_message_id` 拉取缺失消息
4. UI 自动补齐空缺，进度卡片重新订阅 task_update
```

---

## 9. 关键模块设计

### 9.1 Adapter 抽象与扩展点

**新增一个 Agent 的 SOP**

1. 在 `server/adapters/` 下新建 `<name>.py`，继承 `AgentAdapter`。
2. 实现 `send()`：返回 `AsyncIterator[Chunk]`，注意按 token 流式 yield。
3. 实现 `capabilities()`：声明能力标签。
4. 在 `server/adapters/__init__.py` 的 `ADAPTER_REGISTRY` 注册。
5. （可选）在 `db/seed.py` 添加默认 Agent 实例。
6. 编写测试：`server/tests/test_adapter_<name>.py`，至少覆盖：流式 chunk 顺序、超时、取消、错误。

### 9.2 Orchestrator 决策器

```python
class Orchestrator:
    def __init__(self, scheduler, router_client, bff):
        self.scheduler = scheduler          # 复用 src/scheduler/scheduler.py
        self.router = router_client
        self.bff = bff

    async def handle(self, msg: ChatMessage) -> None:
        plan = self.scheduler.analyze(msg.content.text)
        if plan.complexity < THRESHOLD:
            return await self.simple_dispatch(msg, plan)

        design = self.scheduler.design(plan)
        subtasks = self.scheduler.decompose(design)

        await self.bff.push(make_task_status_card(subtasks))

        for st in subtasks:
            await self.router.post_assign(st)

        await self.wait_all_done(subtasks)
        summary = self.scheduler.aggregate(subtasks)
        await self.bff.push(make_summary_card(summary))
```

### 9.3 实时通道（WebSocket Hub）

```python
class WSHub:
    """单进程内的 WS 连接池"""
    def __init__(self):
        self._by_user: dict[str, set[WebSocket]] = defaultdict(set)
        self._by_conv: dict[str, set[WebSocket]] = defaultdict(set)

    async def join(self, ws, user_id, conv_id): ...
    async def push_to_conv(self, conv_id, event): ...
    async def push_to_user(self, user_id, event): ...
    async def broadcast(self, event): ...
```

**背压策略**：每个 WS 写入队列上限 1024；溢出时优先丢弃 `agent_typing` / `presence` 类幂等事件，保证 `stream_chunk` / `message_done` 必达。

### 9.4 产物管理与版本链

- 每次写入 artifact 生成 `art_<uuid>`，`version=parent.version+1`，`parent_id=parent.id`。
- 提供 `GET /artifacts/{id}/history`：沿 `parent_id` 回溯返回版本链。
- 删除策略：软删除 + 30 天后清理（演示期可关闭）。

### 9.5 可观测面板

- 复用 Router 已提供的 `/trace/{message_id}`。
- 前端组件 `TraceViewer.tsx`：拿到 trace JSON 后渲染 Mermaid `sequenceDiagram`。
- 每条 Agent 消息气泡右上角悬浮"查看 trace"按钮。

---

## 10. 跨切面关注点

### 10.1 鉴权与会话

- **用户登录**：邮箱 + 密码 / 演示用一键登录；下发 JWT (HS256, 7d)。
- **WS 鉴权**：握手阶段在 `Sec-WebSocket-Protocol` 携带 `bearer.<token>`；服务端校验后回 `auth_ok`。
- **API 鉴权**：所有 REST 端点要求 `Authorization: Bearer <token>`。
- **Agent 凭证**：Adapter 配置中的 API Key 在数据库**加密保存**（AES-256 + 进程环境变量主密钥）。

### 10.2 可靠性

| 关注点 | 策略 |
|---|---|
| 消息不丢 | Router JSONL append-only + delivered/accepted 双 ACK；BFF 写库成功后才回前端 |
| 重复消息 | Router 以 `id` 去重；前端按 `message_id` 幂等渲染 |
| 流式中断 | `stream_chunk.seq` 校验；缺帧触发客户端 `replay` |
| 崩溃恢复 | `state/recovery.py` 回放日志重建状态 |
| Adapter 失败 | 超时 30 s / 重试 1 次 / 失败转 `error` 消息卡片 |
| 用户取消 | `cancel` 事件中断 Adapter（依赖各 SDK 的 abort 能力） |

### 10.3 性能

| 项 | 目标 | 手段 |
|---|---|---|
| 首屏到可交互 | < 1.5 s | Vite + 路由懒加载 + Service Worker 缓存 |
| 流式延迟 (server→client) | < 200 ms | WS + chunk 立刻 flush |
| 长会话滚动 | 1000 条消息 60 fps | 虚拟列表 + 增量渲染 |
| Router 吞吐 | ≥ 500 msg/s（本地） | 现有实现已满足 |
| 并发对话 | 单机 100 路 WS | uvicorn workers=4 + uvloop |

### 10.4 安全

- API Key 加密存储；日志脱敏（自动遮蔽 `sk-*`、`AKID*`、邮箱）。
- 内容渲染：所有 Markdown / HTML 走白名单（DOMPurify）；预览 iframe 用 `sandbox="allow-scripts"` 限制能力。
- 上传校验：扩展名 + MIME + 大小（默认 10 MB）。
- CSRF：WS 用 JWT 替代 Cookie，REST 启用 SameSite=Lax。

### 10.5 可测试性

- **单元**：每个 Adapter / Router / Orchestrator 模块独立测；`MockAdapter` 用于不依赖外部 API 的 CI。
- **契约**：`fixtures/messages/*.json` 作为协议黄金样本，回归比对。
- **端到端**：Playwright 跑「发消息 → 收到流式 → 渲染卡片 → 应用 Diff」典型用户旅程。

### 10.6 国际化与可访问性

- i18n：`react-i18next`，预置 zh-CN / en-US。
- a11y：所有交互元素带 `aria-label`；色盲友好色板；键盘可达。

---

## 11. 技术栈选型

### 11.1 后端

| 类别 | 选型 | 备注 |
|---|---|---|
| Web 框架 | FastAPI 0.110+ | async 原生、WS 友好 |
| ASGI Server | uvicorn + uvloop | 性能 |
| ORM | SQLAlchemy 2.x + Alembic | |
| 数据库 | SQLite（默认）/ PostgreSQL 15+ | |
| HTTP Client | httpx (async) | Adapter 内部调用 |
| 校验 | pydantic v2 | 与 FastAPI 一体 |
| 任务编排 | 现有 `src/scheduler/*` | 复用 |
| 测试 | pytest + pytest-asyncio + httpx.AsyncClient | |
| 类型检查 | mypy / pyright | |
| 代码风格 | ruff + black | |

### 11.2 前端

| 类别 | 选型 |
|---|---|
| 框架 / 构建 | React 18 + TypeScript 5 + Vite 5 |
| 样式 | TailwindCSS 3 + shadcn/ui |
| 状态 | Zustand + TanStack Query |
| 编辑器 | @monaco-editor/react |
| Markdown | react-markdown + rehype-highlight + remark-gfm |
| 实时 | 原生 WebSocket（自研重连） |
| 路由 | React Router v6 |
| 测试 | Vitest + Testing Library + Playwright |

### 11.3 基础设施（演示用）

- 单机：本地启动 BFF + Router + 前端 dev server。
- 进程管理：`scripts/dev.ps1`（PowerShell，v2 推荐） / `scripts/legacy/start_team.sh`（macOS，v1 已归档）。
- 日志：JSONL 文件 + 控制台彩色输出；不引入 ELK。

---

## 12. 目录结构

```
AgentHub/
├── src/                            # 现有 Python 后端（基本不动）
│   ├── api/                        # 复用，可加 /v2/* 新端点
│   ├── router/                     # 复用 0 改动
│   ├── scheduler/                  # 复用，被 Orchestrator 包装
│   ├── protocol/                   # 扩展 3 个可选字段（见 7.4）
│   ├── state/
│   ├── storage/
│   └── validation/
│
├── server/                         # 【新建】 BFF / 会话服务
│   ├── main.py                     # FastAPI 入口
│   ├── ws.py                       # WebSocket 管理
│   ├── auth.py
│   ├── translator.py               # ChatMessage ⇌ Protocol Message
│   ├── conversation.py
│   ├── message.py
│   ├── agent.py
│   ├── task.py
│   ├── orchestrator.py             # 包装 scheduler
│   ├── artifact.py
│   ├── upload.py
│   ├── adapters/
│   │   ├── base.py
│   │   ├── claude_code.py
│   │   ├── codex.py
│   │   ├── opencode.py
│   │   ├── custom.py
│   │   └── mock.py
│   ├── db/
│   │   ├── engine.py
│   │   ├── models.py
│   │   └── migrations/
│   ├── tests/
│   └── requirements.txt
│
├── web/                            # 【新建】前端
│   ├── src/
│   │   ├── pages/
│   │   ├── components/
│   │   ├── stores/
│   │   ├── ws/
│   │   └── api/
│   ├── package.json
│   └── vite.config.ts
│
├── ai-collab/                      # 【新建】AI 协作规范沉淀（30% 权重）
│   ├── SPEC.md
│   ├── ARCHITECTURE.md             # 本文档的副本或软链
│   ├── skills/
│   │   ├── new-message-type.md
│   │   ├── new-adapter.md
│   │   └── debug-ws-flow.md
│   ├── rules/
│   │   ├── frontend.mdc
│   │   ├── backend.mdc
│   │   └── adapter.mdc
│   └── records/
│       └── 20260521-architecture.md
│
├── docs/                           # 现有
│   ├── design.md                   # 终端版设计（保留）
│   ├── ARCHITECTURE.md             # 本文档
│   ├── main-members-workflow.md
│   └── ...
├── prompts/
├── config/
├── fixtures/
└── README.md
```

---

## 13. 部署架构

### 13.1 开发模式（默认）

```
┌─────────────────────────────────────────────────┐
│   localhost (dev)                                │
│  ┌────────────┐  ┌─────────────┐  ┌──────────┐  │
│  │ Vite 5173  │  │ FastAPI 8788│  │ Router   │  │
│  │ web dev    │←→│  BFF + DB   │←→│ 8765     │  │
│  └────────────┘  └─────────────┘  └──────────┘  │
│         ↑                ↑                       │
│         └── WebSocket ───┘                       │
└─────────────────────────────────────────────────┘
```

启动：

```bash
# 终端 1
cd src && python -m router.router       # 端口 8765
# 终端 2
cd server && uvicorn main:app --port 8788 --reload
# 终端 3
cd web && pnpm dev
```

### 13.2 生产打包（演示）

- 前端 `pnpm build` → 静态资源由 BFF（FastAPI `StaticFiles`）一并托管。
- 单端口 8788 同时提供 HTTP + WS + 静态资源。
- Router 仍作为独立进程，进程间走 HTTP `localhost:8765`。
- 数据：`./.agenthub/*.db` + `./.agenthub/artifacts/`。

### 13.3 容器化（可选）

```yaml
# docker-compose.yml
services:
  router:
    build: ./src
    ports: ["8765:8765"]
  bff:
    build: ./server
    ports: ["8788:8788"]
    depends_on: [router]
    environment:
      - ROUTER_URL=http://router:8765
  web:
    build: ./web
    ports: ["5173:80"]
```

---

## 14. 演进路线

| 阶段 | 时长 | 关键交付 | 验收 |
|---|---|---|---|
| **W1：骨架打通** | 5 天 | 前端 ↔ BFF ↔ MockAdapter 单聊链路 + DB 三表 | 浏览器中能"发消息→收流式回复→存库" |
| **W2：AgentHub 接入 + 群聊** | 5 天 | Router 接入；Orchestrator 拆任务 + 2 个 Adapter 并行 | 一次群聊产出前后端两份代码 |
| **W3：富媒体 + 产物** | 5 天 | Diff 卡片、Preview iframe、Monaco 编辑、二次修改 | 用户能"对话式改代码" |
| **W4：打磨 + 交付物** | 5 天 | UI 美化、用户自建 Agent、Demo 视频、文档定稿 | 3 分钟视频 + 答辩稿 |
| **P2（可选）** | 后续 | 部署发布服务、移动端、版本历史可视化、多机集群 | — |

---

## 15. 风险与权衡

| 风险 | 影响 | 应对 |
|---|---|---|
| 外部 Agent API 不稳定 / 限速 | 流式输出卡顿、demo 失败 | W1 用 MockAdapter 跑通；准备录屏备份；多 Provider 兜底 |
| WebSocket 在企业代理下被阻断 | 部分演示环境不可用 | 提供 SSE 降级通道；本地演示优先 |
| 单机 SQLite 并发写瓶颈 | 高并发演示打不住 | 演示场景并发小；PG 切换路径已留 |
| 产物存储无限增长 | 磁盘占用 | 按会话 + 软删除 + 定期清理 |
| Orchestrator 拆解判断不准 | 群聊体验差 | 提供"显式 @Orchestrator + 强制拆分"开关 |
| 不同 Adapter 流式格式差异大 | 适配工作量超预期 | base 类抽象统一 chunk，差异下沉到子类 |
| AI 协作沉淀流于形式 | 30% 权重大块拿不到 | W1 起每次开发都同步写 Records；Spec/Skills/Rules 在 W2 前定型 |

---

## 附录 A：与现有 AgentHub 模块对照表

| 课题概念 | AgentHub 原概念 | 代码位置 | 处理 |
|---|---|---|---|
| IM 聊天前端 | （无） | — | **新建** `web/` |
| 消息总线 | Router | `src/router/router.py` | **复用** |
| 消息持久化 | JSONL + storage | `src/storage/*` | **复用** |
| 协议消息 | builders / enums | `src/protocol/*` | **小扩展**（3 个可选字段） |
| 主持人 | MAIN Agent | `prompts/agent_main.txt` | **包装为 Orchestrator** |
| 任务分解 | decomposer | `src/scheduler/decomposer.py` | **复用** |
| 结果聚合 | aggregator | `src/scheduler/aggregator.py` | **复用** |
| 调度执行 | scheduler | `src/scheduler/scheduler.py` | **复用** |
| 在线状态 | presence | `src/router/presence.py` | **复用** |
| 崩溃恢复 | state/recovery | `src/state/recovery.py` | **复用** |
| 协议校验 | validator | `src/validation/validator.py` | **复用** |
| 工作区配置 | scheduler.yaml | `config/scheduler.yaml` | **复用** |
| 群聊会话 | （无）任务级有 | — | **新建** Conversation 抽象 |
| Agent 接入 | 终端窗口 + AppleScript | `src/launcher/*` | **改造**为 Adapter |
| 富媒体卡片 | （无） | — | **新建** |
| 实时推送 | HTTP 长轮询 `pop_inbox` | `src/router/router.py` | **升级**为 WS |
| 产物管理 | （无） | — | **新建** Artifact Store |

---

## 附录 B：术语表

| 术语 | 定义 |
|---|---|
| **Agent** | 一个具备能力声明的 AI 单元，对应一种 Adapter 实例 |
| **Conversation** | IM 会话，可为单聊或群聊；持有成员、消息、产物 |
| **Orchestrator** | 群聊中的主持人 Bot，负责任务拆解与聚合，包装现有 scheduler |
| **Adapter** | 统一 Agent 后端访问的抽象，每种外部 AI 平台一个实现 |
| **Artifact** | 由 Agent 产出的可预览 / 编辑 / 下载的对象，带版本链 |
| **Router** | AgentHub 现有本地消息总线，负责机器对机器消息路由 |
| **BFF** | Backend For Frontend，介于前端与 Router/Adapter 之间的薄层 |
| **ACK** | 应用层确认；`delivered` 表示入队成功，`accepted` 表示被处理 |
| **Trace** | 一条消息从发起到完成的全链路事件序列，可视化为时序图 |
| **Card** | 富媒体消息卡片的统称，含 `code/diff/preview/file/task_status` |

---

> 文档由项目团队基于 `COURSE_PROPOSAL.md` 编写，与现有 `src/` 实现保持一致。
> 任何对协议字段、数据库表、Adapter 接口的修改，**必须先在本文件留下 changelog 与 PR 链接**。
