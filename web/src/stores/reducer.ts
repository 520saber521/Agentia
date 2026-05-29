/**
 * 纯 reducer：把 `ServerEvent` + 当前 store 状态切片 ⇒ 新状态切片（或 ``null`` 表示不变）。
 *
 * 把它抽出来主要是为了：
 *   1. 单元可测（Vitest 里不需要起 WS、不需要 Zustand）；
 *   2. 之后多 store 拆分时（task / artifact）可以复用这套消费契约；
 *   3. 强制约束"只有 reducer 能写消息列表 / 流式状态"，避免散落的 set 调用。
 *
 * `handleEvent` 中的副作用（`refreshConversations` / `console.error`）通过返回的
 * `sideEffects` 字段告知调用方，由 store 那一层实际执行 —— reducer 自身保持纯。
 */

import type {
  Agent,
  AgentGraphBeam,
  AgentGraphEvent,
  AgentGraphNode,
  AgentGraphStatus,
  Conversation,
  Message,
  MessageContent,
  ServerEvent,
  Task,
} from "../types";

/** Reducer 关心的状态切片：仅包含被事件影响的那部分字段。
 *
 * W2 F-W2-1 起：``streamingMessageIds`` 从单值升级为数组，
 * 因为群聊 fan-out 时多个 agent 可能同时流；任意一个 done/cancelled/error
 * 只从该数组中移除其 ``message_id``，其他兄弟仍在流。
 */
export interface ChatSlice {
  serverInfo: string | null;
  currentConvId: string | null;
  conversations: Conversation[];
  messages: Message[];
  streamingMessageIds: string[];
  agentTyping: boolean;
  agents: Agent[];
  /** W3 F-W3-3: task_id → Task map for the current conversation. */
  tasks: Record<string, Task>;
  /** Context stats for current conversation. */
  contextStats: {
    total: number;
    pinned: number;
    historyCount?: number;
    estimatedTokens?: number;
    strategy?: string;
  } | null;
  agentGraphNodes: Record<string, AgentGraphNode>;
  agentGraphBeams: AgentGraphBeam[];
  agentGraphEvents: AgentGraphEvent[];
  agentGraphStatuses: Record<string, AgentGraphStatus>;
}

function addStreaming(arr: string[], id: string): string[] {
  if (arr.includes(id)) return arr;
  return [...arr, id];
}

function removeStreaming(arr: string[], id: string): string[] {
  const idx = arr.indexOf(id);
  if (idx < 0) return arr;
  const next = arr.slice();
  next.splice(idx, 1);
  return next;
}

export type SideEffect = "refresh_conversations";

export interface ReduceResult {
  next: ChatSlice;
  effects: SideEffect[];
}

function getText(content: MessageContent | undefined | null): string {
  if (
    content &&
    typeof content === "object" &&
    "text" in content &&
    typeof (content as { text?: unknown }).text === "string"
  ) {
    return (content as { text: string }).text;
  }
  return "";
}

function appendStreamDelta(currentText: string, delta: string): string {
  if (!delta) return currentText;
  if (!currentText) return delta;
  if (currentText.endsWith(delta)) return currentText;

  // Only check for overlap in the trailing 32 chars — O(1) instead of O(n)
  const suffixLen = Math.min(32, currentText.length);
  const suffix = currentText.slice(-suffixLen);
  const maxOverlap = Math.min(suffixLen, delta.length);
  for (let size = maxOverlap; size > 0; size -= 1) {
    if (suffix.endsWith(delta.slice(0, size))) {
      return currentText + delta.slice(size);
    }
  }

  return currentText + delta;
}

function visibleErrorText(code: string, message: string): string {
  if (code === "output_truncated") {
    return "\n\n---\n[提示] 输出达到模型长度上限，当前内容可能不完整。请发送“继续生成”，或提高该 Agent 的 max_tokens 后重新生成。";
  }
  return `\n\n---\n[提示] 生成中断：${message || code}`;
}

