/**
 * 整个 SPA 的状态机（Zustand）。
 *
 * 为什么把会话列表 + 当前消息 + 连接状态放在同一个 store？
 * - Day4 阶段还没有"多会话同时活跃"的需求，单 store 写起来更直接。
 * - 后续 Day5 引入 task / artifact 后可以拆 useTaskStore / useArtifactStore。
 */

import { create } from "zustand";

import {
  createAgent,
  createConversation,
  deleteAgent,
  deleteConversation,
  fetchAgents,
  fetchConversations,
  fetchMessages,
  updateAgent,
  type CreateConversationInput,
  type SaveAgentInput,
} from "../api/client";
import type { Agent, ConnectionStatus, Conversation, EditContext, Message } from "../types";
import { WSClient } from "../ws/client";
import { reduceEvent, type ChatSlice } from "./reducer";

export interface ChatState extends ChatSlice {
  status: ConnectionStatus;
  serverInfo: string | null;
  conversations: Conversation[];
  currentConvId: string | null;
  messages: Message[];
  /** W2 起：可同时多条流式（群聊 fan-out）。空数组 = 无流式。 */
  streamingMessageIds: string[];
  agentTyping: boolean;
  agents: Agent[];
  editContext: EditContext | null;
  sendError: string | null;
  errorToast: string | null;

  init: () => void;
  refreshConversations: () => Promise<void>;
  selectConversation: (id: string) => Promise<void>;
  createAndSelect: (input: CreateConversationInput) => Promise<Conversation>;
  createAgentContact: (input: SaveAgentInput) => Promise<Agent>;
  updateAgentContact: (agentId: string, input: Partial<SaveAgentInput>) => Promise<Agent>;
  deleteAgentContact: (agentId: string) => Promise<void>;
  removeConversation: (conversationId: string) => Promise<void>;
  startAgentChat: (agentId: string) => Promise<Conversation>;
  sendText: (text: string, mentions?: string[]) => void;
  setEditContext: (ctx: EditContext | null) => void;
  clearEditContext: () => void;
  clearSendError: () => void;
  clearErrorToast: () => void;
  /** 取消单条流式消息。 */
  cancelMessage: (messageId: string) => void;
  /** 取消当前所有流式（群聊场景下一次取消所有正在流的 agent）。 */
  cancelAll: () => void;
}

const ws = new WSClient();

