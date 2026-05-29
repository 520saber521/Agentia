/**
 * 整个 SPA 的状态机（Zustand）。
 *
 * W3 多标签页重构：
 * - TabState 缓存每个打开会话的 messages / streaming / tasks / graph 状态
 * - 切换标签页时保存/恢复，不再丢失
 * - WS 事件同时写入活跃标签（flat fields）和对应 tabStates 缓存
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
import type {
  Agent,
  AgentGraphBeam,
  AgentGraphEvent,
  AgentGraphNode,
  AgentGraphStatus,
  ConnectionStatus,
  Conversation,
  Message,
  ServerEvent,
} from "../types";
import { WSClient } from "../ws/client";
import { reduceEvent, type ChatSlice } from "./reducer";

/* ------------------------------------------------------------------ */
/*  Stream-chunk batching: coalesce deltas per animation frame         */
/* ------------------------------------------------------------------ */

let _streamAcc: Record<string, string> = {};
let _rafId: number | null = null;
let _storeGet: (() => ChatState) | null = null;
let _storeSet: ((partial: any) => void) | null = null;

function _flushStreamAcc() {
  const acc = _streamAcc;
  _streamAcc = {};
  _rafId = null;
  const get = _storeGet;
  const set = _storeSet;
  if (!get || !set) return;
  const keys = Object.keys(acc);
  if (keys.length === 0) return;

  const state = get();
  let messages = state.messages;
  let changed = false;

  for (const [mid, delta] of Object.entries(acc)) {
    if (!delta) continue;
    const idx = messages.findIndex((m) => m.id === mid);
    if (idx < 0) continue;
    if (!changed) messages = messages.slice();
    const prev = messages[idx];
    const prevText = (prev.content as any)?.text ?? "";

    let newText: string;
    if (!prevText) {
      newText = delta;
    } else if (prevText.endsWith(delta)) {
      newText = prevText;
    } else {
      const suffixLen = Math.min(32, prevText.length);
      const suffix = prevText.slice(-suffixLen);
      const maxOverlap = Math.min(suffixLen, delta.length);
      let overlap = 0;
      for (let size = maxOverlap; size > 0; size -= 1) {
        if (suffix.endsWith(delta.slice(0, size))) {
          overlap = size;
          break;
        }
      }
      newText = prevText + delta.slice(overlap);
    }

    messages[idx] = { ...prev, content: { type: "text", text: newText } as any };
    changed = true;
  }

  if (changed) set({ messages });
}

/* ------------------------------------------------------------------ */
/*  Per-tab cache                                                      */
/* ------------------------------------------------------------------ */

export interface TabState {
  messages: Message[];
  streamingMessageIds: string[];
  agentTyping: boolean;
  tasks: Record<string, import("../types").Task>;
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

function emptyTabState(): TabState {
  return {
    messages: [],
    streamingMessageIds: [],
    agentTyping: false,
    tasks: {},
    contextStats: null,
    agentGraphNodes: {},
    agentGraphBeams: [],
    agentGraphEvents: [],
    agentGraphStatuses: {},
  };
}

function tabFieldsFromSlice(s: ChatSlice): Partial<TabState> {
  return {
    messages: s.messages,
    streamingMessageIds: s.streamingMessageIds,
    agentTyping: s.agentTyping,
    tasks: s.tasks,
    contextStats: s.contextStats,
    agentGraphNodes: s.agentGraphNodes,
    agentGraphBeams: s.agentGraphBeams,
    agentGraphEvents: s.agentGraphEvents,
    agentGraphStatuses: s.agentGraphStatuses,
  };
}

function flatFieldsFromTab(t: TabState) {
  return {
    messages: t.messages,
    streamingMessageIds: t.streamingMessageIds,
    agentTyping: t.agentTyping,
    tasks: t.tasks,
    contextStats: t.contextStats,
    agentGraphNodes: t.agentGraphNodes,
    agentGraphBeams: t.agentGraphBeams,
    agentGraphEvents: t.agentGraphEvents,
    agentGraphStatuses: t.agentGraphStatuses,
  };
}

/* ------------------------------------------------------------------ */
/*  Store                                                              */
/* ------------------------------------------------------------------ */

export interface ChatState extends ChatSlice {
  status: ConnectionStatus;
  serverInfo: string | null;
  conversations: Conversation[];
  currentConvId: string | null;
  messages: Message[];
  streamingMessageIds: string[];
  agentTyping: boolean;
  agents: Agent[];
  agentGraphNodes: Record<string, AgentGraphNode>;
  agentGraphBeams: AgentGraphBeam[];
  agentGraphEvents: AgentGraphEvent[];
  agentGraphStatuses: Record<string, AgentGraphStatus>;

