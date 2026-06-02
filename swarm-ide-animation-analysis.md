# swarm-ide Agent 动画编排机制分析 & 迁移方案 (v2 深化版)

> 分析日期：2026-05-27
> 源项目：[chmod777john/swarm-ide](https://github.com/chmod777john/swarm-ide)（`chore/specs-mvp` 分支）
> 目标项目：[520saber521/Agentia](https://github.com/520saber521/Agentia.git)

---

## 第一部分：swarm-ide 核心架构深度拆解

swarm-ide 的整体运行模型可以概括为：**"IM 群里跑 Agent 集群"**——每个 Agent 就像一个微信群成员，通过内置工具（`create`、`send`、`list_agents` 等）自主地创建子 Agent、组建群聊、发送消息。前端通过 **Framer Motion 动画的 SVG 树图** 实时可视化整个 Agent 集群的拓扑结构和通信链路。

### 1.1 四层事件总线架构

swarm-ide 的事件系统是其最精巧的设计，分为 **四个独立的事件通道**：

```
┌──────────────────────────────────────────────────────────────────┐
│                     swarm-ide 事件总线架构                         │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────┐   ┌─────────────────┐                       │
│  │ AgentEventBus   │   │ WorkspaceUIBus  │                       │
│  │ (per-agent)     │   │ (per-workspace) │                       │
│  │                 │   │                 │                       │
│  │ agent.stream    │   │ ui.agent.created│  ← 前端 Graph 动画消费 │
│  │ agent.wakeup    │   │ ui.message.     │                       │
│  │ agent.done      │   │    created      │  ← 前端 Beam 连线消费 │
│  │ agent.error     │   │ ui.agent.llm.   │                       │
│  │ agent.unread    │   │   start/done    │  ← 节点状态 BUSY/IDLE │
│  └────────┬────────┘   │ ui.agent.tool_  │                       │
│           │            │   call.start/   │                       │
│           │            │   done          │                       │
│           │            └────────┬────────┘                       │
│           │                     │                                 │
│  ┌────────▼────────┐   ┌───────▼──────────┐                      │
│  │ Server-Sent     │   │ Upstash Realtime │  ← 跨进程/历史回放   │
│  │ Events (SSE)    │   │ (pub/sub)       │                      │
│  │ /api/agents/:id │   │                 │                      │
│  │ /context-stream │   │                 │                      │
│  └────────┬────────┘   └─────────────────┘                      │
│           │                                                      │
│  ┌────────▼─────────────────────────────────┐                    │
│  │ 前端 IMPage 消费层                          │                   │
│  │ • uiEsRef (EventSource → UI事件)           │                   │
│  │ • esRef (EventSource → Agent流式输出)       │                   │
│  │ → vizEvents / vizBeams / agentStatusById   │                   │
│  └───────────────────────────────────────────┘                   │
└──────────────────────────────────────────────────────────────────┘
```

### 1.2 Agent 运行时：自主创建子 Agent + IM 群聊编排

每个 Agent 是一个 `AgentRunner` 实例，运行一个 `processUntilIdle` 循环。Agent 拥有 13 个内置工具：

| 工具 | 功能 | 编排角色 |
|------|------|----------|
| `create(role, guidance)` | 创建子 Agent | **集群扩展** |
| `send(to, content)` | 发送私聊 | **点对点通信** |
| `send_group_message(groupId, content)` | 群聊发言 | **群组通信** |
| `send_direct_message(toAgentId, content)` | 直接消息 | **点对点通信** |
| `list_agents()` | 列出所有 Agent | **拓扑感知** |
| `list_groups()` | 列出所有群组 | **拓扑感知** |
| `create_group(memberIds)` | 创建群组 | **动态组网** |
| `get_group_messages(groupId)` | 读取群聊历史 | **上下文获取** |
| `self()` | 获取自身身份 | **身份感知** |
| `get_skill(skill_name)` | 加载技能 | **能力扩展** |
| `bash(command)` | 执行 Shell | **操作执行** |
| MCP 扩展工具 | 外部工具集成 | **能力扩展** |

### 1.3 前端可视化：SVG + Framer Motion 动画体系

核心数据结构：

```typescript
type VizEvent = {
  id: string;
  kind: "agent" | "message" | "llm" | "tool" | "db";
  label: string;
  at: number;
};

type VizBeam = {
  id: string;
  fromId: UUID;
  toId: UUID;
  kind: "create" | "message";
  label?: string;
  createdAt: number;
  // 2.4秒后自动消失
};

type AgentStatus = "IDLE" | "BUSY" | "WAKING";
```

动画细节：
- **节点入场**：Spring 弹性动画（stiffness: 220, damping: 18）
- **BUSY 状态**：旋转光环（duration: 1s, repeat: Infinity, ease: "linear"）
- **连线 Beam**：光点沿路径运动（duration: 0.8s, easeInOut）+ 虚线描边动画（duration: 0.5s）+ 发光滤镜（drop-shadow）
- **事件流面板**：右下角可折叠，实时滚动展示事件日志

---

## 第二部分：Agentia 现有架构（深化分析）

### 2.1 项目结构总览

```
Agentia/
├── server/                          # FastAPI 后端
│   ├── main.py                      # FastAPI 入口 + WS 接入
│   ├── ws.py                        # WS Hub + Connection 管理
│   ├── orchestrator.py              # @Orchestrator 任务拆解与分派
│   ├── dag_engine.py                # 事件驱动 DAG 执行器
│   ├── adapters/                    # Agent 适配器层
│   │   ├── base.py                  # AgentAdapter 抽象基类
│   │   ├── claude_code.py           # Claude Code 适配器
│   │   ├── codex.py                 # OpenAI Codex 适配器
│   │   └── mock.py                  # Mock 适配器（测试用）
│   ├── handlers/                    # WS 事件处理器
│   │   ├── __init__.py              # dispatch() 路由
│   │   ├── send_message.py          # 消息发送 + fan-out + agent_reply
│   │   ├── join.py                  # 加入会话
│   │   └── cancel.py                # 取消生成
│   ├── services/                    # 业务服务层
│   │   ├── agent.py                 # Agent CRUD
│   │   ├── message.py               # 消息 CRUD
│   │   ├── conversation.py          # 会话 CRUD
│   │   ├── task.py                  # 任务状态机
│   │   ├── react_loop.py            # ReAct 循环引擎
│   │   ├── tool_registry.py         # 工具注册中心
│   │   ├── context_manager.py       # 上下文管理器（4层架构）
│   │   ├── artifact.py              # 产物管理
│   │   └── trace.py                 # 链路追踪
│   ├── db/                          # 数据库层
│   │   ├── engine.py                # SQLAlchemy async engine
│   │   ├── models.py                # ORM 模型（Agent/Message/Conversation/Task）
│   │   └── seed.py                  # 种子数据
│   └── api/                         # REST API
│       ├── rest.py                  # CRUD 端点
│       ├── artifacts.py             # 产物端点
│       └── trace.py                 # 追踪端点
│
├── src/                             # 核心调度引擎（独立模块）
│   ├── scheduler/                   # 任务调度
│   │   ├── scheduler.py             # TaskScheduler 主类
│   │   ├── complexity.py            # ComplexityJudge 复杂度分析
│   │   ├── decomposer.py            # TaskDecomposer 任务拆解
│   │   ├── enhanced_decomposer.py   # EnhancedTaskDecomposer（契约优先）
│   │   ├── collaboration.py         # CollaborationHub 协作中心
│   │   ├── agents.py                # Agent 匹配与分配
│   │   └── aggregator.py            # 结果聚合
│   └── router/                      # 消息路由
│       └── router.py                # Router 客户端
│
└── web/                             # React 前端
    └── src/
        ├── App.tsx                  # 主布局（3栏：会话列表/消息面板/上下文侧栏）
        ├── types.ts                 # 类型定义（ServerEvent/Message/Task 等）
        ├── stores/
        │   ├── reducer.ts           # 纯 reducer（事件→状态转换）
        │   └── useChatStore.ts      # Zustand store
        ├── ws/
        │   └── client.ts            # WebSocket 客户端
        ├── components/
        │   ├── MessagePanel.tsx      # 消息列表面板
        │   ├── MessageBubble.tsx     # 消息气泡
        │   ├── Composer.tsx          # 输入框（@mention 支持）
        │   ├── CollaborationProgressCard.tsx  # 协作进度卡片 ⭐当前唯一可视化
        │   ├── TaskStatusCard.tsx    # 单任务状态卡片
        │   ├── Header.tsx           # 顶部导航
        │   ├── ConversationListPanel.tsx  # 会话列表
        │   ├── ContextSidebar.tsx    # 上下文侧栏
        │   ├── MentionPopover.tsx    # @mention 弹窗
        │   ├── ContentRenderer/     # 内容渲染器
        │   ├── ArtifactEditor.tsx    # 产物编辑器（Monaco）
        │   └── AgentCreateDialog.tsx # Agent 创建对话框
        └── api/
            └── client.ts            # REST API 客户端
```

### 2.2 现有 WebSocket 事件体系

当前已有的事件类型非常丰富，可作为动画事件的直接数据源：

| 事件类型 | 触发时机 | 可用于动画 |
|----------|----------|-----------|
| `message_created` | 新消息创建（含 agent 消息） | → beam 连线动画起点 |
| `agent_typing` | Agent 开始生成 | → 节点 BUSY 状态 |
| `stream_chunk` | 流式文本增量 | → 实时文本面板 |
| `message_done` | Agent 生成完成 | → 节点 IDLE 状态 |
| `message_cancelled` | 生成被取消 | → 节点 IDLE 状态 |
| `task_update` | 任务状态变更 | → DAG 节点状态变化 |
| `tool_call` | 工具调用事件 | → 工具动画脉冲 |
| `artifact_ready` | 产物就绪 | → 节点产出物标记 |
| `context_info` | 上下文统计 | → 上下文面板 |

### 2.3 现有 Orchestrator 编排流程

```
用户消息 → resolve_targets() → @Orchestrator 被提及？

  ├─ 是 → _run_orchestrator() → handle_orchestrator_mention()
  │         ├─ emit planning task_update
  │         ├─ LLM 分类任务类型
  │         ├─ EnhancedTaskDecomposer 拆解子任务
  │         ├─ DAG 构建（依赖关系）
  │         ├─ DAGExecutor 并行调度
  │         │    ├─ run_agent_reply() × N 个 Agent 并发
  │         │    └─ 每个 emit task_update + stream_chunk + message_done
  │         ├─ 结果聚合（分析冲突）
  │         └─ 生成 preview HTML
  │
  └─ 否 → run_agent_reply() 直接回复
```

### 2.4 与 swarm-ide 的关键差距

| 维度 | swarm-ide | Agentia | 差距分析 |
|------|-----------|---------|----------|
| **Agent 间通信** | Agent 通过 IM 工具 **自主** 发消息、建群、创建子 Agent | 通过 Orchestrator **中心化** 分配任务 | ⚠️ 需要增加 Agent 自主通信能力 |
| **Agent 拓扑** | **动态树形结构**，Agent 自主 `create` 子 Agent | 静态 DAG，由 Orchestrator 预定义任务图 | ⚠️ 已有 DAG + parent_task_id，可扩展为动态树 |
| **可视化** | **SVG + Framer Motion 实时动画树图** | 仅静态 `CollaborationProgressCard` | ❌ 需要全新开发 |
| **实时流** | WorkspaceUIBus → SSE → 驱动动画 | WS → reducer → 更新消息列表 | ⚠️ WS 事件体系已完善，只需增加动画消费层 |
| **编排模式** | Spells 自然语言协议，Agent 自组织 | Scheduler 代码逻辑拆解 + DAG | ⚠️ 已有 LLM 驱动的分解器，方向一致 |

---

## 第三部分：深化优化方案

### 总体策略：三阶段渐进式迁移

```
Phase 1: 最小可行动画层 — 在现有 DAG 上添加 Framer Motion 可视化（2-3周）
Phase 2: 增强事件体系 — 动画专用事件 + 实时状态追踪（1-2周）
Phase 3: Agent 自组织能力 — 给 Agent 添加 IM 通信工具 + Spells 协议（3-4周）
```

---

## Phase 1：前端动画可视化层（推荐立即启动）

### 目标
在不改变 Agentia 后端调度逻辑的前提下，为 DAG 任务执行添加 swarm-ide 风格的 SVG 树图动画。**利用现有 WS 事件驱动动画**，无需新增后端代码。

### 1.1 安装依赖

```bash
cd web
npm install framer-motion
```

### 1.2 新增文件清单

| 文件 | 作用 |
|------|------|
| `web/src/components/AgentGraph/types.ts` | 动画相关类型定义 |
| `web/src/components/AgentGraph/layout.ts` | 树图布局算法（移植自 swarm-ide） |
| `web/src/components/AgentGraph/AgentNode.tsx` | 单个 Agent 节点组件（Spring 入场 + BUSY 光环） |
| `web/src/components/AgentGraph/AgentBeam.tsx` | Agent 间连线动画组件（光点飞行） |
| `web/src/components/AgentGraph/AgentGraph.tsx` | SVG 画布容器（缩放/平移/拖拽） |
| `web/src/components/AgentGraph/EventStreamPanel.tsx` | 右下角实时事件流面板 |
| `web/src/components/AgentGraph/index.tsx` | 导出入口 |
| `web/src/components/AgentGraph/useAgentGraph.ts` | 动画状态管理 Hook（消费现有 WS 事件） |

### 1.3 核心实现：`useAgentGraph` Hook

这个 Hook 是动画层的核心，它**复用现有的 `useChatStore`**，从已有 `tasks`、`messages` 数据中推导出动画状态：

```typescript
// web/src/components/AgentGraph/useAgentGraph.ts

import { useMemo, useState, useCallback, useEffect } from "react";
import { useChatStore } from "../../stores/useChatStore";
import type { Task, Message } from "../../types";

// ---- 动画数据结构（与 swarm-ide 对齐）----
export interface AnimAgentNode {
  id: string;
  role: string;
  parentId: string | null;
  status: "IDLE" | "BUSY" | "WAKING";
  domain?: string;
  agentName?: string;
}

export interface AnimBeam {
  id: string;
  fromId: string;
  toId: string;
  kind: "create" | "message";
  label?: string;
  createdAt: number;
}

export interface AnimEvent {
  id: string;
  kind: "agent" | "message" | "llm" | "tool";
  label: string;
  at: number;
}

interface UseAgentGraphReturn {
  nodes: AnimAgentNode[];
  beams: AnimBeam[];
  events: AnimEvent[];
  nodeStatusMap: Record<string, "IDLE" | "BUSY" | "WAKING">;
  orchestratorId: string | null;
}

export function useAgentGraph(): UseAgentGraphReturn {
  const tasks = useChatStore((s) => s.tasks);
  const messages = useChatStore((s) => s.messages);
  const streamingIds = useChatStore((s) => s.streamingMessageIds);
  const currentConvId = useChatStore((s) => s.currentConvId);

  // 从 tasks 推导 Agent 节点树
  const { nodes, orchestratorId, beams, events } = useMemo(() => {
    const taskList = currentConvId
      ? Object.values(tasks).filter((t) => t.conversation_id === currentConvId)
      : [];

    const convMessages = currentConvId
      ? messages.filter((m) => m.conversation_id === currentConvId)
      : [];

    // 1. 构建 Agent 节点：从 task 的 assigned_agent_id 提取
    const nodeMap = new Map<string, AnimAgentNode>();
    const seenAgents = new Set<string>();

    // Orchestrator 始终作为根节点
    const orchId = "agent_orchestrator";
    nodeMap.set(orchId, {
      id: orchId,
      role: "Orchestrator",
      parentId: null,
      status: "IDLE",
      agentName: "Orchestrator",
    });

    for (const task of taskList) {
      const agentId = task.assigned_agent_id;
      if (!agentId || seenAgents.has(agentId)) continue;
      seenAgents.add(agentId);

      // 判断 BUSY 状态：检查是否有该 agent 的消息正在 streaming
      const isStreaming = convMessages.some(
        (m) =>
          m.sender_id === agentId &&
          streamingIds.includes(m.id)
      );

      nodeMap.set(agentId, {
        id: agentId,
        role: task.domain || "agent",
        parentId: task.parent_task_id ? orchId : orchId, // 子任务的父节点都是 Orchestrator
        status: isStreaming ? "BUSY" : "IDLE",
        domain: task.domain || undefined,
        agentName: task.agent_name || undefined,
      });
    }

    // 2. 构建连线 Beams：从 task 的 depends_on 关系推导
    const beams: AnimBeam[] = [];
    for (const task of taskList) {
      if (!task.assigned_agent_id || task.status === "planning") continue;

      // 子任务 → Orchestrator 的连线
      if (task.parent_task_id) {
        beams.push({
          id: `beam-${task.id}-orch`,
          fromId: orchId,
          toId: task.assigned_agent_id,
          kind: "create",
          label: `分派: ${task.title?.slice(0, 20)}`,
          createdAt: task.created_at,
        });
      }

      // 任务间依赖连线
      if (task.depends_on) {
        for (const depId of task.depends_on) {
          const depTask = taskList.find((t) => t.id === depId);
          if (depTask?.assigned_agent_id && task.assigned_agent_id) {
            beams.push({
              id: `beam-dep-${depId}-${task.id}`,
              fromId: depTask.assigned_agent_id,
              toId: task.assigned_agent_id,
              kind: "message",
              label: `依赖: ${depTask.title?.slice(0, 20)}`,
              createdAt: task.created_at,
            });
          }
        }
      }
    }

    // 3. 构建事件流
    const events: AnimEvent[] = [];
    for (const task of taskList) {
      if (task.status === "running") {
        events.push({
          id: `evt-${task.id}-running`,
          kind: "llm",
          label: `${task.agent_name || task.domain}: 执行中`,
          at: task.updated_at || task.created_at,
        });
      } else if (task.status === "done") {
        events.push({
          id: `evt-${task.id}-done`,
          kind: "llm",
          label: `${task.agent_name || task.domain}: 完成`,
          at: task.updated_at || task.created_at,
        });
      }
    }

    // 对话消息事件
    for (const msg of convMessages) {
      if (msg.sender_type === "agent") {
        events.push({
          id: `evt-msg-${msg.id}`,
          kind: "message",
          label: `消息: ${msg.sender_id?.slice(0, 8)}`,
          at: msg.created_at,
        });
      }
    }

    return {
      nodes: Array.from(nodeMap.values()),
      orchestratorId: orchId,
      beams,
      events: events.sort((a, b) => b.at - a.at).slice(0, 50),
    };
  }, [tasks, messages, streamingIds, currentConvId]);

  // 状态映射
  const nodeStatusMap = useMemo(() => {
    const map: Record<string, "IDLE" | "BUSY" | "WAKING"> = {};
    for (const node of nodes) {
      map[node.id] = node.status;
    }
    return map;
  }, [nodes]);

  return { nodes, beams, events, nodeStatusMap, orchestratorId };
}
```

### 1.4 树图布局算法（移植自 swarm-ide）

```typescript
// web/src/components/AgentGraph/layout.ts

import type { AnimAgentNode } from "./useAgentGraph";

export interface LayoutNode {
  id: string;
  x: number;
  y: number;
  role: string;
  parentId: string | null;
}

export function computeTreeLayout(
  nodes: AnimAgentNode[],
  humanId: string | null,
  nodeOffsets: Record<string, { x: number; y: number }>,
  viewport: { width: number; height: number },
): LayoutNode[] {
  const paddingX = 70;
  const paddingY = 60;

  const byId = new Map(nodes.map((n) => [n.id, n]));
  const childrenById = new Map<string, AnimAgentNode[]>();
  const roots: AnimAgentNode[] = [];

  for (const node of nodes) {
    if (!node.parentId || !byId.has(node.parentId)) {
      roots.push(node);
    } else {
      const children = childrenById.get(node.parentId) || [];
      children.push(node);
      childrenById.set(node.parentId, children);
    }
  }

  // 将 Orchestrator 排在 roots 最前面
  roots.sort((a) => (a.id === "agent_orchestrator" ? -1 : 1));

  const result: LayoutNode[] = [];
  let leafIndex = 0;
  const depthOffsets: Record<number, number> = {};

  function dfs(node: AnimAgentNode, depth: number): number {
    const children = childrenById.get(node.id) || [];
    if (children.length === 0) {
      const x = leafIndex * paddingX + 60;
      leafIndex++;
      const y = depth * 90 + 80;
      result.push({ id: node.id, x, y, role: node.role, parentId: node.parentId });
      return x;
    }
    const childXs = children.map((c) => dfs(c, depth + 1));
    const x = (childXs[0] + childXs[childXs.length - 1]) / 2;
    const y = depth * 90 + 80;
    result.push({ id: node.id, x, y, role: node.role, parentId: node.parentId });
    return x;
  }

  for (const root of roots) {
    dfs(root, 0);
  }

  // 应用节点偏移
  const offsetMap = new Map<string, { dx: number; dy: number }>();
  function collectOffset(id: string, dx: number, dy: number) {
    const existing = offsetMap.get(id) || { dx: 0, dy: 0 };
    offsetMap.set(id, { dx: existing.dx + dx, dy: existing.dy + dy });
    const children = childrenById.get(id) || [];
    for (const child of children) {
      collectOffset(child.id, dx, dy);
    }
  }
  for (const [id, offset] of Object.entries(nodeOffsets)) {
    collectOffset(id, offset.x, offset.y);
  }

  for (const node of result) {
    const off = offsetMap.get(node.id);
    if (off) {
      node.x += off.dx;
      node.y += off.dy;
    }
  }

  return result;
}
```

### 1.5 Agent 节点组件（Framer Motion 动画）

```typescript
// web/src/components/AgentGraph/AgentNode.tsx

import { motion } from "framer-motion";

interface Props {
  id: string;
  role: string;
  x: number;
  y: number;
  status: "IDLE" | "BUSY" | "WAKING";
  agentName?: string;
  domain?: string;
  isOrchestrator?: boolean;
  onDragEnd?: (id: string, dx: number, dy: number) => void;
}

const DOMAIN_COLORS: Record<string, string> = {
  frontend: "#3b82f6",
  backend: "#10b981",
  database: "#f59e0b",
  test: "#8b5cf6",
  docs: "#06b6d4",
  devops: "#ef4444",
};

const NODE_SIZE = 56;

export function AgentNode({
  id, role, x, y, status, agentName, domain, isOrchestrator, onDragEnd,
}: Props) {
  const color = DOMAIN_COLORS[domain || ""] || "#6366f1";
  const isBusy = status === "BUSY";

  return (
    <motion.g
      initial={{ scale: 0, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      exit={{ scale: 0, opacity: 0 }}
      transition={{ type: "spring", stiffness: 220, damping: 18 }}
      style={{ cursor: "grab" }}
      drag
      dragMomentum={false}
      onDragEnd={(_, info) => onDragEnd?.(id, info.offset.x, info.offset.y)}
      whileDrag={{ cursor: "grabbing" }}
    >
      {/* BUSY 旋转光环 */}
      {isBusy && (
        <motion.circle
          cx={x}
          cy={y}
          r={NODE_SIZE / 2 + 6}
          fill="none"
          stroke={color}
          strokeWidth={2}
          strokeDasharray="8 4"
          animate={{ rotate: 360 }}
          transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
          style={{ transformOrigin: `${x}px ${y}px` }}
        />
      )}

      {/* 节点背景 */}
      <circle
        cx={x}
        cy={y}
        r={NODE_SIZE / 2}
        fill={isOrchestrator ? "#1e1b4b" : "#0f172a"}
        stroke={color}
        strokeWidth={2}
        style={{ filter: isBusy ? `drop-shadow(0 0 8px ${color}80)` : undefined }}
      />

      {/* 角色图标 */}
      <text
        x={x}
        y={y - 6}
        textAnchor="middle"
        dominantBaseline="central"
        fontSize={14}
        fill={color}
      >
        {isOrchestrator ? "🎯" : domain === "frontend" ? "🎨" :
         domain === "backend" ? "⚙️" : domain === "database" ? "🗄️" :
         domain === "test" ? "🧪" : "🤖"}
      </text>

      {/* 角色名 */}
      <text
        x={x}
        y={y + 14}
        textAnchor="middle"
        dominantBaseline="central"
        fontSize={8}
        fill="#94a3b8"
        fontFamily="system-ui"
      >
        {isOrchestrator ? "Orch" : (domain || role).slice(0, 6)}
      </text>

      {/* Agent 名称标签 */}
      {agentName && (
        <text
          x={x}
          y={y + (NODE_SIZE / 2) + 14}
          textAnchor="middle"
          dominantBaseline="central"
          fontSize={9}
          fill="#e2e8f0"
          fontFamily="system-ui"
        >
          {agentName.length > 10 ? agentName.slice(0, 10) + "…" : agentName}
        </text>
      )}
    </motion.g>
  );
}
```

### 1.6 Beam 连线组件

```typescript
// web/src/components/AgentGraph/AgentBeam.tsx

import { motion } from "framer-motion";

interface Props {
  beamId: string;
  fromX: number;
  fromY: number;
  toX: number;
  toY: number;
  kind: "create" | "message";
  label?: string;
  onComplete: (beamId: string) => void;
}

export function AgentBeam({ beamId, fromX, fromY, toX, toY, kind, label, onComplete }: Props) {
  const color = kind === "create" ? "#6366f1" : "#f59e0b";
  const dashArray = kind === "create" ? "6 4" : "0";

  return (
    <motion.g
      initial={{ opacity: 0 }}
      animate={{ opacity: 0.85 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.6 }}
    >
      {/* 虚线/实线路径 */}
      <motion.line
        x1={fromX}
        y1={fromY}
        x2={toX}
        y2={toY}
        stroke={color}
        strokeWidth={1.5}
        strokeDasharray={dashArray}
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: 1, opacity: 0.6 }}
        transition={{ duration: 0.5 }}
      />

      {/* 飞行光点 */}
      <motion.circle
        r={4}
        fill={color}
        initial={{ cx: fromX, cy: fromY, opacity: 0 }}
        animate={{ cx: toX, cy: toY, opacity: 1 }}
        transition={{ duration: 0.8, ease: "easeInOut" }}
        style={{ filter: `drop-shadow(0 0 6px ${color})` }}
        onAnimationComplete={() => onComplete(beamId)}
      />

      {/* 标签 */}
      {label && (
        <text
          x={(fromX + toX) / 2}
          y={(fromY + toY) / 2 - 8}
          textAnchor="middle"
          fontSize={8}
          fill={color}
          fontFamily="system-ui"
          opacity={0.7}
        >
          {label}
        </text>
      )}
    </motion.g>
  );
}
```

### 1.7 SVG 画布主组件

```typescript
// web/src/components/AgentGraph/AgentGraph.tsx

import { useState, useCallback, useRef } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useAgentGraph } from "./useAgentGraph";
import { computeTreeLayout } from "./layout";
import { AgentNode } from "./AgentNode";
import { AgentBeam } from "./AgentBeam";
import type { AnimBeam } from "./useAgentGraph";

interface Props {
  width?: number;
  height?: number;
}

export function AgentGraph({ width: initialWidth = 800, height: initialHeight = 400 }: Props) {
  const { nodes, beams, events, nodeStatusMap, orchestratorId } = useAgentGraph();
  const [vizOffset, setVizOffset] = useState({ x: 40, y: 40 });
  const [vizScale, setVizScale] = useState(1);
  const [nodeOffsets, setNodeOffsets] = useState<Record<string, { x: number; y: number }>>({});
  const [activeBeams, setActiveBeams] = useState<AnimBeam[]>([]);
  const [showEvents, setShowEvents] = useState(true);
  const svgRef = useRef<SVGSVGElement>(null);
  const isPanning = useRef(false);
  const panStart = useRef({ x: 0, y: 0 });

  // 计算布局
  const layoutNodes = computeTreeLayout(nodes, null, nodeOffsets, {
    width: initialWidth,
    height: initialHeight,
  });

  const layoutMap = new Map(layoutNodes.map((n) => [n.id, n]));

  // Beam 自动过期
  const handleBeamComplete = useCallback((beamId: string) => {
    setActiveBeams((prev) => prev.filter((b) => b.id !== beamId));
  }, []);

  // 当新 beams 出现时添加到活跃列表
  const newBeamIds = new Set(beams.map((b) => b.id));
  const existingBeamIds = new Set(activeBeams.map((b) => b.id));
  for (const beam of beams) {
    if (!existingBeamIds.has(beam.id)) {
      setActiveBeams((prev) => [...prev, beam]);
    }
  }

  // 画布平移交互
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if ((e.target as SVGElement).tagName === "svg") {
      isPanning.current = true;
      panStart.current = { x: e.clientX - vizOffset.x, y: e.clientY - vizOffset.y };
    }
  }, [vizOffset]);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!isPanning.current) return;
    setVizOffset({ x: e.clientX - panStart.current.x, y: e.clientY - panStart.current.y });
  }, []);

  const handleMouseUp = useCallback(() => {
    isPanning.current = false;
  }, []);

  // 缩放
  const handleWheel = useCallback((e: React.WheelEvent) => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    setVizScale((s) => Math.min(2, Math.max(0.5, s - e.deltaY * 0.001)));
  }, []);

  // 节点拖拽
  const handleNodeDragEnd = useCallback((id: string, dx: number, dy: number) => {
    setNodeOffsets((prev) => ({
      ...prev,
      [id]: { x: (prev[id]?.x || 0) + dx, y: (prev[id]?.y || 0) + dy },
    }));
  }, []);

  if (nodes.length <= 1) return null; // 只有 Orchestrator 时不显示

  return (
    <div className="relative rounded-xl border border-border bg-panel/50 overflow-hidden"
         style={{ width: initialWidth, height: initialHeight }}>
      {/* 工具栏 */}
      <div className="absolute top-2 right-2 z-10 flex items-center gap-1">
        <button
          onClick={() => setVizScale((s) => Math.min(2, s + 0.1))}
          className="rounded bg-bg border border-border px-2 py-0.5 text-[10px] text-muted hover:text-fg"
        >
          +
        </button>
        <button
          onClick={() => setVizScale((s) => Math.max(0.5, s - 0.1))}
          className="rounded bg-bg border border-border px-2 py-0.5 text-[10px] text-muted hover:text-fg"
        >
          −
        </button>
        <button
          onClick={() => { setVizOffset({ x: 40, y: 40 }); setVizScale(1); setNodeOffsets({}); }}
          className="rounded bg-bg border border-border px-2 py-0.5 text-[10px] text-muted hover:text-fg"
        >
          Reset
        </button>
        <button
          onClick={() => setShowEvents((v) => !v)}
          className={`rounded border px-2 py-0.5 text-[10px] ${
            showEvents ? "border-accent/40 text-accent" : "border-border text-muted"
          }`}
        >
          事件
        </button>
      </div>

      {/* SVG 画布 */}
      <svg
        ref={svgRef}
        width={initialWidth}
        height={initialHeight}
        className="cursor-grab active:cursor-grabbing"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onWheel={handleWheel}
        style={{ background: "transparent" }}
      >
        <g transform={`translate(${vizOffset.x}, ${vizOffset.y}) scale(${vizScale})`}>
          {/* 连线 Beams */}
          <AnimatePresence>
            {activeBeams.map((beam) => {
              const fromNode = layoutMap.get(beam.fromId);
              const toNode = layoutMap.get(beam.toId);
              if (!fromNode || !toNode) return null;
              return (
                <AgentBeam
                  key={beam.id}
                  beamId={beam.id}
                  fromX={fromNode.x}
                  fromY={fromNode.y}
                  toX={toNode.x}
                  toY={toNode.y}
                  kind={beam.kind}
                  label={beam.label}
                  onComplete={handleBeamComplete}
                />
              );
            })}
          </AnimatePresence>

          {/* Agent 节点 */}
          <AnimatePresence>
            {layoutNodes.map((node) => (
              <AgentNode
                key={node.id}
                id={node.id}
                role={node.role}
                x={node.x}
                y={node.y}
                status={nodeStatusMap[node.id] || "IDLE"}
                agentName={nodes.find((n) => n.id === node.id)?.agentName}
                domain={nodes.find((n) => n.id === node.id)?.domain}
                isOrchestrator={node.id === orchestratorId}
                onDragEnd={handleNodeDragEnd}
              />
            ))}
          </AnimatePresence>
        </g>
      </svg>

      {/* 右下角事件流面板 */}
      <AnimatePresence>
        {showEvents && (
          <motion.div
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 20 }}
            className="absolute bottom-2 right-2 w-56 max-h-36 overflow-y-auto rounded-lg border border-border bg-bg/90 p-2 backdrop-blur"
          >
            <div className="text-[10px] font-medium text-muted mb-1">事件流</div>
            {events.slice(0, 8).map((evt) => (
              <div key={evt.id} className="flex items-center gap-1.5 py-0.5">
                <span className={`w-1.5 h-1.5 rounded-full ${
                  evt.kind === "llm" ? "bg-sky-400" :
                  evt.kind === "tool" ? "bg-amber-400" :
                  evt.kind === "message" ? "bg-emerald-400" :
                  "bg-purple-400"
                }`} />
                <span className="text-[9px] text-muted truncate">{evt.label}</span>
              </div>
            ))}
            {events.length === 0 && (
              <div className="text-[9px] text-muted/50">等待事件...</div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
```

### 1.8 集成到 MessagePanel

修改 [MessagePanel.tsx](file:///d:/Agentia/Agentia/web/src/components/MessagePanel.tsx)，在 CollaborationProgressCard 旁边加入 AgentGraph：

```typescript
// 在 MessagePanel.tsx 顶部的 import 区域新增：
import { AgentGraph } from "./AgentGraph";

// 在 CollaborationProgressCard 下方新增 AgentGraph 渲染：
{currentTasks.length > 0 && (
  <>
    <CollaborationProgressCard tasks={currentTasks} />
    <AgentGraph />
  </>
)}
```

---

## Phase 2：后端动画事件体系增强

### 目标
在现有 WS 事件基础上，新增专门的动画事件类型，使前后端动画数据流更加解耦和高效。

### 2.1 新增 WS 事件类型

在 [types.ts](file:///d:/Agentia/Agentia/web/src/types.ts) 的 `ServerEvent` 联合类型中新增：

```typescript
// 新增动画事件类型
| {
    type: "anim_agent_created";
    ts: number;
    conversation_id: string;
    agent: {
      id: string;
      role: string;
      parentId: string | null;
      domain?: string;
      agentName?: string;
    };
  }
| {
    type: "anim_agent_status";
    ts: number;
    conversation_id: string;
    agentId: string;
    status: "IDLE" | "BUSY" | "WAKING";
  }
| {
    type: "anim_beam";
    ts: number;
    conversation_id: string;
    beam: {
      id: string;
      fromId: string;
      toId: string;
      kind: "create" | "message";
      label?: string;
    };
  }
| {
    type: "anim_event";
    ts: number;
    conversation_id: string;
    event: {
      id: string;
      kind: "agent" | "message" | "llm" | "tool";
      label: string;
    };
  }
```

### 2.2 后端新增 `AnimationEventBus`

新建 [server/services/animation_bus.py](file:///d:/Agentia/Agentia/server/services/animation_bus.py)：

```python
"""AnimationEventBus — 动画事件总线（移植自 swarm-ide ui-bus.ts）。

与现有 WS hub 协同工作：WS 处理业务事件（message/task），
AnimationEventBus 处理可视化事件（agent created/status/beam）。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class AnimEvent:
    id: str
    at: float
    type: str
    data: dict[str, Any]


class AnimationEventBus:
    def __init__(self, max_buffer: int = 2000):
        self._next_id = 0
        self._buffer: list[AnimEvent] = []
        self._listeners: list[Callable] = []
        self._max_buffer = max_buffer

    def _next_event_id(self) -> str:
        self._next_id += 1
        return f"anim_evt_{self._next_id}"

    def emit(self, event_type: str, data: dict[str, Any]):
        evt = AnimEvent(
            id=self._next_event_id(),
            at=time.time() * 1000,
            type=event_type,
            data=data,
        )
        self._buffer.append(evt)
        if len(self._buffer) > self._max_buffer:
            self._buffer = self._buffer[-self._max_buffer:]
        for listener in self._listeners:
            try:
                listener(evt)
            except Exception:
                pass

    def subscribe(self, listener: Callable):
        self._listeners.append(listener)

    def get_since(self, after_id: str) -> list[AnimEvent]:
        found = False
        result = []
        for e in self._buffer:
            if found:
                result.append(e)
            elif e.id == after_id:
                found = True
        return result

    def agent_created(
        self,
        *,
        conversation_id: str,
        agent_id: str,
        role: str,
        parent_id: Optional[str] = None,
        domain: Optional[str] = None,
        agent_name: Optional[str] = None,
    ):
        self.emit("anim_agent_created", {
            "conversation_id": conversation_id,
            "agent": {
                "id": agent_id,
                "role": role,
                "parentId": parent_id,
                "domain": domain,
                "agentName": agent_name,
            },
        })

    def agent_status(
        self,
        *,
        conversation_id: str,
        agent_id: str,
        status: str,  # IDLE | BUSY | WAKING
    ):
        self.emit("anim_agent_status", {
            "conversation_id": conversation_id,
            "agentId": agent_id,
            "status": status,
        })

    def beam(
        self,
        *,
        conversation_id: str,
        from_id: str,
        to_id: str,
        kind: str = "message",
        label: Optional[str] = None,
    ):
        self.emit("anim_beam", {
            "conversation_id": conversation_id,
            "beam": {
                "id": f"beam_{uuid.uuid4().hex[:8]}",
                "fromId": from_id,
                "toId": to_id,
                "kind": kind,
                "label": label,
            },
        })

    def viz_event(
        self,
        *,
        conversation_id: str,
        kind: str,
        label: str,
    ):
        self.emit("anim_event", {
            "conversation_id": conversation_id,
            "event": {
                "id": f"viz_{uuid.uuid4().hex[:8]}",
                "kind": kind,
                "label": label,
            },
        })


animation_bus = AnimationEventBus()
```

### 2.3 在 Orchestrator 和 DAG 执行中埋点

修改 [orchestrator.py](file:///d:/Agentia/Agentia/server/orchestrator.py) 中的 `handle_orchestrator_mention`：

```python
from services.animation_bus import animation_bus

# 在创建子任务时，发送动画事件
for st, agent_name, agent_id, input_summary, deps in subtask_records:
    animation_bus.agent_created(
        conversation_id=conversation_id,
        agent_id=agent_id,
        role=st.domain or "agent",
        parent_id=ORCHESTRATOR_AGENT_ID,
        domain=st.domain,
        agent_name=agent_name,
    )
    animation_bus.beam(
        conversation_id=conversation_id,
        from_id=ORCHESTRATOR_AGENT_ID,
        to_id=agent_id,
        kind="create",
        label=f"分派: {st.title[:20]}",
    )
    animation_bus.viz_event(
        conversation_id=conversation_id,
        kind="agent",
        label=f"创建: {agent_name}",
    )
```

在 [dag_engine.py](file:///d:/Agentia/Agentia/server/dag_engine.py) 的 `DAGExecutor._run_node` 中：

```python
# node 开始执行
animation_bus.agent_status(
    conversation_id=self.conversation_id,
    agent_id=node.assigned_agent_id,
    status="BUSY",
)

# node 执行完成
animation_bus.agent_status(
    conversation_id=self.conversation_id,
    agent_id=node.assigned_agent_id,
    status="IDLE",
)
```

### 2.4 在 WS Hub 中转发动画事件

修改 [ws.py](file:///d:/Agentia/Agentia/server/ws.py)，让 `WSHub` 能够消费 AnimationEventBus：

```python
# 在 WSHub 或 main.py 启动时注册：
from services.animation_bus import animation_bus

def _forward_anim_event(evt):
    # 构造与 ServerEvent 兼容的字典
    ws_event = {
        "type": evt.type,
        "ts": int(evt.at),
        **evt.data,
    }
    asyncio.create_task(hub.broadcast_conversation(
        evt.data.get("conversation_id", ""),
        ws_event,
    ))

animation_bus.subscribe(_forward_anim_event)
```

---

## Phase 3：Agent 自组织能力（长期规划）

### 目标
给 Agent 添加 swarm-ide 风格的 IM 通信工具，使 Agent 能够自主创建子 Agent、发消息、建群，从中心化调度进化为自组织集群。

### 3.1 需要新增的工具

在 [server/services/tool_registry.py](file:///d:/Agentia/Agentia/server/services/tool_registry.py) 中注册新工具：

```python
tools = [
    {
        "name": "send_message_to_agent",
        "description": "Send a direct message to another Agent",
        "parameters": {
            "to_agent_id": "string (required) — target agent ID",
            "content": "string (required) — message content",
        },
    },
    {
        "name": "create_sub_agent",
        "description": "Create a new child Agent with specified role and guidance",
        "parameters": {
            "role": "string (required) — role description",
            "guidance": "string (required) — task guidance for the new agent",
        },
    },
    {
        "name": "list_available_agents",
        "description": "List all available agents in the workspace",
        "parameters": {},
    },
    {
        "name": "get_agent_status",
        "description": "Get the current status of a specific agent",
        "parameters": {
            "agent_id": "string (required) — agent ID",
        },
    },
]
```

### 3.2 工具实现要点

- `send_message_to_agent`：通过 `animation_bus.beam()` + `hub.broadcast_conversation()` 发送消息，唤醒目标 Agent
- `create_sub_agent`：动态创建 Agent 记录 + 发送 `anim_agent_created` 事件
- `list_available_agents`：从数据库查询当前会话中的 Agent 列表
- `get_agent_status`：从 `animation_bus` 或 DAG 状态中查询

### 3.3 Spells 协议迁移

将 swarm-ide 的 `spells/` 目录下的三种编排模式（map-reduce、router-experts、tree-executor）翻译为 Agentia 的 Agent 系统提示词扩展：

- **map-reduce**：已有的 Orchestrator 分解 + DAG 并行执行 + 结果聚合，天然支持
- **router-experts**：扩展 `_pick_agent_for_domain` 的匹配逻辑，支持 LLM 驱动的路由
- **tree-executor**：利用 `parent_task_id` 递归创建父子任务树，DAG 自动处理依赖

---

## 第四部分：实施路线图

### Week 1-2：Phase 1 前端动画层

| 天 | 任务 | 产出 |
|----|------|------|
| D1-2 | 安装 framer-motion，创建 `AgentGraph/` 目录结构 | 目录 + types.ts |
| D3-4 | 实现 `useAgentGraph` Hook（消费现有 WS 数据） | Hook 完成 |
| D5-6 | 实现 `computeTreeLayout` 布局算法 | 布局算法完成 |
| D7-8 | 实现 `AgentNode` 组件（Spring 入场 + BUSY 光环） | 节点组件 |
| D9-10 | 实现 `AgentBeam` 组件（光点飞行 + 渐变消失） | 连线组件 |
| D11-12 | 实现 `AgentGraph` SVG 画布（缩放/平移/拖拽） | 画布交互 |
| D13-14 | 集成到 `MessagePanel`，端到端测试 | 可演示版本 |

### Week 3：Phase 2 后端事件增强

| 天 | 任务 | 产出 |
|----|------|------|
| D1-2 | 创建 `animation_bus.py` | 动画事件总线 |
| D3-4 | 在 orchestrator.py / dag_engine.py 中埋点 | 后端埋点完成 |
| D5-6 | WS 转发动画事件 + 前端 reducer 处理 | 事件管道打通 |
| D7 | 端到端集成测试 | 测试通过 |

### Week 4-6：Phase 3 Agent 自组织

| 周 | 任务 | 产出 |
|----|------|------|
| W4 | 实现 4 个 Agent 间通信工具 + 工具注册 | 工具就绪 |
| W5 | ReAct 循环集成新工具 + 端到端测试 | 自主通信可行 |
| W6 | Spells 协议 prompt 工程 + 性能调优 | 完整 Swarm 模式 |

---

## 第五部分：风险与注意事项

### 5.1 性能风险

| 风险 | 缓解措施 |
|------|----------|
| SVG 节点过多导致渲染卡顿 | 限制同时显示节点数 ≤ 50，折叠子树，Canvas 模式降级方案 |
| Framer Motion 动画在低端设备上掉帧 | `useReducedMotion` 检测，提供静态模式切换 |
| 大量 WS 事件导致前端状态更新过频 | `useMemo` + `requestAnimationFrame` 节流，事件批量合并 |

### 5.2 架构风险

| 风险 | 缓解措施 |
|------|----------|
| Phase 3 Agent 自组织可能导致无限递归创建 | 限制创建深度（max 5 层），父 Agent 可手动终止子 Agent |
| 动画事件与业务事件耦合过紧 | AnimationEventBus 独立于 WS hub，仅单向消费，不影响业务逻辑 |
| 数据库并发写入冲突 | 复用现有 SQLAlchemy async session + 状态机校验 |

### 5.3 兼容性

- 所有新增前端组件通过 feature flag（环境变量 `VITE_ENABLE_AGENT_GRAPH`）控制开关
- 后端 AnimationEventBus 为可选模块，未注册时自动降级为空操作
- 不影响现有消息流、任务调度、DAG 执行的任何逻辑

---

> 本文档基于对 swarm-ide 和 Agentia 两个项目的完整代码审查生成。
> 所有文件路径、函数名、数据结构均与实际代码一一对应。
