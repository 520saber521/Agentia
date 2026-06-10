# Agentia — 多 Agent 协作平台

（一）项目沉淀出ai协作的Spec、skill、rules等协作规范在https://github.com/520saber521/Agentia/tree/main/ai-collab

（二）已部署生成的产物样例https://6a258dd4926549e469893760--hilarious-twilight-b6a787.netlify.app/

Agentia 是一个以 **IM 聊天为核心交互范式**的多 Agent 协作平台。用户可以像使用飞书或微信一样新建会话、选择 Agent、发送消息，在群聊中通过 `@` 提及多个 Agent，让它们并行或串行协作完成复杂任务。

## 目录

- [核心特性](#核心特性)
- [系统架构](#系统架构)
- [技术栈](#技术栈)
- [目录结构](#目录结构)
- [快速启动](#快速启动)
- [WebSocket 协议](#websocket-协议)
- [REST API 概览](#rest-api-概览)
- [Agent 适配器](#agent-适配器)
- [测试](#测试)
- [推荐 Demo 流程](#推荐-demo-流程)
- [后续规划](#后续规划)

---

## 核心特性

### 1. IM 式交互界面

三栏布局：会话列表 | 聊天流 | 上下文侧栏

- 会话管理：新建、查询、置顶、归档、搜索、单聊/群聊切换
- `@` 提及机制：群聊中精确指定参与协作的 Agent
- 流式回复：实时展示 Agent 生成过程，支持取消生成

### 2. 多 Agent 协作引擎

- **Orchestrator**：识别复杂任务，自动拆解为子任务，分派给不同 Agent，聚合结果
- **群聊 Fan-out**：消息根据 `@mentions` 分发给多个 Agent 并行处理；空会话首次消息自动识别复杂任务并路由到 Orchestrator
- **编配策略命令**：支持 `/map-reduce`（分片并行）、`/router-experts`（按领域路由）、`/tree-executor`（树形分层执行）三种编配策略
- **DAG 执行引擎**：事件驱动的 DAG 执行器，管理子任务之间的依赖关系与并发调度
- **Sub-Agent 动态创建**：Orchestrator 可在运行时根据任务复杂度自动创建子 Agent 并委派工作

### 3. 统一 Agent 适配器

通过 `Adapter` 抽象层统一接入多种 Agent 后端：

| Adapter          | 状态   | 说明                                                                 |
| ---------------- | ------ | -------------------------------------------------------------------- |
| Mock             | 已完成 | 开发调试用，模拟 Agent 回复。配置 API Key 后自动升级为真实大模型调用 |
| Claude Code      | 已完成 | 接入本地 Claude Code CLI                                             |
| Claude Agent SDK | 已完成 | 基于 `claude-agent-sdk` 的标准适配                                   |
| Codex            | 已完成 | 接入 OpenAI Codex CLI                                                |
| OpenCode         | 已完成 | 接入 OpenCode CLI                                                    |

### 4. 富媒体产物

支持多种消息类型，超出文本范围承载结构化信息：

| 产物类型      | 说明                                 |
| ------------- | ------------------------------------ |
| 文本/Markdown | 标准消息渲染                         |
| 代码块        | 语法高亮、一键复制                   |
| 网页预览      | 内嵌 iframe 预览生成的 HTML/前端页面 |
| 文件附件      | 文件上传、下载                       |
| Diff 卡片     | 代码差异对比展示                     |
| 任务状态卡片  | 展示子任务拆解与进度                 |
| 部署状态卡片  | 展示部署流程状态                     |

### 5. 产物编辑与版本管理

- 内嵌 **Monaco 编辑器**，在线编辑代码产物
- **版本历史**追踪，回退到任意历史版本
- **Diff 应用**：将 Agent 生成的 Diff 预览后应用到实际代码

### 6. 自建 Agent 管理

- 通过 REST API 创建、更新、删除自定义 Agent
- 聊天命令创建 Agent：输入 `/agent create name: xxx adapter: codex prompt: ...` 即可在对话中创建
- 配置系统提示词（`prompts/`），赋予 Agent 专属角色（Frontend、Backend、Database、Test & Docs、Product 等）

### 7. 可观测性

- **Trace 追踪**：每条消息可回溯到完整执行链路
- **Animation 事件流**：可视化展示多 Agent 协作过程
- **Agent 执行记录**：历史执行统计与日志

---

## 系统架构

```
┌─────────────────────────────────────────────────────┐
│  Web 前端 (React + Vite + Tailwind + Zustand)       │
│  三栏布局  │  Monaco 编辑器  │  富媒体卡片          │
└─────────────────┬───────────────────────────────────┘
                  │ HTTP/WS
┌─────────────────▼───────────────────────────────────┐
│  BFF / Gateway (FastAPI + Uvicorn)                  │
│  ├─ REST API: 会话 / Agent / 产物 / 部署 / Trace    │
│  ├─ WebSocket Hub: 连接管理 + 事件分发              │
│  └─ 静态文件服务                                    │
└─────────────────┬───────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────┐
│  服务层 (server/services/)                          │
│  ├─ Conversation Service: 会话 CRUD + 上下文管理    │
│  ├─ Message Service: 消息存储 + 历史回放            │
│  ├─ Agent Service: Agent 注册、查询、管理           │
│  ├─ Artifact Service: 产物存储 + 版本管理           │
│  ├─ Task Service: 任务状态机                       │
│  ├─ Trace Service: 执行链路追踪                    │
│  ├─ Deploy Service: 部署流程                       │
│  ├─ Context Manager: 上下文窗口管理                │
│  └─ Tool Registry: Agent 工具注册                  │
└─────────────────┬───────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────┐
│  调度层                                             │
│  ├─ Orchestrator: 任务拆解 + Sub-Agent 调度         │
│  │    planning → task decomposition → fan-out →     │
│  │    track progress → aggregate summary            │
│  ├─ DAG Engine: 子任务 DAG 执行编排                │
│  └─ Router Client: 向 Router 注册节点               │
└─────────────────┬───────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────┐
│  Adapter 抽象层 (server/adapters/)                  │
│  ├─ BaseAdapter: 统一接口                           │
│  ├─ ClaudeCodeAdapter                              │
│  ├─ ClaudeAgentSDKAdapter                          │
│  ├─ CodexAdapter                                   │
│  └─ MockAdapter                                    │
└─────────────────┬───────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────┐
│  持久层                                             │
│  ├─ SQLite (SQLAlchemy 2.x async)                  │
│  ├─ 本地文件系统 (产物存储)                         │
│  └─ 数据库文件: server/.agenthub/bff.db             │
└─────────────────────────────────────────────────────┘
```

**数据模型**：

| 表                    | 说明                                              |
| --------------------- | ------------------------------------------------- |
| `conversation`        | 会话（type: single/group，支持 pin/archive/搜索） |
| `conversation_member` | 会话成员关联（user/agent）                        |
| `message`             | 消息（文本 + 富媒体 payload，支持 pin）           |
| `agent`               | Agent 注册信息（名称、系统提示词、能力标签）      |
| `agent_execution`     | Agent 执行记录                                    |
| `artifact`            | 产物（代码、页面、文件等，带版本号）              |
| `task`                | 任务（Orchestrator 拆解后的子任务状态机）         |
| `trace_entry`         | 执行链路追踪日志                                  |

---

## 技术栈

### 后端

| 组件       | 技术                                         |
| ---------- | -------------------------------------------- |
| 框架       | FastAPI + Uvicorn                            |
| ORM        | SQLAlchemy 2.x (async)                       |
| 数据库     | SQLite（文件：`server/.agenthub/bff.db`）    |
| 实时通信   | WebSocket（自建 Hub + 事件分发）             |
| Agent 接入 | Claude Agent SDK、Claude Code CLI、Codex CLI |
| 测试       | pytest + pytest-asyncio + httpx              |

### 前端

| 组件     | 技术                                   |
| -------- | -------------------------------------- |
| 框架     | React 18 + TypeScript                  |
| 构建     | Vite 6                                 |
| 样式     | Tailwind CSS 3                         |
| 状态管理 | Zustand 5                              |
| 动画     | Framer Motion                          |
| 代码编辑 | Monaco Editor (`@monaco-editor/react`) |
| Markdown | marked                                 |
| 语法高亮 | PrismJS                                |
| 测试     | Vitest                                 |

---

## 目录结构

```text
Agentia/
├── server/                         # BFF / Gateway 服务
│   ├── main.py                     # FastAPI 应用入口 + 生命周期
│   ├── ws.py                       # WebSocket Hub + 事件封装
│   ├── orchestrator.py             # 主 Agent 协调器（任务拆解、分派、聚合）
│   ├── dag_engine.py               # 子任务 DAG 执行引擎
│   ├── router_client.py            # Router 注册客户端
│   ├── configure_key.py            # API Key 配置工具
│   ├── dev_server.py               # 开发服务器入口
│   ├── adapters/                   # Agent 适配器
│   │   ├── base.py                 # 抽象基类
│   │   ├── claude_code.py          # Claude Code CLI 适配
│   │   ├── claude_agent_sdk.py     # Claude Agent SDK 适配
│   │   ├── codex.py                # Codex CLI 适配
│   │   ├── mock.py                 # Mock 适配（开发用）
│   │   └── sdk_client_pool.py      # SDK 客户端池管理
│   ├── api/                        # REST 路由
│   │   ├── rest.py                 # 会话 / Agent / 消息 CRUD
│   │   ├── artifacts.py            # 产物管理
│   │   ├── deploy.py               # 部署接口
│   │   ├── trace.py                # Trace 查询
│   │   ├── animation.py            # Animation 事件
│   │   └── workspace.py            # 工作区管理
│   ├── services/                   # 业务服务层
│   │   ├── conversation.py         # 会话服务
│   │   ├── message.py              # 消息服务
│   │   ├── agent.py                # Agent 管理
│   │   ├── artifact.py             # 产物管理
│   │   ├── task.py                 # 任务状态机
│   │   ├── trace.py                # 链路追踪
│   │   ├── deploy.py               # 部署服务
│   │   ├── context_manager.py      # 上下文窗口管理
│   │   ├── content_schema.py       # 富媒体内容 Schema
│   │   ├── react_loop.py           # Agent React 循环
│   │   ├── tool_registry.py        # 工具注册中心
│   │   ├── animation_bus.py        # Animation 事件总线
│   │   ├── sub_agent_gate.py       # Sub-Agent 网关
│   │   ├── spells.py               # 命令解析
│   │   └── secrets.py              # 密钥管理
│   ├── db/                         # 数据库
│   │   ├── models.py               # ORM 模型
│   │   ├── engine.py               # 引擎 + 会话工厂
│   │   └── seed.py                 # 默认数据种子
│   ├── handlers/                   # WebSocket 事件处理器
│   │   ├── __init__.py              # dispatch 入口 + 事件注册（ping/echo 内联）
│   │   ├── send_message.py         # 消息发送
│   │   ├── join.py                 # 加入会话
│   │   └── cancel.py               # 取消生成
│   ├── tests/                      # 后端测试
│   ├── static/                     # 静态文件
│   └── surface/                    # 外部渠道集成（飞书等）
│
├── web/                            # React 前端
│   ├── src/
│   │   ├── App.tsx                 # 应用根组件
│   │   ├── main.tsx                # 入口
│   │   ├── types.ts                # TypeScript 类型定义
│   │   ├── index.css               # 全局样式 + Tailwind
│   │   ├── components/             # 组件
│   │   │   ├── ConversationListPanel.tsx  # 会话列表
│   │   │   ├── MessagePanel.tsx           # 消息流面板
│   │   │   ├── MessageBubble.tsx          # 消息气泡
│   │   │   ├── Composer.tsx               # 输入框 + 发送
│   │   │   ├── ContextSidebar.tsx         # 上下文侧栏
│   │   │   ├── MemberPanel.tsx            # 成员面板
│   │   │   ├── WorkspacePanel.tsx         # 工作区面板
│   │   │   ├── AgentWorkspacePage.tsx     # Agent 工作区页
│   │   │   ├── ArtifactEditor.tsx         # 产物编辑器（Monaco）
│   │   │   ├── VersionHistoryPanel.tsx    # 版本历史
│   │   │   ├── CollaborationProgressCard.tsx  # 协作进度卡片
│   │   │   ├── TaskStatusCard.tsx         # 任务状态卡片
│   │   │   ├── MentionPopover.tsx         # @提及弹窗
│   │   │   ├── NewConversationDialog.tsx  # 新建会话弹窗
│   │   │   ├── AgentCreateDialog.tsx      # 创建 Agent 弹窗
│   │   │   ├── Header.tsx                 # 顶部栏
│   │   │   ├── TabBar.tsx                 # 标签栏
│   │   │   ├── AgentGraph/               # Animation 可视化组件
│   │   │   │   ├── AgentGraph.tsx        # Agent 协作图
│   │   │   │   ├── AgentNode.tsx         # Agent 节点
│   │   │   │   ├── AgentBeam.tsx         # 协作连接线
│   │   │   │   └── useAgentGraph.ts      # 图状态 Hook
│   │   │   └── ContentRenderer/          # 富媒体内容渲染
│   │   │       ├── TextBubble.tsx        # 文本/Markdown
│   │   │       ├── CodeBlock.tsx         # 代码块
│   │   │       ├── DiffCard.tsx          # Diff 卡片
│   │   │       ├── PreviewCard.tsx       # 网页预览
│   │   │       ├── FileCard.tsx          # 文件卡片
│   │   │       ├── FilePreviewPane.tsx   # 文件预览面板
│   │   │       └── StatusCards.tsx       # 任务/部署状态卡片
│   │   ├── stores/                 # 状态管理 (Zustand)
│   │   │   ├── useChatStore.ts     # 聊天状态
│   │   │   ├── reducer.ts          # 消息流 Reducer
│   │   │   └── reducer.test.ts     # Reducer 单元测试
│   │   ├── hooks/                  # 自定义 Hooks
│   │   │   └── useAnimationStream.ts  # Animation SSE 流
│   │   ├── ws/                     # WebSocket
│   │   │   └── client.ts          # WS 客户端
│   │   └── api/                    # API 客户端
│   │       └── client.ts          # HTTP 请求封装
│   ├── package.json
│   ├── vite.config.ts              # Vite 配置（含 API 代理）
│   ├── tailwind.config.js
│   └── vitest.config.ts
│
├── src/                            # v1 调度器 / Router 能力沉淀（保留，可独立运行）
│   ├── router/                     # 消息路由
│   ├── scheduler/                  # 任务调度
│   ├── protocol/                   # 通信协议
│   ├── state/                      # 状态管理
│   ├── storage/                    # 存储
│   ├── api/                        # API
│   ├── cli/                        # CLI 工具
│   ├── launcher/                   # 启动器
│   └── validation/                 # 校验
│
├── docs/                           # 设计与架构文档
│   ├── ARCHITECTURE.md             # 技术架构文档
│   ├── design.md                   # 原有终端版设计
│   ├── main-members-workflow.md    # 主从协作协议
│   ├── multi-agent-checklist.md    # 多 Agent 验收清单
│   ├── 产品设计文档.md              # 产品设计详细文档
│   └── v1-terminal.md              # v1 终端版说明
│
├── prompts/                        # Agent 系统提示词
│   ├── agent_system.md             # 系统提示词主文件
│   ├── agent_main.txt              # MAIN Agent 角色
│   ├── agent_frontend.txt          # Frontend Agent 角色
│   ├── agent_backend.txt           # Backend Agent 角色
│   ├── agent_database.txt          # Database Agent 角色
│   ├── agent_check.txt             # Check Agent 角色
│   ├── agent_helper.txt            # Helper Agent 角色
│   ├── agent_idea.txt              # Idea Agent 角色
│   ├── agent_delivery.txt          # Delivery Agent 角色
│   └── agent_member.txt            # Member Agent 角色
│
├── ai-collab/                      # AI 协作规范
├── aidoc/                          # AI 文档（自动生成）
├── config/                         # 项目配置
├── fixtures/                       # 测试 Fixtures
├── scripts/                        # 辅助脚本
├── workspaces/                     # Agent 工作区（运行时生成）
├── tests/                          # v1 调度器旧测试
│
├── CHANGELOG.md                    # 变更日志
├── CONTRIBUTING.md                 # 贡献指南
├── COURSE_PROPOSAL.md              # 课题方案
├── EXAMPLES.md                     # 使用示例
├── MULTI_AGENT_ARCHITECTURE.md     # 多 Agent 架构说明
├── REBUILD_PLAN.md                 # 重建计划
├── SECURITY.md                     # 安全说明
└── SUPPORT.md                      # 支持信息
```

---

## 快速启动

### 环境要求

- Python 3.11+
- Node.js 20+
- Windows / macOS / Linux

### 1. 克隆项目

```powershell
git clone <repo-url>
cd Agentia
```

### 2. 启动后端

```powershell
# 创建虚拟环境
python -m venv server\.venv

# 安装依赖
server\.venv\Scripts\python.exe -m pip install -r server\requirements.txt

# 配置 API Key（可选，使用 Mock Adapter 时可跳过）
server\.venv\Scripts\python.exe server\configure_key.py

# 启动服务 (默认 http://127.0.0.1:8788)
server\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8788 --app-dir server
```

验证：打开浏览器访问 <http://localhost:8788/health>，应返回 `{"status": "ok", ...}`。
浏览器直接访问 <http://localhost:8788/> 可打开内建的调试控制台（独立于 React 前端），用于快速验证 WS 连接和 API 是否正常。

### 3. 启动前端

```powershell
cd web

# 安装依赖
npm install

# 启动开发服务器 (默认 http://localhost:5173)
npm run dev
```

浏览器打开 <http://localhost:5173/> 即可使用。

> **说明**：Vite 开发服务器已将 `/api`、`/ws`、`/health`、`/preview` 代理到后端 `127.0.0.1:8788`，无需额外配置。

---

## WebSocket 协议

WebSocket 地址：`ws://127.0.0.1:8788/ws`

### 客户端 → 服务端

| 事件           | 说明                                                              |
| -------------- | ----------------------------------------------------------------- |
| `ping`         | 心跳（服务端回复 `pong`）                                         |
| `echo`         | 回显测试（服务端原样返回）                                        |
| `join`         | 加入会话，服务端返回 `history` 回放历史消息                       |
| `send_message` | 发送消息，支持 `mentions` 指定目标 Agent，支持 `attachments` 附件 |
| `cancel`       | 取消当前正在生成的 Agent 回复                                     |

### 服务端 → 客户端

| 事件                                  | 说明                                                         |
| ------------------------------------- | ------------------------------------------------------------ |
| `hello`                               | 连接成功，返回 `conn_id`                                     |
| `pong`                                | 心跳响应                                                     |
| `echo`                                | 回显响应（原样返回客户端 echo 消息）                         |
| `history`                             | 历史消息批量推送，含 `messages`、`tasks`、`count`            |
| `message_created`                     | 新消息已创建（含完整 Message 对象）                          |
| `agent_typing`                        | Agent 开始生成回复                                           |
| `stream_chunk`                        | 流式 Token 推送（含 `seq` 序号）                             |
| `message_done`                        | 消息生成完成（含 `final_content`）                           |
| `message_cancelled`                   | 消息已被取消（含已生成的部分内容）                           |
| `usage`                               | Token 用量统计（`input_tokens` / `output_tokens`）           |
| `error`                               | 错误事件（含 `code`、`message`，可能含 `degraded` 降级标记） |
| `agents`                              | Agent 列表推送                                               |
| `task_update`                         | 任务状态更新（`created` / `status_changed` / `completed`）   |
| `artifact_ready`                      | 新产物就绪（含完整 Artifact 对象）                           |
| `deploy_status`                       | 部署状态变更                                                 |
| `tool_call`                           | Agent 工具调用通知（含 `tool_name`、`status`）               |
| `message_pinned` / `message_unpinned` | 消息 Pin 状态变更                                            |
| `context_info`                        | 上下文窗口统计（含 `estimated_tokens`、`strategy`）          |
| `workspace_file_changed`              | 工作区文件变更通知（`created` / `modified` / `deleted`）     |
| `anim_agent_created`                  | Animation：Agent 节点创建                                    |
| `anim_agent_status`                   | Animation：Agent 节点状态变化                                |
| `anim_beam`                           | Animation：协作关系连接线                                    |
| `anim_event`                          | Animation：通用事件                                          |

---

## REST API 概览

### 会话管理

| Method  | Path                                      | 说明                                          |
| ------- | ----------------------------------------- | --------------------------------------------- |
| `GET`   | `/api/conversations`                      | 会话列表（支持 `?include_archived=` / `?q=`） |
| `POST`  | `/api/conversations`                      | 创建单聊或群聊                                |
| `GET`   | `/api/conversations/{id}`                 | 会话详情                                      |
| `PATCH` | `/api/conversations/{id}`                 | 更新标题、置顶、归档                          |
| `GET`   | `/api/conversations/{id}/messages`        | 分页读取历史消息                              |
| `GET`   | `/api/conversations/{id}/pinned-messages` | 读取已 Pin 消息                               |
| `GET`   | `/api/conversations/{id}/context-stats`   | 上下文统计                                    |

### Agent 管理

| Method   | Path                          | 说明             |
| -------- | ----------------------------- | ---------------- |
| `GET`    | `/api/agents`                 | Agent 列表       |
| `POST`   | `/api/agents`                 | 创建自定义 Agent |
| `PUT`    | `/api/agents/{id}`            | 更新 Agent 配置  |
| `DELETE` | `/api/agents/{id}`            | 删除 Agent       |
| `GET`    | `/api/agents/{id}/prompt`     | 查看系统提示词   |
| `GET`    | `/api/agents/{id}/executions` | 查看执行记录     |

### 其他

| Method     | Path                                  | 说明                         |
| ---------- | ------------------------------------- | ---------------------------- |
| `GET`      | `/health`                             | 健康检查                     |
| `GET/POST` | `/api/artifacts/*`                    | 产物 CRUD + 版本管理         |
| `POST`     | `/api/upload`                         | 文件上传                     |
| `GET`      | `/preview/{artifact_id}`              | 产物预览页面                 |
| `GET`      | `/api/trace/{message_id}`             | 执行链路追踪                 |
| `GET`      | `/deploy/preview/{conversation_id}/*` | 部署产物预览（静态站点托管） |
| `GET/POST` | `/api/conversations/{id}/workspace/*` | 工作区文件树浏览与配置       |
| `GET`      | `/api/animation-stream`               | Animation 事件流 (SSE)       |

---

## Agent 适配器

Adapter 抽象层统一了不同 Agent 后端的接入方式，新增 Agent 类型只需继承 `AgentAdapter` 并实现 `send()` 和 `capabilities()`：

```python
class AgentAdapter(abc.ABC):
    name: str = "unknown"

    @abc.abstractmethod
    def send(self, messages, *, tools=None, artifacts_context=None, stream=True) -> AsyncIterator[Chunk]:
        """返回 Chunk 联合类型: ChunkText | ChunkToolCall | ChunkArtifact | ChunkUsage | ChunkError | ChunkDone"""
        ...

    @abc.abstractmethod
    def capabilities(self) -> list[str]:
        """能力声明，例如 ["code", "web", "tool_use"]"""
        ...

    async def cancel(self, message_id: str) -> None:
        """可选实现：按 message_id 主动中断外部请求"""
        ...
```

**设计要点**：Mock Adapter 若配置了 `api_key`，会自动升级为 Codex（OpenAI 兼容 API），基于 DB 中的 `system_prompt` 驱动 Agent 行为，无需修改代码。

当前支持的适配器：

- **MockAdapter** — 模拟 Agent 回复，无需外部依赖。配置 API Key 后自动升级为 Codex（真实大模型调用）
- **ClaudeCodeAdapter** — 调用本地 `claude` CLI，支持文件读写、代码执行
- **ClaudeAgentSDKAdapter** — 基于 `claude-agent-sdk`，支持工具调用确认
- **CodexAdapter** — 接入 OpenAI Codex CLI
- **OpenCodeAdapter** — 接入 OpenCode CLI

### 配置 API Key

```powershell
python server\configure_key.py
```

按提示输入各 Agent 后端的 API Key。Key 存储在 `server/.env` 中。

---

## 测试

### 后端

```powershell
# 运行全部测试
python -m pytest -c server\pyproject.toml server\tests

# 运行冒烟测试
python -m pytest server\tests\smoke_w1.py -v

# 运行特定模块测试
python -m pytest server\tests\test_rest.py -v
python -m pytest server\tests\test_db.py -v
python -m pytest server\tests\test_mock_adapter.py -v
```

测试文件说明：

| 文件                               | 内容                          |
| ---------------------------------- | ----------------------------- |
| `smoke_day1.py` ~ `smoke_day4.py`  | 分天冒烟测试                  |
| `smoke_w1.py`                      | W1 集成冒烟测试               |
| `test_rest.py`                     | REST API 测试                 |
| `test_db.py`                       | 数据库模型测试                |
| `test_mock_adapter.py`             | Mock Adapter 测试             |
| `test_adapter_claude.py`           | Claude Code Adapter 测试      |
| `test_adapter_claude_agent_sdk.py` | Claude Agent SDK Adapter 测试 |
| `test_adapter_codex.py`            | Codex Adapter 测试            |
| `test_orchestrator_im_recovery.py` | Orchestrator IM 恢复测试      |
| `test_spells_and_agent_tools.py`   | 命令解析与工具注册测试        |
| `test_w2_fan_out.py`               | 群聊 Fan-out 测试             |

### 前端

```powershell
cd web

# 运行测试
npm test

# Watch 模式
npm run test:watch
```

## 推荐 Demo 流程

1. **新建群聊**：选择 Orchestrator、Frontend、Backend、Database、Test Agent
2. **发送任务**：`@Orchestrator 帮我实现一个登录页，包括前端页面、后端接口、数据库表设计和测试建议`
3. **观察协作**：Orchestrator 自动拆解任务 → 多个 Agent 并行/串行回复 → 实时流式展示
4. **查看产物**：网页预览卡片、代码编辑器、版本历史和 Diff 应用
5. **说明扩展**：部署发布、桌面端/移动端作为 P2 扩展方向

---

## 相关文档

- [技术架构详细设计](docs/ARCHITECTURE.md)
- [产品设计文档](docs/产品设计文档.md)
- [多 Agent 架构说明](MULTI_AGENT_ARCHITECTURE.md)
- [主从协作协议](docs/main-members-workflow.md)
- [使用示例](EXAMPLES.md)
- [课题方案](COURSE_PROPOSAL.md)
- [安全说明](SECURITY.md)
- [贡献指南](CONTRIBUTING.md)

## License

本项目采用 MIT License，详见 [LICENSE](LICENSE)。