  /** Multi-tab state */
  activeTabId: string | null;
  openTabIds: string[];
  tabStates: Record<string, TabState>;

  applyServerEvent: (evt: ServerEvent) => void;
  init: () => void;
  refreshConversations: () => Promise<void>;
  selectConversation: (id: string) => Promise<void>;
  openTab: (id: string) => Promise<void>;
  closeTab: (id: string) => void;
  switchTab: (id: string) => void;
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
  agentGraphNodes: {},
  agentGraphBeams: [],
  agentGraphEvents: [],
  agentGraphStatuses: {},

  activeTabId: null,
  openTabIds: [],
  tabStates: {},

  /* ---- event dispatch (tab-aware) ---- */

  applyServerEvent(evt) {
    // Cache get/set for RAF stream-chunk batching
    _storeGet = get as any;
    _storeSet = set as any;

    // Batch stream_chunk events per animation frame to reduce renders
    if (evt.type === "stream_chunk" && (evt as any).message_id) {
      const s = get();
      const cid = _eventConversationId(evt);
      if (cid && cid === s.currentConvId) {
        _streamAcc[(evt as any).message_id] =
          (_streamAcc[(evt as any).message_id] || "") + ((evt as any).delta || "");
        if (_rafId === null) {
          _rafId = requestAnimationFrame(() => _flushStreamAcc());
        }
        return;
      }
    }

    const state = get();
    const cid = _eventConversationId(evt);

    if (cid && cid !== state.currentConvId) {
      // Event for a background tab — update its TabState cache only
      const tab = state.tabStates[cid];
      if (!tab) return;
      const slice: ChatSlice = {
        serverInfo: state.serverInfo,
        currentConvId: cid,
        conversations: state.conversations,
        agents: state.agents,
        ...flatFieldsFromTab(tab),
      };
      const { next } = reduceEvent(slice, evt);
      if (next !== slice) {
        set({
          tabStates: {
            ...state.tabStates,
            [cid]: { ...tab, ...tabFieldsFromSlice(next) },
          },
        });
      }
      return;
    }

    // Event for active tab (or global event)
    const cur = sliceFromState(state);
    const { next, effects } = reduceEvent(cur, evt);
    if (next !== cur) {
      set(next);
    }
    if (evt.type === "error") console.error("[server error]", evt);
    for (const ef of effects) {
      if (ef === "refresh_conversations") void get().refreshConversations();
    }

    // Mirror active-tab changes into tabStates cache
    if (cid) {
      const activeTab = state.tabStates[cid] ?? emptyTabState();
      const updated = sliceFromState(get());
      set({
        tabStates: {
          ...get().tabStates,
          [cid]: { ...activeTab, ...tabFieldsFromSlice(updated) },
        },
      });
    }
  },

  /* ---- lifecycle ---- */

  init() {
    ws.onStatus((s) => set({ status: s }));

    ws.onConnected(() => {
      const { openTabIds } = get();
      for (const cid of openTabIds) {
        ws.send({ type: "join", conversation_id: cid, limit: 200 });
      }
    });

    ws.onEvent((evt) => {
      get().applyServerEvent(evt);
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
        await get().openTab(firstActive.id);
      }
    } catch (err) {
      console.error("refreshConversations failed", err);
    }
  },

  /* ---- tab management ---- */

