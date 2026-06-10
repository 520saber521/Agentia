# AgentHub 课题实施方案：多 Agent 协作平台（IM 形态）

> 基于现有 AgentHub 项目，构建对话式多 Agent 协作平台的完整思路、技术架构与实施路线图。

---

## 目录

- [一、关键洞察：现有项目与课题的契合度](#一关键洞察现有项目与课题的契合度)
- [二、产品定位重新设计](#二产品定位重新设计)
- [三、技术架构文档](#三技术架构文档)
  - [3.1 总体架构图](#31-总体架构图)
  - [3.2 分层职责](#32-分层职责)
  - [3.3 数据模型](#33-数据模型sqlite-即可)
  - [3.4 消息内容结构](#34-消息内容content-字段的-json-结构)
  - [3.5 关键流程时序](#35-关键流程时序)
  - [3.6 Agent Adapter 抽象](#36-agent-adapter-抽象关键创新点之一)
  - [3.7 实时通信协议](#37-实时通信协议websocket-消息格式)
- [四、目录结构建议](#四目录结构建议fork-现有项目后)
- [五、分期实施路线图](#五分期实施路线图建议-4-周)
- [六、AI 协作规范沉淀（30% 权重）](#六ai-协作规范沉淀30-权重--这是评分的最大块)
- [七、创新与产品感（10%）](#七创新与产品感10--可拉差距点)
- [八、交付物与评分对应表](#八交付物与评分对应表)
- [九、立即可以开始的下一步](#九立即可以开始的下一步)

---

## 一、关键洞察：现有项目与课题的契合度

先做一个对照表，看清楚 **AgentHub 现有什么、缺什么、需要改什么** —— 这决定了你不是从零写，而是站在已有 80% 后端能力上"加皮"和"换交互范式"。

| 课题要求 | AgentHub 现有能力 | 处理策略 |
|---|---|---|
| IM 聊天式交互 | 完全没有前端 | **新建** Web 端（核心工作量） |
| 消息可靠投递、ACK、重试 | `src/router/router.py` 完整实现 | **直接复用** |
| 多 Agent 并行调度 | `src/scheduler/scheduler.py` | **包装** 为"群聊 Orchestrator" |
| 主 Agent 协调器 | MAIN 角色 + decomposer/aggregator | **直接复用**，重命名为 Orchestrator |
| 消息协议（review/assign/done…） | `src/protocol/builders.py` | **扩展**：加 `chat / preview_card / diff_card` 类型 |
| 历史回放、崩溃恢复 | JSONL + `state/recovery.py` | **直接复用**作为聊天历史存储 |
| 任务分解、契约优先 | `decomposer / contracts` | **复用**为群聊任务拆分 |
| 多 Agent 接入（Claude Code / Codex / OpenCode） | 现在用终端窗口 + AppleScript 启动 | **改造**为 Adapter 抽象层（HTTP/SDK 直连） |
| 上下文连续 | 任务级有，缺会话级 | **扩展**：新增 Conversation 抽象 |
| 富媒体（Diff / Preview / 附件） | 无 | **新建**消息类型 + 前端组件 |
| 实时推送 | 现在是 HTTP 长轮询 `pop_inbox` | **升级**为 WebSocket / SSE |
| 用户自建 Agent | 无 | **新建** Agent 配置管理 |
| 部署发布（P2） | 无 | **新建** Deploy 服务 |
| AI 协作规范沉淀 | `prompts/`、`docs/main-members-workflow.md` 已是完整范本 | **直接当作 Spec 交付** |

**核心洞察**：AgentHub 实际上是一个"AI 群聊后端"被错装在了"终端窗口"这个交互外壳里。你的工作就是 **把外壳从"5 个终端窗口"换成"IM 聊天前端"**，后端协议几乎不动。这是这个项目最大的红利。

---

## 二、产品定位重新设计

把现有概念做一次"翻译"，让团队（和评委）一眼看懂：

| AgentHub 原概念 | 课题里的 IM 概念 |
|---|---|
| MAIN Agent | **Orchestrator（主持人 Bot）** |
| A/B/C/D Agent | **联系人**（Claude Code / Codex / OpenCode / 自建 Agent） |
| Router | **IM 服务端（消息总线）** |
| Task | **会话（Conversation）** 或会话内的一次"任务话题" |
| Inbox 队列 | **未读消息队列** |
| `assign / review / done` 协议消息 | 群聊里的 @ 指令、回复、产物提交 |
| `progress / lock / notify` | 群聊"成员状态条"、"输入中..."、"正在写代码..." |
| `team board` ASCII 看板 | **群聊侧边栏的任务进度面板** |

这样一来，整个产品看起来非常完整且自洽：**用户像用飞书一样聊天，背后是 AgentHub 在做可靠消息路由和多 Agent 调度**。

---

## 三、技术架构文档

### 3.1 总体架构图

```
┌────────────────────────────────────────────────────────────────────┐
│                          Web 前端 (React + TS)                      │
│  ┌──────────┬──────────────────────┬──────────────────────────┐    │
│  │ 会话列表 │  消息流 (虚拟列表)    │  侧栏: 任务/产物/Agent列表 │    │
│  │          │  ┌──────────────┐    │                          │    │
│  │ - 单聊   │  │ 文本气泡      │    │  · 任务进度卡片          │    │
│  │ - 群聊   │  │ 代码块 + 复制 │    │  · 产物预览 (iframe)     │    │
│  │ - 新建   │  │ Diff 卡片     │    │  · 文件附件              │    │
│  │ - 搜索   │  │ 预览卡片      │    │  · @ 提示器              │    │
│  └──────────┴──────────────────────┴──────────────────────────┘    │
└─────────────────────────────┬──────────────────────────────────────┘
                              │ WebSocket / HTTPS
┌─────────────────────────────▼──────────────────────────────────────┐
│              BFF / Gateway 层 (FastAPI + WebSocket)                 │
│  · 鉴权 / Session                                                   │
│  · WS 长连接管理 (每用户一条)                                        │
│  · 把前端 ChatMessage → AgentHub Protocol Message                   │
│  · 把 AgentHub 投递事件 → 前端 WS 推送                              │
└────────┬───────────────────────────┬───────────────────────────────┘
         │                           │
         │ (聊天会话/消息 CRUD)       │ (Agent 通信)
         ▼                           ▼
┌──────────────────┐    ┌─────────────────────────────────────────┐
│ Conversation Svc │    │     AgentHub Router (复用 0 改动)       │
│  · 会话元数据    │    │  /messages /acks /inbox /presence       │
│  · 消息历史      │    │  · 投递 / 重试 / ACK / Trace            │
│  · pin / 搜索    │    │  · JSONL 持久化 + 崩溃恢复              │
│  (SQLite/PG)     │    └──────────┬──────────────────────────────┘
└──────────────────┘               │
                                   │
                ┌──────────────────┼──────────────────┐
                │                  │                  │
                ▼                  ▼                  ▼
        ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
        │ Orchestrator │  │   Adapter    │  │   Adapter    │
        │  (主持人)    │  │ Claude Code  │  │   Codex      │
        │ 复用 scheduler│  │              │  │              │
        └──────────────┘  └──────────────┘  └──────────────┘
                                   │
                                   ▼
                          ┌──────────────────┐
                          │  Artifact Store  │
                          │  (代码/网页/文件) │
                          │  本地FS + 元数据  │
                          └──────────────────┘
```

### 3.2 分层职责

#### L1 - 前端层（**新建，工作量最大**）
- **技术**：React 18 + TypeScript + Vite + TailwindCSS + shadcn/ui + Zustand（状态）
- **关键库**：
  - `@monaco-editor/react`：代码编辑器（含 Diff View）
  - `react-markdown` + `rehype-highlight`：消息渲染
  - `react-window` 或 `@tanstack/react-virtual`：长消息流虚拟滚动
  - `socket.io-client` 或原生 WebSocket：实时通信
- **页面结构**：参考飞书/微信，三栏布局（会话列表 / 消息流 / 侧栏）

#### L2 - BFF/Gateway 层（**新建，薄一层**）
- **技术**：FastAPI + uvicorn + `fastapi.WebSocket`
- **职责**：
  - WebSocket 长连接管理（用户 ↔ 服务端）
  - 协议转换：前端 ChatMessage ↔ AgentHub 内部 Message
  - 鉴权、限流、文件上传
- **为什么不直接让前端调 Router**：因为 Router 设计是"机器对机器"（Agent ↔ Agent），不带鉴权、不区分用户、不做协议翻译。BFF 是必需的薄适配。

#### L3 - 会话服务（**新建**）
- **技术**：SQLite（演示足够）/ PostgreSQL（如要多用户）+ SQLAlchemy
- **职责**：聊天会话 CRUD、消息分页查询、置顶/归档/搜索、pin 消息
- **数据模型**：见 3.3 节

#### L4 - AgentHub Router（**复用 0 改动**）
- 端口 8765，REST API
- 唯一改造点：可能要给消息体加几个新字段（`conversation_id`, `card_type`, `artifact_id`），但属于扩展，不破坏现有协议

#### L5 - Orchestrator（**复用 + 包装**）
- 复用 `src/scheduler/scheduler.py` + `src/scheduler/decomposer.py`
- 触发条件：群聊中检测到"复杂任务"或显式 @Orchestrator
- 决策流程：参考现有 `analyze → design → schedule → execute → aggregate`

#### L6 - Agent Adapter 层（**新建，是个亮点**）
- 抽象基类 `AgentAdapter`，统一接口
- 实现三个适配器：`ClaudeCodeAdapter`、`CodexAdapter`、`OpenCodeAdapter`
- 还有一个 `CustomAgentAdapter` 走通用 OpenAI/Anthropic API

#### L7 - 产物存储（**新建**）
- 本地文件系统 + 元数据表
- 每个产物有唯一 ID、类型（code/web/doc/ppt）、版本号、所属消息

### 3.3 数据模型（SQLite 即可）

```sql
-- 会话
CREATE TABLE conversation (
    id              TEXT PRIMARY KEY,        -- conv_xxx (UUID)
    title           TEXT NOT NULL,
    type            TEXT NOT NULL,           -- 'single' | 'group'
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL,
    pinned          INTEGER DEFAULT 0,
    archived        INTEGER DEFAULT 0,
    last_msg_preview TEXT,
    owner_user_id   TEXT NOT NULL
);

-- 会话成员（Agent 或人）
CREATE TABLE conversation_member (
    conversation_id TEXT NOT NULL,
    member_id       TEXT NOT NULL,           -- user_xxx 或 agent_xxx
    member_type     TEXT NOT NULL,           -- 'user' | 'agent'
    role            TEXT,                    -- 'orchestrator' | 'worker' | 'observer'
    joined_at       INTEGER NOT NULL,
    PRIMARY KEY (conversation_id, member_id)
);

-- 消息
CREATE TABLE message (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    sender_id       TEXT NOT NULL,           -- user_xxx 或 agent_xxx
    sender_type     TEXT NOT NULL,
    content_type    TEXT NOT NULL,           -- 'text'|'code'|'diff'|'preview'|'file'|'task_status'
    content         TEXT NOT NULL,           -- JSON
    reply_to        TEXT,                    -- 消息 id (回复/引用)
    mentions        TEXT,                    -- JSON array: ['agent_claude','agent_codex']
    pinned          INTEGER DEFAULT 0,
    artifact_id     TEXT,                    -- 关联产物
    agenthub_msg_id TEXT,                    -- 对应 Router 里的 message id
    created_at      INTEGER NOT NULL
);
CREATE INDEX idx_msg_conv ON message(conversation_id, created_at);

-- Agent 注册表
CREATE TABLE agent (
    id              TEXT PRIMARY KEY,        -- agent_xxx
    name            TEXT NOT NULL,
    avatar          TEXT,
    adapter_type    TEXT NOT NULL,           -- 'claude_code'|'codex'|'opencode'|'custom'
    config          TEXT NOT NULL,           -- JSON: api_key, base_url, system_prompt...
    capabilities    TEXT,                    -- JSON array: ['code','web','review'...]
    owner_user_id   TEXT,                    -- NULL 表示系统内置
    created_at      INTEGER NOT NULL
);

-- 产物
CREATE TABLE artifact (
    id              TEXT PRIMARY KEY,
    type            TEXT NOT NULL,           -- 'code_file'|'web_page'|'doc'|'ppt'|'zip'
    title           TEXT,
    file_path       TEXT,                    -- 本地路径
    preview_url     TEXT,                    -- 可访问 URL
    version         INTEGER DEFAULT 1,
    parent_id       TEXT,                    -- 上一版本
    conversation_id TEXT,
    created_by      TEXT,                    -- agent_xxx
    created_at      INTEGER NOT NULL
);

-- 任务（群聊里的子任务，对接 AgentHub task）
CREATE TABLE task (
    id              TEXT PRIMARY KEY,        -- 对应 AgentHub 的 task_id
    conversation_id TEXT NOT NULL,
    parent_msg_id   TEXT,                    -- 触发任务的那条用户消息
    title           TEXT NOT NULL,
    status          TEXT NOT NULL,           -- 'pending'|'running'|'done'|'failed'
    assignee        TEXT,
    progress        INTEGER DEFAULT 0,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL
);
```

### 3.4 消息内容（content 字段的 JSON 结构）

```typescript
// 文本
{ "type": "text", "text": "用 React 写一个登录页" }

// 代码块
{ "type": "code", "language": "tsx", "code": "...", "filename": "Login.tsx" }

// Diff 卡片
{
  "type": "diff",
  "filename": "Login.tsx",
  "before_artifact_id": "art_001",
  "after_artifact_id": "art_002",
  "stats": { "additions": 12, "deletions": 5 }
}

// 网页预览卡片
{
  "type": "preview",
  "preview_url": "http://localhost:8788/preview/art_003",
  "title": "Login Page v2",
  "thumbnail": "..."
}

// 任务状态卡片（Orchestrator 用）
{
  "type": "task_status",
  "task_id": "task_007",
  "title": "实现登录功能",
  "subtasks": [
    { "id": "sub_1", "title": "前端表单", "assignee": "agent_claude", "status": "done" },
    { "id": "sub_2", "title": "后端 API",  "assignee": "agent_codex",  "status": "running", "progress": 60 }
  ]
}

// 文件
{ "type": "file", "filename": "design.pdf", "size": 234567, "url": "..." }
```

### 3.5 关键流程时序

#### 流程 A：单聊发送消息

```
User                    Web                BFF                  Adapter         Router
 │                       │                  │                      │              │
 │  输入"写个登录页"      │                  │                      │              │
 ├──────────────────────►│                  │                      │              │
 │                       │  WS: send_msg    │                      │              │
 │                       ├─────────────────►│                      │              │
 │                       │                  │ ① 写 message 表       │              │
 │                       │                  │ ② 调 Adapter.send()   │              │
 │                       │                  ├─────────────────────►│              │
 │                       │                  │                      │  调用外部API  │
 │                       │                  │                      │ (Claude Code)│
 │                       │                  │                      │              │
 │                       │  WS: agent_typing│  推送 "Agent 输入中..."│              │
 │                       │◄─────────────────┤                      │              │
 │                       │                  │                      │              │
 │                       │                  │                      │  流式返回    │
 │                       │                  │◄─────────────────────┤              │
 │                       │  WS: stream_chunk│                      │              │
 │                       │◄─────────────────┤  (分片转发)           │              │
 │                       │                  │ ③ 完成后写产物 / DB    │              │
 │                       │  WS: msg_done    │                      │              │
 │                       │◄─────────────────┤                      │              │
```

**关键点**：单聊不一定要经过 AgentHub Router，可以直接 BFF → Adapter，简单直接。

#### 流程 B：群聊 @Orchestrator + 多 Agent 协作

```
User → "@Orchestrator 做一个支持 OAuth 的登录页 + 后端 API"
   │
   ▼
BFF 写 message 表 → POST /messages 到 AgentHub Router
   │   to=["agent_orchestrator"]
   ▼
Router → 投递到 Orchestrator inbox
   │
   ▼
Orchestrator (复用 scheduler):
  1. analyze: 判定为复杂任务
  2. design: 生成契约（前端组件接口 + 后端 API schema）
  3. decompose: 拆出 2 个子任务
     - 子任务1: 前端登录页 → assign to agent_claude
     - 子任务2: 后端 OAuth API → assign to agent_codex
  4. 把"任务卡片"作为群聊消息 push 回会话 (经 BFF WS)
   │
   ▼
Router 投递 assign 消息给 claude / codex (并行)
   │
   ▼
各 Adapter 调用外部 API → 流式产出 → 转发到 BFF
   │
   ▼
BFF 把每个 Agent 的产出包装成 ChatMessage 写入会话
（前端实时看到"群聊"里多个 Agent 依次发言）
   │
   ▼
两个子任务都 done → Orchestrator aggregate → 在群里发"汇总卡片"
```

#### 流程 C：Diff 与代码二次编辑

```
1. Agent 产出 Login.tsx → 保存为 artifact art_001
2. 在消息流插入 preview 卡片（点击可全屏 Monaco 编辑）
3. 用户在前端 Monaco 里改了代码 → 保存为 art_002
4. 用户在聊天里发 "把按钮换成圆角"
5. BFF 把当前选中的代码段 + 用户描述打包成 prompt 给 Agent
6. Agent 返回 patch → 生成 diff 卡片（before=art_002, after=art_003）
7. 用户点"应用 Diff" → BFF 落盘 → 触发新 preview
```

### 3.6 Agent Adapter 抽象（关键创新点之一）

```python
# adapters/base.py
from abc import ABC, abstractmethod
from typing import AsyncIterator, List

class AgentAdapter(ABC):
    """统一 Agent 适配器接口"""

    @abstractmethod
    async def send(
        self,
        messages: List[dict],          # OpenAI-style chat history
        tools: List[dict] | None = None,
        artifacts_context: dict | None = None,  # 已有产物的引用
    ) -> AsyncIterator[dict]:
        """流式返回，yield 出 {type: 'text'|'tool_call'|'artifact', ...}"""
        ...

    @abstractmethod
    def capabilities(self) -> List[str]:
        """能力声明: ['code', 'web', 'image', 'tool_use'...]"""
        ...

# adapters/claude_code.py
class ClaudeCodeAdapter(AgentAdapter):
    async def send(self, messages, tools=None, **kw):
        # 调用 Anthropic Claude API (claude-sonnet-4.5 / claude-opus-4.7 等)
        ...

# adapters/codex.py
class CodexAdapter(AgentAdapter):
    async def send(self, messages, tools=None, **kw):
        # 调用 OpenAI Codex / GPT-5 API
        ...

# adapters/custom.py
class CustomAgentAdapter(AgentAdapter):
    """用户自建 Agent: 配置 System Prompt + 后端模型即可"""
    def __init__(self, config):
        self.system_prompt = config["system_prompt"]
        self.model = config["model"]
        self.api_key = config["api_key"]
        ...
```

这个 Adapter 层让你的"接入 N 个 Agent 平台"变成 **写 N 个文件**，是评委一眼能看出工程感的地方。

### 3.7 实时通信协议（WebSocket 消息格式）

```typescript
// Client → Server
type ClientEvent =
  | { type: 'join', conversation_id: string }
  | { type: 'send_message', conversation_id: string, content: MessageContent, mentions?: string[] }
  | { type: 'typing', conversation_id: string }
  | { type: 'cancel', message_id: string }

// Server → Client
type ServerEvent =
  | { type: 'message_created', message: Message }
  | { type: 'stream_chunk', message_id: string, delta: string }
  | { type: 'message_done', message_id: string, final_content: MessageContent }
  | { type: 'agent_typing', agent_id: string, conversation_id: string }
  | { type: 'task_update', task: Task }
  | { type: 'artifact_ready', artifact: Artifact, message_id: string }
  | { type: 'error', code: string, message: string }
```

---

## 四、目录结构建议（fork 现有项目后）

```
AgentHub/
├── src/                    # 现有 Python 后端（基本不动）
│   ├── api/                # ← 复用，但加 /v2/* 新端点
│   ├── router/             # ← 复用 0 改动
│   ├── scheduler/          # ← 复用，Orchestrator 包装
│   ├── protocol/           # ← 扩展几个消息类型
│   └── ...
│
├── server/                 # 【新建】 BFF / 会话服务
│   ├── main.py             # FastAPI 入口
│   ├── ws.py               # WebSocket 管理
│   ├── conversation.py     # 会话 CRUD
│   ├── adapters/           # Agent 适配器
│   │   ├── base.py
│   │   ├── claude_code.py
│   │   ├── codex.py
│   │   ├── opencode.py
│   │   └── custom.py
│   ├── orchestrator.py     # 包装 scheduler 的群聊主持人
│   ├── artifact.py         # 产物管理
│   ├── db/                 # SQLite + SQLAlchemy
│   │   ├── models.py
│   │   └── migrations/
│   └── requirements.txt
│
├── web/                    # 【新建】前端
│   ├── src/
│   │   ├── pages/
│   │   ├── components/
│   │   │   ├── ConversationList.tsx
│   │   │   ├── MessageStream.tsx
│   │   │   ├── MessageBubble.tsx
│   │   │   ├── CodeBlock.tsx
│   │   │   ├── DiffCard.tsx
│   │   │   ├── PreviewCard.tsx
│   │   │   ├── TaskStatusCard.tsx
│   │   │   ├── AgentPicker.tsx
│   │   │   └── ArtifactEditor.tsx   # Monaco
│   │   ├── stores/         # Zustand
│   │   ├── ws/             # WebSocket 客户端
│   │   └── api/
│   ├── package.json
│   └── vite.config.ts
│
├── ai-collab/              # 【新建，30% 权重核心交付】
│   ├── SPEC.md             # 产品规格
│   ├── ARCHITECTURE.md     # 本文档
│   ├── skills/             # AI 协作 Skill 沉淀
│   │   ├── new-message-type.md
│   │   ├── new-adapter.md
│   │   └── debug-ws-flow.md
│   ├── rules/              # .cursor/rules 类规范
│   │   ├── frontend.mdc
│   │   ├── backend.mdc
│   │   └── adapter.mdc
│   └── records/            # 真实开发对话记录
│       ├── 20260520-orchestrator.md
│       └── 20260521-diff-card.md
│
├── docs/                   # 现有，扩充
├── prompts/                # 现有，扩充 Agent 提示词
└── README.md
```

---

## 五、分期实施路线图（建议 4 周）

| 阶段 | 时长 | 目标 | 验收点 |
|---|---|---|---|
| **W1: 骨架打通** | 5 天 | 走通"前端 ↔ BFF ↔ Adapter ↔ 外部 Agent"单聊链路 | 能用浏览器和 Claude API 聊一段话，消息存 DB |
| **W2: AgentHub 接入 + 群聊** | 5 天 | 接 Router、跑通 Orchestrator 拆任务 + 2 Agent 并行 | 一次群聊产出前后端两份代码 |
| **W3: 富媒体 + 产物** | 5 天 | Diff 卡片、Preview iframe、Monaco 编辑、二次修改 | 用户能"对话式改代码" |
| **W4: 打磨 + 交付物** | 5 天 | UI 美化、用户自建 Agent、Demo 视频、文档定稿 | 3 分钟视频 + 答辩稿 |

**P2（如果有时间）**：部署发布、移动端适配、版本历史。

**强烈建议**：W1 用最简单的 Mock Adapter（返回固定文本）跑通整条链路，W2 再换真 API。这是经过验证的"先链路后内容"打法，避免被外部 API 卡住。

---

## 六、AI 协作规范沉淀（30% 权重 — 这是评分的最大块）

课题明确说"沉淀出和 AI 协作的 Spec、skill、rules 等协作规范"，这一项 **直接占总分 30%**，必须当成产品来做。建议在 `ai-collab/` 下分三类沉淀：

### 6.1 Spec（产品规格）— `ai-collab/SPEC.md`

用 EARS / Given-When-Then 风格写：

```markdown
## Feature: 群聊 @Orchestrator 自动拆任务

### User Story
作为用户，在群聊中 @Orchestrator 提出复杂需求时，我希望它能自动拆解任务、分派给合适的 Agent，并实时展示进度。

### Acceptance Criteria
- GIVEN 群聊中包含 ≥2 个 Agent
- WHEN 用户消息 @Orchestrator 且文本被判定为"复杂任务"
- THEN 系统应在 3s 内在群聊中插入"任务卡片"，包含 ≥2 个子任务及负责 Agent
- AND 每个子任务的状态实时更新，最终聚合产物
```

每个核心功能都写一份。**评委一翻就知道你做了规范化设计**。

### 6.2 Skills — `ai-collab/skills/*.md`

把"如何让 AI 帮你完成某类任务"的可复用流程沉淀下来。比如：

`skills/new-adapter.md`：

```markdown
# 新增一个 Agent Adapter

When to use: 用户想接入一个新的 AI Agent 平台。

Steps for AI:
1. 在 server/adapters/ 下复制 base.py 创建 <name>.py
2. 实现 send() 流式接口，注意分片 yield
3. 在 server/adapters/__init__.py 注册到 ADAPTER_REGISTRY
4. 在 db/seed.py 添加默认 Agent 实例
5. 测试: pytest server/tests/test_adapter_<name>.py

Reference files:
- server/adapters/base.py
- server/adapters/claude_code.py (参考实现)
```

可以直接参考现有项目的 `prompts/agent_*.txt` 风格，这其实已经是非常成熟的 Skill 范本了。

### 6.3 Rules — `ai-collab/rules/*.mdc`

放在 `.cursor/rules/` 下，给后续协作 AI 的硬约束：

```markdown
---
description: 后端代码约定
globs: ["server/**/*.py"]
alwaysApply: true
---
# Backend Rules
- 所有 IO 必须 async，禁止 requests，用 httpx
- 数据库 schema 变更必须先在 db/migrations/ 写 alembic 脚本
- Adapter.send() 必须支持流式 yield，不允许返回完整字符串
- 写入 message 表前必须 validate content JSON schema
```

### 6.4 协作记录 — `ai-collab/records/*.md`

每次和 AI 大规模协作时，导出对话存档（Cursor 有"导出对话"功能）。**评委想看的是真实痕迹，不是事后包装**。

> **顺便**：你的项目本身就在 **吃自己的狗粮** —— 用 AgentHub 多 Agent 协作来开发 AgentHub 的新版本。这一点必须在答辩里讲，是天然的高分点。

---

## 七、创新与产品感（10% — 可拉差距点）

按性价比排序：

1. **"吃自己狗粮"叙事**：用 AgentHub 群聊开发本课题，把开发过程的群聊截图作为 demo 之一。**无成本，叙事最强**。
2. **Agent 名片悬浮卡**：鼠标悬停 Agent 头像显示能力标签、最近任务、token 消耗，类似飞书悬浮卡。**小成本，体验感强**。
3. **任务进度气泡内嵌进度条**：任务卡片不是静态的，是一条会动态更新的消息（已有 `progress` 协议消息）。
4. **代码"圈选改"**：Monaco 选中代码 → 浮动按钮"在聊天中描述修改" → 自动把选中片段作为引用插入输入框。
5. **多 Agent 投票模式**：群聊里输入 `/vote 这两个方案哪个好` → 让所有在场 Agent 各自发表意见 → 用户决策。这是 AutoGen 类框架罕见的形态。
6. **可观测面板**：基于 Router 的 `/trace` 端点做一个 Mermaid 时序图渲染 —— 评委的代码理解度分（15%）直接拉满。
7. **离线优先**：所有产物保存到本地 FS，断网也能查历史。结合现有 JSONL 持久化非常自然。

---

## 八、交付物与评分对应表

| 交付物 | 评分维度 | 内容来源 |
|---|---|---|
| **产品设计文档** | 创新与产品感 10% + 功能完整度 25% | 把"二、产品定位重新设计 + 七、创新"扩写成 10 页 |
| **技术文档** | 代码理解度 15% | 本文（三、技术架构）扩写 + 关键模块代码导读 |
| **AI 协作开发记录** | AI 协作能力 30% | `ai-collab/` 整个目录（Spec + Skills + Rules + Records） |
| **可运行 Demo** | 功能完整度 25% + 生成效果质量 20% | W1-W4 实施成果 |
| **3 分钟 Demo 视频** | 生成效果质量 20% + 创新 10% | 推荐脚本见下 |

### Demo 视频脚本（3 分钟）

```
00:00-00:20  开场：问题陈述（多 Agent 协作的痛点）+ 产品一句话定义
00:20-00:50  单聊：新建会话 → 选 Claude Code → 让它写登录页 → 流式输出 → preview 卡片
00:50-01:40  群聊：@Orchestrator 做 OAuth 全栈 → 任务卡片自动出现 →
            Claude 和 Codex 在群里并发干活 → 任务进度条动 → 最后汇总卡片
01:40-02:10  Diff 与二次修改：圈选代码 → 在聊天里说"加圆角" → diff 卡片 → 一键应用
02:10-02:35  用户自建 Agent：通过对话创建一个"PM Bot"，回到群聊即可 @
02:35-03:00  吃自己狗粮的开发记录截图 + 架构图 + GitHub
```

---

## 九、立即可以开始的下一步

如果接受这份思路，建议这样开工：

1. **今晚** 在 fork 出来的项目里新建 `server/` 和 `web/` 两个目录，把 `server/main.py` 写出 hello world FastAPI + WebSocket echo。
2. **明天** 写 `server/adapters/base.py` 和一个 `MockAdapter`（固定返回流式文本），让前端能跑通"发消息→流式收到回复"。
3. **第三天** 把 SQLite + 三张核心表（conversation / message / agent）建好，前端能展示会话列表 + 消息流。
4. **第四天** 接入第一个真 Adapter（推荐 Claude，SDK 最干净）。
5. **第五天** 接 AgentHub Router，群聊跑通。

---

## 附录 A：AgentHub 现有技术栈速览

| 分类 | 技术选型 |
|---|---|
| 主语言 | Python 3.8+ |
| HTTP Server | `http.server.ThreadingHTTPServer`（标准库） |
| HTTP Client | `urllib.request`（标准库） |
| 并发 | `threading` + `Lock` + 后台线程 |
| 数据序列化 | `json` + JSONL 日志 |
| 存储 | 本地文件系统（JSON/JSONL/blob），无数据库 |
| 配置 | YAML（`config/scheduler.yaml`） |
| 校验 | 自研 validator |
| CLI | `argparse`（`team.py`） |
| 启动脚本 | Bash + AppleScript（macOS 专属） |
| 终端集成 | macOS Terminal.app / iTerm2 / tmux |
| 前端 | 无（Web Dashboard 仅在 Roadmap） |

## 附录 B：参考资料

- 现有项目协议规范：`docs/main-members-workflow.md`
- 现有项目架构设计：`docs/design.md`
- 现有 Agent 角色提示词：`prompts/agent_*.txt`
- 现有调度器配置：`config/scheduler.yaml`
