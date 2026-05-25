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
  fetchAgents,
  fetchConversations,
  fetchMessages,
  updateConversation,
  updateAgent,
  fetchContextStats,
  type CreateConversationInput,
  type SaveAgentInput,
} from "../api/client";
import type { Agent, ConnectionStatus, Conversation, Message } from "../types";
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

  init: () => void;
  refreshConversations: () => Promise<void>;
  selectConversation: (id: string) => Promise<void>;
  createAndSelect: (input: CreateConversationInput) => Promise<Conversation>;
  createAgentContact: (input: SaveAgentInput) => Promise<Agent>;
  updateAgentContact: (agentId: string, input: Partial<SaveAgentInput>) => Promise<Agent>;
  deleteAgentContact: (agentId: string) => Promise<void>;
  startAgentChat: (agentId: string) => Promise<Conversation>;
  updateConversationMeta: (
    conversationId: string,
    input: { title?: string; pinned?: boolean; archived?: boolean },
  ) => Promise<Conversation>;
  sendText: (text: string, mentions?: string[]) => void;
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
  contextStats: null,

  init() {
    ws.onStatus((s) => set({ status: s }));
    ws.onEvent((evt) => {
      const cur = sliceFromState(get());
      const { next, effects } = reduceEvent(cur, evt);
      if (next !== cur) set(next);
      if (evt.type === "error") console.error("[server error]", evt);
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
      const convs = await fetchConversations({ includeArchived: true });
      set({ conversations: convs });
      const current = get().currentConvId;
      if (!current && convs.length > 0) {
        const firstActive = convs.find((c) => !c.archived) ?? convs[0];
        await get().selectConversation(firstActive.id);
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

  async startAgentChat(agentId) {
    const agent = get().agents.find((a) => a.id === agentId);
    return get().createAndSelect({
      title: agent?.name ? `Chat with ${agent.name}` : "Agent Chat",
      type: "single",
      agent_ids: [agentId],
    });
  },

  async updateConversationMeta(conversationId, input) {
    const conv = await updateConversation(conversationId, input);
    set((s) => ({
      conversations: s.conversations.map((x) => (x.id === conv.id ? conv : x)),
      currentConvId:
        conv.archived && s.currentConvId === conv.id ? null : s.currentConvId,
      messages: conv.archived && s.currentConvId === conv.id ? [] : s.messages,
    }));
    return conv;
  },

  async selectConversation(id) {
    set({
      currentConvId: id,
      messages: [],
      streamingMessageIds: [],
      agentTyping: false,
      contextStats: null,
    });
    try {
      const [msgs, stats] = await Promise.all([
        fetchMessages(id, 200),
        fetchContextStats(id).catch(() => null),
      ]);
      set({
        messages: msgs,
        contextStats: stats
          ? { total: stats.total_messages, pinned: stats.pinned_messages }
          : null,
      });
    } catch (err) {
      console.error("fetchMessages failed", err);
    }
    ws.send({ type: "join", conversation_id: id, limit: 200 });
  },

  sendText(text, mentions) {
    const cid = get().currentConvId;
    if (!cid) return;
    ws.send({
      type: "send_message",
      conversation_id: cid,
      content: { type: "text", text },
      ...(mentions && mentions.length > 0 ? { mentions } : {}),
    });
  },

  cancelAll() {
    const ids = get().streamingMessageIds;
    if (ids.length === 0) return;
    // 每个 message_id 各发一条 cancel；后端按 message_id 索引 in_flight。
    for (const mid of ids) {
      ws.send({ type: "cancel", message_id: mid });
    }
  },

  cancelMessage(messageId) {
    ws.send({ type: "cancel", message_id: messageId });
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
    contextStats: s.contextStats ?? null,
  };
}