export const useChatStore = create<ChatState>()((set, get) => ({
  status: "disconnected",
  serverInfo: null,
  conversations: [],
  currentConvId: null,
  messages: [],
  streamingMessageIds: [],
  agentTyping: false,
  agents: [],
  tasks: {},
  editContext: null,
  sendError: null,
  errorToast: null,

  init() {
    ws.onStatus((s) => set({ status: s }));
    ws.onEvent((evt) => {
      const cur = sliceFromState(get());
      const { next, effects } = reduceEvent(cur, evt);
      if (next !== cur) set(next);
      if (evt.type === "error") {
        console.error("[server error]", evt);
        // 非流式错误（无 message_id）→ Toast 提示
        if (!evt.message_id) {
          set({ errorToast: `[${evt.code}] ${evt.message}` });
        }
      }
      for (const ef of effects) {
        if (ef === "refresh_conversations") void get().refreshConversations();
      }
    });
    ws.connect();
    void get().refreshConversations();
    void fetchAgents().then((agents) => set({ agents })).catch((err) => {
      console.error("fetchAgents failed", err);
    });
  },

  async refreshConversations() {
    try {
      const convs = await fetchConversations();
      set({ conversations: convs });
      const current = get().currentConvId;
      if (!current && convs.length > 0) {
        await get().selectConversation(convs[0].id);
      }
    } catch (err) {
      console.error("refreshConversations failed", err);
    }
  },

  async createAndSelect(input) {
    const conv = await createConversation(input);
    // 先把新会话塞进列表头，避免等下一次刷新出现"空白期"
    set((s) => ({
      conversations: [conv, ...s.conversations.filter((x) => x.id !== conv.id)],
    }));
    await get().selectConversation(conv.id);
    return conv;
  },

  async createAgentContact(input) {
    const agent = await createAgent(input);
    set((s) => ({
      agents: [agent, ...s.agents.filter((x) => x.id !== agent.id)],
    }));
    return agent;
  },

  async updateAgentContact(agentId, input) {
    const agent = await updateAgent(agentId, input);
    set((s) => ({
      agents: s.agents.map((x) => (x.id === agent.id ? agent : x)),
    }));
    return agent;
  },

  async deleteAgentContact(agentId) {
    await deleteAgent(agentId);
    set((s) => ({
      agents: s.agents.filter((x) => x.id !== agentId),
    }));
  },

  async removeConversation(conversationId) {
    try {
      await deleteConversation(conversationId);
    } catch (err) {
      console.warn("deleteConversation failed", err);
    }
    set((s) => {
      const next = {
        conversations: s.conversations.filter((c) => c.id !== conversationId),
      };
      if (s.currentConvId === conversationId) {
        const remaining = next.conversations;
        Object.assign(next, {
          currentConvId: remaining.length > 0 ? remaining[0].id : null,
          messages: [],
          streamingMessageIds: [],
          agentTyping: false,
        });
      }
      return next;
    });
  },

  async startAgentChat(agentId) {
    const agent = get().agents.find((a) => a.id === agentId);
    return get().createAndSelect({
      title: agent?.name ? `Chat with ${agent.name}` : "Agent Chat",
      type: "single",
      agent_ids: [agentId],
    });
  },

  async selectConversation(id) {
    set({
      currentConvId: id,
      messages: [],
      streamingMessageIds: [],
      agentTyping: false,
    });
    try {
      const msgs = await fetchMessages(id, 200);
      set({ messages: msgs });
    } catch (err) {
      console.error("fetchMessages failed", err);
    }
    ws.send({ type: "join", conversation_id: id, limit: 200 });
  },

  sendText(text, mentions) {
    const cid = get().currentConvId;
    if (!cid) return;
    const editCtx = get().editContext;

    // 乐观插入用户消息
    const optimisticId = `pending_${Date.now()}`;
    const optimisticMsg: Message = {
      id: optimisticId,
      conversation_id: cid,
      sender_id: "user",
      sender_type: "user",
      content_type: "text",
      content: { type: "text", text },
      reply_to: null,
      mentions: mentions ?? [],
      pinned: false,
      artifact_id: null,
      agenthub_msg_id: null,
      created_at: Date.now(),
    };
    set((s) => ({
      messages: [...s.messages, optimisticMsg],
    }));

    const ok = ws.send({
      type: "send_message",
      conversation_id: cid,
      content: { type: "text", text },
      ...(mentions && mentions.length > 0 ? { mentions } : {}),
      ...(editCtx ? { edit_context: editCtx } : {}),
    });
    if (!ok) {
      // 发送失败：移除乐观消息，设置错误
      set((s) => ({
        messages: s.messages.filter((m) => m.id !== optimisticId),
        sendError: "消息发送失败，请检查连接后重试",
      }));
      return;
    }
    if (editCtx) set({ editContext: null });
  },

  setEditContext(ctx) {
    set({ editContext: ctx });
  },

  clearEditContext() {
    set({ editContext: null });
  },

  clearSendError() {
    set({ sendError: null });
  },

  clearErrorToast() {
    set({ errorToast: null });
  },

  cancelMessage(messageId) {
    const ids = get().streamingMessageIds;
    if (!ids.includes(messageId)) return;
    ws.send({ type: "cancel", message_id: messageId });
    set((s) => ({
      streamingMessageIds: s.streamingMessageIds.filter((id) => id !== messageId),
    }));
  },

  cancelAll() {
    const ids = get().streamingMessageIds;
    if (ids.length === 0) return;
    // 每个 message_id 各发一条 cancel；后端按 message_id 索引 in_flight。
    for (const mid of ids) {
      ws.send({ type: "cancel", message_id: mid });
    }
  },
}));

function sliceFromState(s: ChatState): ChatSlice {
  return {
    serverInfo: s.serverInfo,
    currentConvId: s.currentConvId,
    conversations: s.conversations,
    messages: s.messages,
    streamingMessageIds: s.streamingMessageIds,
    agentTyping: s.agentTyping,
    agents: s.agents,
    tasks: s.tasks ?? {},
  };
}
