import { useMemo, useState } from "react";

import { fetchAgentPrompt } from "../api/client";
import { useChatStore } from "../stores/useChatStore";
import { AgentCreateDialog } from "./AgentCreateDialog";
import { NewConversationDialog } from "./NewConversationDialog";

type ViewMode = "active" | "archived";

function formatTime(ts: number): string {
  const d = new Date(ts);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString([], { month: "2-digit", day: "2-digit" });
}

const CAP_COLORS: Record<string, string> = {
  actor: "border-blue-500/40 bg-blue-500/10 text-blue-400",
  critic: "border-amber-500/40 bg-amber-500/10 text-amber-400",
  idea: "border-purple-500/40 bg-purple-500/10 text-purple-400",
  prd: "border-emerald-500/40 bg-emerald-500/10 text-emerald-400",
  design: "border-cyan-500/40 bg-cyan-500/10 text-cyan-400",
  plan: "border-rose-500/40 bg-rose-500/10 text-rose-400",
  coding: "border-indigo-500/40 bg-indigo-500/10 text-indigo-400",
  frontend: "border-blue-500/40 bg-blue-500/10 text-blue-400",
  backend: "border-emerald-500/40 bg-emerald-500/10 text-emerald-400",
  database: "border-purple-500/40 bg-purple-500/10 text-purple-400",
  testing: "border-amber-500/40 bg-amber-500/10 text-amber-400",
  devops: "border-rose-500/40 bg-rose-500/10 text-rose-400",
  orchestration: "border-accent/40 bg-accent/10 text-accent",
};

function capColor(cap: string): string {
  for (const [key, color] of Object.entries(CAP_COLORS)) {
    if (cap.toLowerCase().includes(key)) return color;
  }
  return "border-border bg-bg text-muted";
}