  async openTab(id) {
    const { openTabIds, currentConvId } = get();

    // Already open: just switch
    if (openTabIds.includes(id)) {
      if (id !== currentConvId) get().switchTab(id);
      return;
    }

    // Save current tab state before opening new one
    const curState = get();
    const saveTabStates: Record<string, TabState> = { ...curState.tabStates };
    if (curState.currentConvId) {
      saveTabStates[curState.currentConvId] = {
        ...(saveTabStates[curState.currentConvId] ?? emptyTabState()),
        ...tabFieldsFromSlice(sliceFromState(curState)),
      };
    }

    // Use cached or empty state for target
    const cached = saveTabStates[id] ?? emptyTabState();
    saveTabStates[id] = cached;

    set({
      activeTabId: id,
      currentConvId: id,
      openTabIds: [...openTabIds, id],
      tabStates: saveTabStates,
      ...flatFieldsFromTab(cached),
    } as any);

    // Fetch fresh if not cached
    if (cached.messages.length === 0) {
      try {
        const [msgs, stats] = await Promise.all([
          fetchMessages(id, 200),
          fetchContextStats(id).catch(() => null),
        ]);
        set((s) => ({
          messages: msgs,
          contextStats: stats
            ? { total: stats.total_messages, pinned: stats.pinned_messages }
            : null,
          tabStates: {
            ...s.tabStates,
            [id]: {
              ...s.tabStates[id],
              messages: msgs,
              contextStats: stats
                ? { total: stats.total_messages, pinned: stats.pinned_messages }
                : null,
            },
          },
        }));
      } catch (err) {
        console.error("fetchMessages failed", err);
      }
    }

    ws.send({ type: "join", conversation_id: id, limit: 200 });
  },

  closeTab(id) {
    const { openTabIds, tabStates, activeTabId } = get();
    const idx = openTabIds.indexOf(id);
    if (idx < 0) return;

    const nextIds = openTabIds.filter((x) => x !== id);
    const nextStates = { ...tabStates };
    delete nextStates[id];

    let nextActive = activeTabId;
    if (activeTabId === id) {
      nextActive = nextIds.length > 0 ? nextIds[Math.min(idx, nextIds.length - 1)] : null;
    }

    const update: Record<string, any> = {
      openTabIds: nextIds,
      tabStates: nextStates,
      activeTabId: nextActive,
      currentConvId: nextActive,
    };

    if (nextActive && nextStates[nextActive]) {
      Object.assign(update, flatFieldsFromTab(nextStates[nextActive]));
    } else {
      Object.assign(update, flatFieldsFromTab(emptyTabState()));
    }

    set(update as any);
  },

  switchTab(id) {
    const { openTabIds, tabStates, currentConvId } = get();
    if (!openTabIds.includes(id) || id === currentConvId) return;

    // Save current state into cache
    const curState = sliceFromState(get());
    const saveTabStates = { ...tabStates };
    if (currentConvId) {
      saveTabStates[currentConvId] = {
        ...(saveTabStates[currentConvId] ?? emptyTabState()),
        ...tabFieldsFromSlice(curState),
      };
    }

    // Restore target
    const target = saveTabStates[id] ?? emptyTabState();
    set({
      activeTabId: id,
      currentConvId: id,
      tabStates: saveTabStates,
      ...flatFieldsFromTab(target),
    } as any);
  },

  /* ---- conversation CRUD ---- */

  async selectConversation(id) {
    await get().openTab(id);
  },

  async createAndSelect(input) {
    const conv = await createConversation(input);
    set((s) => ({
      conversations: [conv, ...s.conversations.filter((x) => x.id !== conv.id)],
    }));
    await get().openTab(conv.id);
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

  /* ---- messaging ---- */

  sendText(text, mentions) {
    const cid = get().currentConvId;
    if (!cid) return;
    const tempId = `temp-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
    const optimisticMsg: Message = {
      id: tempId,
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
    for (const mid of ids) {
      ws.send({ type: "cancel", message_id: mid });
    }
  },

  cancelMessage(messageId) {
    ws.send({ type: "cancel", message_id: messageId });
  },
}));

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Extract conversation_id from a ServerEvent (if any). */
function _eventConversationId(evt: ServerEvent): string | null {
  const e = evt as any;
  if (typeof e.conversation_id === "string") return e.conversation_id;
  // Some events have it nested (e.g. message_created.message.conversation_id)
  if (e.message && typeof e.message.conversation_id === "string") return e.message.conversation_id;
  return null;
}

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
    agentGraphNodes: s.agentGraphNodes ?? {},
    agentGraphBeams: s.agentGraphBeams ?? [],
    agentGraphEvents: s.agentGraphEvents ?? [],
    agentGraphStatuses: s.agentGraphStatuses ?? {},
  };
}
