import { useMemo, useState } from "react";
import { useChatStore } from "../stores/useChatStore";
import type { Agent, Member, Message, ToolCallInfo } from "../types";
import { WorkspacePanel } from "./WorkspacePanel";

type PanelId = "context" | "workspace" | "tools" | "members" | "pinned";

const PANELS: Array<{ id: PanelId; title: string }> = [
  { id: "context", title: "Context" },
  { id: "workspace", title: "Workspace" },
  { id: "tools", title: "Realtime tools" },
  { id: "members", title: "Members" },
  { id: "pinned", title: "Pinned" },
];

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function textOf(msg: Message): string {
  if (msg.content.type === "text") return msg.content.text;
  if ("title" in msg.content && typeof msg.content.title === "string") return msg.content.title;
  return msg.content.type;
}

function ToolStatus({ call }: { call: ToolCallInfo }) {
  const cls =
    call.status === "running"
      ? "border-sky-500/40 text-sky-200"
      : call.status === "done"
        ? "border-emerald-500/35 text-emerald-200"
        : "border-rose-500/40 text-rose-200";
  return (
    <div className={`rounded-md border bg-bg px-2 py-1.5 ${cls}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-mono text-[10px]">{call.toolName}</span>
        <span className="shrink-0 text-[9px] uppercase">{call.status}</span>
      </div>
      {call.resultSummary && (
        <div className="mt-1 line-clamp-2 text-[10px] leading-relaxed text-muted">
          {call.resultSummary}
        </div>
      )}
    </div>
  );
}

export function ContextSidebar() {
  const messages = useChatStore((s) => s.messages);
  const conversations = useChatStore((s) => s.conversations);
  const agents = useChatStore((s) => s.agents);
  const contextStats = useChatStore((s) => s.contextStats);
  const currentConvId = useChatStore((s) => s.currentConvId);
  const [open, setOpen] = useState<Record<PanelId, boolean>>({
    context: true,
    workspace: true,
    tools: true,
    members: true,
    pinned: false,
  });

  const currentConv = conversations.find((c) => c.id === currentConvId);
  const members = currentConv?.members ?? [];

  const agentMembers = members
    .filter((m) => m.member_type === "agent")
    .map((m) => ({
      ...m,
      agent: agents.find((a) => a.id === m.member_id),
    }))
    .filter((m): m is Member & { agent: Agent } => m.agent != null);

  const pinnedMessages = useMemo(
    () => messages
      .filter((m) => m.pinned && m.content.type === "text")
      .sort((a, b) => b.created_at - a.created_at)
      .slice(0, 20),
    [messages],
  );

  const toolCalls = useMemo(
    () => messages
      .flatMap((message) => (message.toolCalls ?? []).map((call) => ({ ...call, message })))
      .slice(-18)
      .reverse(),
    [messages],
  );

  function toggle(id: PanelId) {
    setOpen((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  return (
    <aside className="flex w-72 min-w-72 max-w-72 shrink-0 flex-col overflow-hidden border-l border-border bg-panel">
      <div className="border-b border-border px-4 py-3">
        <h3 className="text-sm font-semibold text-fg">Runtime panels</h3>
        <p className="mt-0.5 text-xs text-muted">
          {members.length} members / {messages.length} messages
        </p>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {PANELS.map((panel) => (
          <section key={panel.id} className="mb-2 overflow-hidden rounded-md border border-border bg-bg/70">
            <button
              type="button"
              onClick={() => toggle(panel.id)}
              className="flex h-9 w-full items-center justify-between border-b border-border px-3 text-left text-[11px] font-semibold uppercase tracking-[0.14em] text-muted hover:text-fg"
            >
              <span>{panel.title}</span>
              <span className="font-mono text-[10px]">{open[panel.id] ? "-" : "+"}</span>
            </button>

            {open[panel.id] && panel.id === "context" && (
              <div className="space-y-2 p-3 text-xs">
                <div className="grid grid-cols-2 gap-2">
                  <div className="rounded border border-border bg-panel/50 p-2">
                    <div className="text-[10px] text-muted">History</div>
                    <div className="mt-1 font-mono text-sm text-fg">{contextStats?.total ?? messages.length}</div>
                  </div>
                  <div className="rounded border border-border bg-panel/50 p-2">
                    <div className="text-[10px] text-muted">Pinned</div>
                    <div className="mt-1 font-mono text-sm text-fg">{contextStats?.pinned ?? pinnedMessages.length}</div>
                  </div>
                </div>
                {contextStats?.estimatedTokens != null && (
                  <div className="rounded border border-border bg-panel/50 p-2">
                    <div className="text-[10px] text-muted">Estimated tokens</div>
                    <div className="mt-1 font-mono text-sm text-fg">
                      {contextStats.estimatedTokens.toLocaleString()}
                    </div>
                  </div>
                )}
                <div className="text-[10px] leading-relaxed text-muted">
                  Pinned messages and recent history are injected into Agent calls.
                </div>
              </div>
            )}

            {open[panel.id] && panel.id === "workspace" && (
              <div className="min-h-0 flex-1">
                <WorkspacePanel />
              </div>
            )}

            {open[panel.id] && panel.id === "tools" && (
              <div className="space-y-1.5 p-2">
                {toolCalls.length === 0 ? (
                  <div className="rounded border border-dashed border-border px-3 py-4 text-center text-[10px] text-muted">
                    No tool calls yet
                  </div>
                ) : (
                  toolCalls.map((item, idx) => (
                    <ToolStatus key={`${item.message.id}-${item.toolName}-${idx}`} call={item} />
                  ))
                )}
              </div>
            )}

            {open[panel.id] && panel.id === "members" && (
              <div className="space-y-1 p-2">
                {agentMembers.map((member) => (
                  <div key={member.member_id} className="flex items-center gap-2 rounded px-2 py-1.5 hover:bg-accent/10">
                    <span className="grid h-7 w-7 shrink-0 place-items-center rounded bg-accent/15 text-xs text-accent">
                      {member.agent.avatar || member.agent.name.charAt(0).toUpperCase()}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-xs font-medium text-fg">{member.agent.name}</div>
                      <div className="truncate text-[10px] text-muted">
                        {member.agent.adapter_type} / {member.agent.capabilities.slice(0, 2).join(", ")}
                      </div>
                    </div>
                    <span className={`h-1.5 w-1.5 rounded-full ${
                      member.agent.api_key_configured || member.agent.adapter_type === "mock"
                        ? "bg-emerald-400"
                        : "bg-amber-400"
                    }`} />
                  </div>
                ))}
                {agentMembers.length === 0 && (
                  <div className="rounded border border-dashed border-border px-3 py-4 text-center text-[10px] text-muted">
                    No agents in this conversation
                  </div>
                )}
              </div>
            )}

            {open[panel.id] && panel.id === "pinned" && (
              <div className="space-y-1.5 p-2">
                {pinnedMessages.length === 0 ? (
                  <div className="rounded border border-dashed border-border px-3 py-4 text-center text-[10px] text-muted">
                    No pinned context
                  </div>
                ) : (
                  pinnedMessages.map((msg) => {
                    const agent = agents.find((a) => a.id === msg.sender_id);
                    return (
                      <div key={msg.id} className="rounded border border-amber-500/20 bg-amber-500/5 px-2 py-1.5">
                        <div className="mb-0.5 flex items-center gap-1 text-[10px] text-amber-300">
                          <span className="truncate">{msg.sender_type === "user" ? "User" : agent?.name ?? msg.sender_id}</span>
                          <span className="text-muted/60">{formatTime(msg.created_at)}</span>
                        </div>
                        <div className="line-clamp-3 text-[10px] leading-relaxed text-fg/80">
                          {textOf(msg).slice(0, 300)}
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            )}
          </section>
        ))}
      </div>

      <div className="border-t border-border px-4 py-3">
        <div className="text-xs text-muted">
          Mode: {currentConv?.type === "group" ? "group swarm" : "direct chat"}
        </div>
      </div>
    </aside>
  );
}
