import { useState } from "react";

import { useChatStore } from "../stores/useChatStore";
import { AgentCreateDialog } from "./AgentCreateDialog";
import { NewConversationDialog } from "./NewConversationDialog";

export function ConversationListPanel() {
  const items = useChatStore((s) => s.conversations);
  const agents = useChatStore((s) => s.agents);
  const current = useChatStore((s) => s.currentConvId);
  const select = useChatStore((s) => s.selectConversation);
  const refresh = useChatStore((s) => s.refreshConversations);
  const startAgentChat = useChatStore((s) => s.startAgentChat);

  const [showCreate, setShowCreate] = useState(false);
  const [showAgentCreate, setShowAgentCreate] = useState(false);
  const [editingAgent, setEditingAgent] = useState<(typeof agents)[number] | null>(null);

  return (
    <aside className="w-72 min-w-72 max-w-72 bg-panel flex flex-col min-h-0 shrink-0 overflow-hidden">
      <div className="px-4 h-12 flex items-center justify-between border-b border-border shrink-0">
        <h2 className="text-xs uppercase tracking-[0.08em] text-muted font-semibold">
          会话
        </h2>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowCreate(true)}
            className="text-xs px-2 py-1 rounded-md border border-border text-muted hover:text-fg hover:border-accent/60 transition"
            title="新建会话"
          >
            ＋ 新建
          </button>
          <button
            onClick={() => void refresh()}
            className="text-xs text-muted hover:text-fg transition"
          >
            刷新
          </button>
        </div>
      </div>
      <NewConversationDialog
        open={showCreate}
        onClose={() => setShowCreate(false)}
      />
      <AgentCreateDialog
        open={showAgentCreate || editingAgent != null}
        agent={editingAgent}
        onClose={() => {
          setShowAgentCreate(false);
          setEditingAgent(null);
        }}
      />
      <div className="border-b border-border p-2">
        <div className="mb-2 flex items-center justify-between px-1">
          <h3 className="text-[10.5px] font-semibold uppercase text-muted">
            Agent contacts
          </h3>
          <button
            type="button"
            onClick={() => setShowAgentCreate(true)}
            className="rounded-md border border-border px-2 py-1 text-[10.5px] text-muted transition hover:border-accent/60 hover:text-fg"
            title="Create custom Agent"
          >
            New Agent
          </button>
        </div>
        <div className="max-h-52 space-y-1 overflow-y-auto pr-1">
          {agents.map((agent) => (
            <div
              key={agent.id}
              className="group rounded-md border border-border p-2 transition hover:border-accent/60 hover:bg-accent/10"
            >
              <button
                type="button"
                onClick={() => void startAgentChat(agent.id)}
                className="w-full text-left"
              >
                <div className="flex items-center gap-2">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent/15 text-xs font-semibold text-accent">
                    {agent.avatar || agent.name.slice(0, 1).toUpperCase()}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-fg">
                      {agent.name}
                    </span>
                    <span className="block truncate text-[10.5px] text-muted">
                      {agent.adapter_type} · {agent.model || "model unset"}
                    </span>
                  </span>
                </div>
              </button>
              <div className="mt-2 flex items-center justify-between gap-2">
                <div className="min-w-0 flex-1">
                  {agent.capabilities.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {agent.capabilities.slice(0, 4).map((cap) => (
                        <span
                          key={cap}
                          className="rounded border border-border bg-bg px-1.5 py-0.5 text-[10px] text-muted"
                        >
                          {cap}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => setEditingAgent(agent)}
                  className="rounded border border-border px-2 py-1 text-[10px] text-muted opacity-90 transition hover:border-accent/60 hover:text-fg"
                  title="Edit Agent"
                >
                  Edit
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
      <ul className="flex-1 overflow-y-auto p-2 space-y-1">
        {items.length === 0 && (
          <li className="px-3 py-4 text-xs text-muted">(无会话)</li>
        )}
        {items.map((c) => {
          const active = c.id === current;
          return (
            <li key={c.id}>
              <button
                type="button"
                onClick={() => void select(c.id)}
                className={`w-full text-left p-3 rounded-md border transition ${
                  active
                    ? "border-accent bg-accent/10"
                    : "border-border hover:border-accent/60"
                }`}
              >
                <div className="font-medium text-sm text-fg truncate">
                  {c.title}
                </div>
                <div className="text-xs text-muted truncate mt-1">
                  {c.last_msg_preview || "(暂无消息)"}
                </div>
                <div className="text-[10.5px] text-muted mt-1 truncate">
                  {c.type} · {c.members.length} 成员 · {c.id}
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