export function ConversationListPanel() {
  const items = useChatStore((s) => s.conversations);
  const agents = useChatStore((s) => s.agents);
  const current = useChatStore((s) => s.currentConvId);
  const select = useChatStore((s) => s.openTab);
  const refresh = useChatStore((s) => s.refreshConversations);
  const startAgentChat = useChatStore((s) => s.startAgentChat);
  const createAndSelect = useChatStore((s) => s.createAndSelect);
  const updateConversationMeta = useChatStore((s) => s.updateConversationMeta);

  const [showCreate, setShowCreate] = useState(false);
  const [showAgentCreate, setShowAgentCreate] = useState(false);
  const [editingAgent, setEditingAgent] = useState<(typeof agents)[number] | null>(null);
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<ViewMode>("active");
  const [promptAgentId, setPromptAgentId] = useState<string | null>(null);
  const [promptText, setPromptText] = useState("");
  const [promptLoading, setPromptLoading] = useState(false);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return items.filter((c) => {
      if (mode === "active" && c.archived) return false;
      if (mode === "archived" && !c.archived) return false;
      if (!q) return true;
      return (
        c.title.toLowerCase().includes(q) ||
        (c.last_msg_preview ?? "").toLowerCase().includes(q) ||
        c.members.some((m) => m.member_id.toLowerCase().includes(q))
      );
    });
  }, [items, mode, query]);

  async function togglePrompt(agentId: string) {
    if (promptAgentId === agentId) {
      setPromptAgentId(null);
      return;
    }
    setPromptAgentId(agentId);
    setPromptText("");
    setPromptLoading(true);
    try {
      const res = await fetchAgentPrompt(agentId);
      setPromptText(res.prompt);
    } catch {
      setPromptText("");
    } finally {
      setPromptLoading(false);
    }
  }

  async function createLoginDemoConversation() {
    await createAndSelect({
      title: "登录页多 Agent 协作 Demo",
      type: "group",
      agent_ids: ["agent_orchestrator", "agent_mock", "agent_mock_2", "agent_claude", "agent_deepseek"],
    });
  }

  return (
    <aside className="flex min-h-0 w-80 min-w-80 max-w-80 shrink-0 flex-col overflow-hidden border-r border-border bg-panel">
      <div className="shrink-0 border-b border-border px-4 py-3">
        <div className="flex items-center justify-between">
          <h2 className="text-xs font-semibold uppercase tracking-[0.08em] text-muted">Conversations</h2>
          <div className="flex items-center gap-2">
            <button
              onClick={() => void createLoginDemoConversation()}
              className="rounded-md border border-accent/50 px-2.5 py-1.5 text-xs text-accent transition hover:bg-accent/10"
              title="创建登录页多 Agent 协作 Demo 群聊"
            >
              Demo
            </button>
            <button
              onClick={() => setShowCreate(true)}
              className="rounded-md bg-accent px-2.5 py-1.5 text-xs text-white transition hover:bg-accent-hover"
              title="新建会话"
            >
              新建
            </button>
            <button
              onClick={() => void refresh()}
              className="rounded-md border border-border px-2.5 py-1.5 text-xs text-muted transition hover:border-accent/60 hover:text-fg"
            >
              刷新
            </button>
          </div>
        </div>

        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索标题、成员或最近消息"
          className="mt-3 w-full rounded-md border border-border bg-bg px-3 py-2 text-xs text-fg outline-none transition focus:border-accent"
        />

        <div className="mt-2 grid grid-cols-2 gap-1 rounded-md border border-border bg-bg p-1">
          {(["active", "archived"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={`rounded px-2 py-1.5 text-xs transition ${mode === m ? "bg-panel text-fg shadow-sm" : "text-muted hover:text-fg"}`}
            >
              {m === "active" ? "活跃" : "归档"}
            </button>
          ))}
        </div>
      </div>

      <NewConversationDialog open={showCreate} onClose={() => setShowCreate(false)} />
      <AgentCreateDialog
        open={showAgentCreate || editingAgent != null}
        agent={editingAgent}
        onClose={() => {
          setShowAgentCreate(false);
          setEditingAgent(null);
        }}
      />

      <div className="border-b border-border p-3">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-[10.5px] font-semibold uppercase text-muted">Agent contacts</h3>
          <button
            type="button"
            onClick={() => setShowAgentCreate(true)}
            className="rounded-md border border-border px-2 py-1 text-[10.5px] text-muted transition hover:border-accent/60 hover:text-fg"
          >
            New Agent
          </button>
        </div>
        <div className="max-h-80 space-y-1 overflow-y-auto pr-1">
          {agents.map((agent) => (
            <div key={agent.id} className="group rounded-md border border-border p-2 transition hover:border-accent/60 hover:bg-accent/10">
              <button type="button" onClick={() => void startAgentChat(agent.id)} className="w-full text-left">
                <div className="flex items-center gap-2">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent/15 text-xs font-semibold text-accent">
                    {agent.avatar || agent.name.slice(0, 1).toUpperCase()}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-fg">{agent.name}</span>
                    <span className="block truncate text-[10.5px] text-muted">
                      {agent.adapter_type}
                      {agent.model ? ` · ${agent.model}` : ""}
                    </span>
                  </span>
                  <span
                    className={`h-2 w-2 shrink-0 rounded-full ${agent.api_key_configured || agent.adapter_type === "mock" ? "bg-emerald-400" : "bg-amber-400"}`}
                    title={agent.api_key_configured ? "可调用" : "未配置 API Key"}
                  />
                </div>
              </button>

              <div className="mt-2 flex items-center justify-between gap-2">
                <div className="min-w-0 flex-1">
                  {agent.capabilities.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {agent.capabilities.slice(0, 4).map((cap) => (
                        <span key={cap} className={`rounded border px-1.5 py-0.5 text-[10px] ${capColor(cap)}`}>
                          {cap}
                        </span>
                      ))}
                      {agent.capabilities.length > 4 && (
                        <span className="rounded border border-border bg-bg px-1.5 py-0.5 text-[10px] text-muted">
                          +{agent.capabilities.length - 4}
                        </span>
                      )}
                    </div>
                  )}
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  {agent.is_system && (
                    <span className="rounded border border-accent/30 bg-accent/5 px-1 py-0.5 text-[9px] text-accent/70">system</span>
                  )}
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      void startAgentChat(agent.id);
                    }}
                    className="rounded border border-accent/50 bg-accent/10 px-2 py-0.5 text-[10px] text-accent transition hover:bg-accent/20 hover:border-accent"
                    title={`与 ${agent.name} 开始对话`}
                  >
                    Chat
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      void togglePrompt(agent.id);
                    }}
                    className="rounded border border-border px-1.5 py-0.5 text-[10px] text-muted transition hover:border-accent/60 hover:text-fg"
                    title="View prompt"
                  >
                    Prompt
                  </button>
                  <button
                    type="button"
                    onClick={() => setEditingAgent(agent)}
                    className="rounded border border-border px-1.5 py-0.5 text-[10px] text-muted transition hover:border-accent/60 hover:text-fg"
                  >
                    Edit
                  </button>
                </div>
              </div>

              {promptAgentId === agent.id && (
                <div className="mt-2 rounded border border-border bg-bg/80">
                  {promptLoading ? (
                    <div className="px-2 py-2 text-[10px] italic text-muted">Loading prompt...</div>
                  ) : promptText ? (
                    <pre className="max-h-32 overflow-y-auto whitespace-pre-wrap px-2 py-2 font-mono text-[10px] leading-relaxed text-muted">
                      {promptText.slice(0, 800)}
                      {promptText.length > 800 && <span className="text-accent/60"> ... (truncated)</span>}
                    </pre>
                  ) : (
                    <div className="px-2 py-2 text-[10px] italic text-muted">No prompt available.</div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      <ul className="flex-1 space-y-1 overflow-y-auto p-2">
        {filtered.length === 0 && (
          <li className="px-3 py-5 text-center text-xs text-muted">
            {mode === "archived" ? "没有归档会话" : "没有匹配的会话"}
          </li>
        )}
        {filtered.map((c) => {
          const active = c.id === current;
          return (
            <li key={c.id}>
              <div className={`rounded-md border transition ${active ? "border-accent bg-accent/10" : "border-border hover:border-accent/60"}`}>
                <button type="button" onClick={() => void select(c.id)} className="w-full p-3 text-left">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        {c.pinned && <span className="text-[10px] text-accent">置顶</span>}
                        <span className="truncate text-sm font-medium text-fg">{c.title}</span>
                      </div>
                      <div className="mt-1 truncate text-xs text-muted">{c.last_msg_preview || "暂无消息"}</div>
                    </div>
                    <span className="shrink-0 text-[10px] text-muted">{formatTime(c.updated_at)}</span>
                  </div>
                  <div className="mt-2 flex items-center justify-between gap-2 text-[10.5px] text-muted">
                    <span>
                      {c.type === "group" ? "群聊" : "单聊"} · {c.members.length} 成员
                    </span>
                    <span className="truncate">{c.id}</span>
                  </div>
                </button>
                <div className="flex items-center gap-1 border-t border-border px-2 py-1">
                  <button
                    type="button"
                    onClick={() => void updateConversationMeta(c.id, { pinned: !c.pinned })}
                    className="rounded px-2 py-1 text-[10px] text-muted transition hover:bg-bg hover:text-fg"
                  >
                    {c.pinned ? "取消置顶" : "置顶"}
                  </button>
                  <button
                    type="button"
                    onClick={() => void updateConversationMeta(c.id, { archived: !c.archived })}
                    className="rounded px-2 py-1 text-[10px] text-muted transition hover:bg-bg hover:text-fg"
                  >
                    {c.archived ? "恢复" : "归档"}
                  </button>
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