/** 主入口。永远返回新的 slice 对象（即使内容相同），便于调用方一律走相等性判断。 */
export function reduceEvent(state: ChatSlice, evt: ServerEvent): ReduceResult {
  const effects: SideEffect[] = [];

  switch (evt.type) {
    case "hello":
      return { next: { ...state, serverInfo: evt.server }, effects };

    case "history": {
      if (evt.conversation_id !== state.currentConvId) return { next: state, effects };
      return { next: { ...state, messages: evt.messages }, effects };
    }

    case "message_created": {
      const m = evt.message;
      if (m.conversation_id !== state.currentConvId) {
        effects.push("refresh_conversations");
        return { next: state, effects };
      }
      if (state.messages.some((x) => x.id === m.id)) {
        return { next: state, effects };
      }
      if (m.sender_type === "user") {
        const tempIdx = state.messages.findIndex(
          (x) => x.id.startsWith("temp-") && x.sender_type === "user",
        );
        if (tempIdx >= 0) {
          const messages = state.messages.slice();
          messages[tempIdx] = m;
          return { next: { ...state, messages }, effects };
        }
      }
      const messages = [...state.messages, m];
      const next: ChatSlice =
        m.sender_type === "agent"
          ? {
              ...state,
              messages,
              streamingMessageIds: addStreaming(state.streamingMessageIds, m.id),
              agentTyping: false,
            }
          : { ...state, messages };
      return { next, effects };
    }

    case "agents": {
      return { next: { ...state, agents: evt.agents }, effects };
    }

    case "task_update": {
      if (evt.conversation_id !== state.currentConvId) return { next: state, effects };
      const existing = state.tasks[evt.task.id];
      const merged = existing?.depends_on != null && evt.task.depends_on == null
        ? { ...evt.task, depends_on: existing.depends_on }
        : evt.task;
      const tasks = { ...state.tasks, [evt.task.id]: merged };
      return {
        next: { ...state, tasks },
        effects: evt.action === "completed" ? ["refresh_conversations"] : effects,
      };
    }

    case "agent_typing": {
      if (evt.conversation_id !== state.currentConvId) return { next: state, effects };
      return { next: { ...state, agentTyping: true }, effects };
    }

    case "stream_chunk": {
      if (evt.conversation_id !== state.currentConvId) return { next: state, effects };
      const idx = state.messages.findIndex((m) => m.id === evt.message_id);
      if (idx < 0) return { next: state, effects };
      const messages = state.messages.slice();
      const prev = messages[idx];
      messages[idx] = {
        ...prev,
        content: {
          type: "text",
          text: appendStreamDelta(getText(prev.content), evt.delta),
        },
      };
      return { next: { ...state, messages }, effects };
    }

    case "message_done":
    case "message_cancelled": {
      const idx = state.messages.findIndex((m) => m.id === evt.message_id);
      let messages = state.messages;
      if (idx >= 0) {
        messages = state.messages.slice();
        messages[idx] = { ...messages[idx], content: evt.final_content };
      }
      const nextStreaming = removeStreaming(
        state.streamingMessageIds,
        evt.message_id,
      );
      effects.push("refresh_conversations");
      return {
        next: {
          ...state,
          messages,
          streamingMessageIds: nextStreaming,
          // 还有兄弟在流时不清 typing 标志；全部完成才清
          agentTyping: nextStreaming.length > 0 ? state.agentTyping : false,
        },
        effects,
      };
    }

    case "error": {
      // 服务端报错：若 message_id 命中正在流的列表，仅从中移除该条。
      if (
        typeof evt.message_id === "string" &&
        state.streamingMessageIds.includes(evt.message_id)
      ) {
        const idx = state.messages.findIndex((m) => m.id === evt.message_id);
        let messages = state.messages;
        if (idx >= 0) {
          const current = state.messages[idx];
          const text = getText(current.content);
          const note = visibleErrorText(evt.code, evt.message);
          messages = state.messages.slice();
          messages[idx] = {
            ...current,
            content: {
              type: "text",
              text: text.includes(note) ? text : `${text}${note}`,
            },
          };
        }
        const nextStreaming = removeStreaming(
          state.streamingMessageIds,
          evt.message_id,
        );
        return {
          next: {
            ...state,
            messages,
            streamingMessageIds: nextStreaming,
            agentTyping: nextStreaming.length > 0 ? state.agentTyping : false,
          },
          effects,
        };
      }
      return { next: state, effects };
    }

    case "artifact_ready": {
      if (
        evt.conversation_id !== state.currentConvId ||
        !evt.message_id
      ) {
        return { next: state, effects };
      }
      const idx = state.messages.findIndex((m) => m.id === evt.message_id);
      if (idx < 0) return { next: state, effects };
      const messages = state.messages.slice();
      const current = messages[idx];
      const content = current.content.type === "preview"
        ? {
            ...current.content,
            artifact_id: evt.artifact.id,
            title: current.content.title || evt.artifact.title,
            mimeType: current.content.mimeType || evt.artifact.mime_type,
            fileSize: current.content.fileSize || evt.artifact.file_size,
            url: current.content.url || evt.artifact.url,
            previewUrl: current.content.previewUrl || evt.artifact.preview_url,
            version: current.content.version || evt.artifact.version,
          }
        : current.content;
      messages[idx] = { ...current, artifact_id: evt.artifact.id, content };
      return { next: { ...state, messages }, effects };
    }

    case "message_pinned":
    case "message_unpinned": {
      if (evt.conversation_id !== state.currentConvId) return { next: state, effects };
      const pinned = evt.type === "message_pinned";
      const messages = state.messages.map((m) =>
        m.id === evt.message.id ? { ...m, pinned } : m
      );
      return { next: { ...state, messages }, effects };
    }

    case "context_info": {
      if (evt.conversation_id !== state.currentConvId) return { next: state, effects };
      return {
        next: {
          ...state,
          contextStats: {
            total: evt.total_messages,
            pinned: evt.pinned_messages,
            historyCount: evt.history_count,
            estimatedTokens: evt.estimated_tokens,
            strategy: evt.strategy,
          },
        },
        effects,
      };
    }

    case "tool_call": {
      if (evt.conversation_id !== state.currentConvId) return { next: state, effects };
      const idx = state.messages.findIndex((m) => m.id === evt.message_id);
      if (idx < 0) return { next: state, effects };
      const messages = state.messages.slice();
      const current = messages[idx];
      const nextCall = {
        toolName: evt.tool_name,
        status: evt.status,
        resultSummary: evt.result_summary,
      };
      const existing = current.toolCalls ?? [];
      const foundIdx = existing.findIndex((call) => call.toolName === evt.tool_name);
      const toolCalls = existing.slice();
      if (foundIdx >= 0) {
        toolCalls[foundIdx] = { ...toolCalls[foundIdx], ...nextCall };
      } else {
        toolCalls.push(nextCall);
      }
      messages[idx] = { ...current, toolCalls };
      return { next: { ...state, messages }, effects };
    }

    case "anim_agent_created": {
      if (evt.conversation_id !== state.currentConvId) return { next: state, effects };
      const existing = state.agentGraphNodes[evt.agent.id];
      const status = state.agentGraphStatuses[evt.agent.id] ?? existing?.status ?? "IDLE";
      const node: AgentGraphNode = {
        id: evt.agent.id,
        role: evt.agent.role,
        parentId: evt.agent.parentId,
        status,
        domain: evt.agent.domain || undefined,
        agentName: evt.agent.agentName || undefined,
      };
      return {
        next: {
          ...state,
          agentGraphNodes: { ...state.agentGraphNodes, [node.id]: node },
        },
        effects,
      };
    }

    case "anim_agent_status": {
      if (evt.conversation_id !== state.currentConvId) return { next: state, effects };
      const existing = state.agentGraphNodes[evt.agentId];
      const nodes = existing
        ? {
            ...state.agentGraphNodes,
            [evt.agentId]: { ...existing, status: evt.status },
          }
        : state.agentGraphNodes;
      return {
        next: {
          ...state,
          agentGraphStatuses: { ...state.agentGraphStatuses, [evt.agentId]: evt.status },
          agentGraphNodes: nodes,
        },
        effects,
      };
    }

    case "anim_beam": {
      if (evt.conversation_id !== state.currentConvId) return { next: state, effects };
      const beam: AgentGraphBeam = {
        id: evt.beam.id,
        fromId: evt.beam.fromId,
        toId: evt.beam.toId,
        kind: evt.beam.kind,
        label: evt.beam.label || undefined,
        createdAt: evt.ts,
      };
      return {
        next: {
          ...state,
          agentGraphBeams: [...state.agentGraphBeams.filter((b) => b.id !== beam.id), beam].slice(-100),
        },
        effects,
      };
    }

    case "anim_event": {
      if (evt.conversation_id !== state.currentConvId) return { next: state, effects };
      const item: AgentGraphEvent = {
        id: evt.event.id,
        kind: evt.event.kind,
        label: evt.event.label,
        at: evt.ts,
      };
      return {
        next: {
          ...state,
          agentGraphEvents: [item, ...state.agentGraphEvents.filter((e) => e.id !== item.id)].slice(0, 80),
        },
        effects,
      };
    }

    case "workspace_file_changed": {
      // File changed in workspace — no state mutation needed,
      // the WorkspacePanel listens for new messages to auto-refresh.
      return { next: state, effects };
    }

    default:
      // pong / echo / usage 等不更新 UI 状态。
      return { next: state, effects };
  }
}

/** 初始状态工厂，主要给测试用。 */
export function emptySlice(): ChatSlice {
  return {
    serverInfo: null,
    currentConvId: null,
    conversations: [],
    messages: [],
    streamingMessageIds: [],
    agentTyping: false,
    agents: [],
    tasks: {},
    contextStats: null,
    agentGraphNodes: {},
    agentGraphBeams: [],
    agentGraphEvents: [],
    agentGraphStatuses: {},
  };
}
