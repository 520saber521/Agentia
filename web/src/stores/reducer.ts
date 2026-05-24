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

  const maxOverlap = Math.min(currentText.length, delta.length);
  for (let size = maxOverlap; size > 0; size -= 1) {
    if (currentText.endsWith(delta.slice(0, size))) {
      return currentText + delta.slice(size);
    }
  }

  return currentText + delta;
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
      const tasks = { ...state.tasks, [evt.task.id]: evt.task };
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
        const nextStreaming = removeStreaming(
          state.streamingMessageIds,
          evt.message_id,
        );
        return {
          next: {
            ...state,
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
  };
}
