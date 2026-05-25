import { useMemo } from "react";
import { useChatStore } from "../stores/useChatStore";
import type { Agent, Member, Message } from "../types";

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function textOf(msg: Message): string {
  if (msg.content.type === "text") return msg.content.text;
  if ("title" in msg.content && typeof msg.content.title === "string") return msg.content.title;
  return msg.content.type;
}

export function ContextSidebar() {
  const messages = useChatStore((s) => s.messages);
  const conversations = useChatStore((s) => s.conversations);
  const agents = useChatStore((s) => s.agents);
  const contextStats = useChatStore((s) => s.contextStats);
  const currentConvId = useChatStore((s) => s.currentConvId);

  const currentConv = conversations.find((c) => c.id === currentConvId);
  const members = currentConv?.members ?? [];

  const agentMembers = members
    .filter((m) => m.member_type === "agent")
    .map((m) => ({
      ...m,
      agent: agents.find((a) => a.id === m.member_id),
    }))
    .filter((m): m is Member & { agent: Agent } => m.agent != null);

  const userMembers = members.filter((m) => m.member_type === "user");

  const pinnedMessages = useMemo(
    () => messages
      .filter((m) => m.pinned && m.content.type === "text")
      .sort((a, b) => b.created_at - a.created_at)
      .slice(0, 20),
    [messages],
  );

  const statsDisplay = contextStats
    ? `已携带 ${contextStats.total} 条历史消息 / ${contextStats.pinned} 条 Pin 消息`
    : pinnedMessages.length > 0
      ? `${pinnedMessages.length} 条 Pin 消息`
      : "暂无 Pin 消息";

  const strategyLabel =
    contextStats?.strategy === "sliding" ? "滑窗"
    : contextStats?.strategy === "token" ? "Token 裁剪"
    : contextStats?.strategy === "hybrid" ? "混合"
    : null;

  return (
    <aside className="w-64 min-w-64 max-w-64 flex flex-col bg-panel border-l border-border shrink-0 overflow-hidden">
      <div className="px-4 py-3 border-b border-border">
        <h3 className="text-sm font-medium text-fg">上下文</h3>
        <p className="text-xs text-muted mt-0.5">{members.length} 位成员</p>
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* Context Stats */}
        <div className="border-b border-border">
          <div className="px-3 py-2">
            <h4 className="text-[10px] font-semibold uppercase text-muted tracking-wider mb-1.5">
              上下文信息
            </h4>
            <div className="rounded-md border border-border bg-bg p-2">
              <div className="flex items-center gap-1.5 text-[11px] text-fg">
                <span className="text-accent">📊</span>
                <span className="font-medium">
                  {contextStats ? (
                    <>
                      {contextStats.total} 条历史
                      {contextStats.pinned > 0 && (
                        <span className="text-amber-400"> · {contextStats.pinned} 条 Pin</span>
                      )}
                    </>
                  ) : (
                    "加载中…"
                  )}
                </span>
              </div>
              {contextStats && (
                <div className="mt-1.5 space-y-0.5">
                  {contextStats.historyCount != null && (
                    <div className="flex items-center gap-1 text-[10px] text-muted">
                      <span>Agent 携带</span>
                      <span className="rounded bg-bg-secondary px-1 font-mono text-[9px]">
                        {contextStats.historyCount}
                      </span>
                      <span>条消息</span>
                    </div>
                  )}
                  {contextStats.estimatedTokens != null && (
                    <div className="flex items-center gap-1 text-[10px] text-muted">
                      <span>约</span>
                      <span className="rounded bg-bg-secondary px-1 font-mono text-[9px]">
                        {contextStats.estimatedTokens.toLocaleString()}
                      </span>
                      <span>tokens</span>
                    </div>
                  )}
                  {strategyLabel && (
                    <div className="flex items-center gap-1 text-[10px] text-muted">
                      <span>策略:</span>
                      <span className="rounded border border-border px-1 font-mono text-[9px]">
                        {strategyLabel}
                      </span>
                    </div>
                  )}
                  <div className="flex items-center gap-1 text-[10px] text-muted/60">
                    <span>每次 Agent 请求自动携带 Pin 上下文</span>
                  </div>
                </div>
              )}
              {!contextStats && pinnedMessages.length > 0 && (
                <div className="mt-1 flex items-center gap-1 text-[10px] text-muted">
                  <span>每次 Agent 请求自动携带 Pin 上下文</span>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Pinned Messages */}
        <div className="border-b border-border">
          <div className="px-3 py-2">
            <h4 className="text-[10px] font-semibold uppercase text-muted tracking-wider mb-1.5">
              📌 Pin 消息 ({pinnedMessages.length})
            </h4>
            {pinnedMessages.length === 0 ? (
              <div className="rounded-md border border-dashed border-border bg-bg/50 px-2 py-3 text-center">
                <div className="text-[10px] text-muted">
                  将消息悬停 → 点击 📌 Pin 即可固定到上下文
                </div>
                <div className="mt-1 text-[10px] text-muted/60">
                  Pin 消息会优先带入 Agent 的对话上下文
                </div>
              </div>
            ) : (
              <div className="space-y-1">
                {pinnedMessages.map((msg) => {
                  const agent = agents.find((a) => a.id === msg.sender_id);
                  const text = textOf(msg);
                  return (
                    <div
                      key={msg.id}
                      className="rounded-md border border-amber-500/15 bg-amber-500/5 px-2 py-1.5"
                    >
                      <div className="flex items-center gap-1 text-[10px] text-amber-400/80 mb-0.5">
                        <span className="font-medium">
                          {msg.sender_type === "user" ? "用户" : agent?.name ?? msg.sender_id}
                        </span>
                        <span className="text-muted/50">·</span>
                        <span className="text-muted/60">
                          {formatTime(msg.created_at)}
                        </span>
                      </div>
                      <div className="text-[10px] text-fg/80 leading-relaxed line-clamp-3 break-words">
                        {text.slice(0, 300)}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Members */}
        <div className="px-2 py-2">
          {userMembers.length > 0 && (
            <div className="space-y-1 mb-3">
              <div className="px-2 py-1 text-xs font-medium text-muted uppercase tracking-wider">
                用户
              </div>
              {userMembers.map((member) => (
                <div
                  key={member.member_id}
                  className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-accent/10 transition-colors"
                >
                  <span className="w-6 h-6 rounded bg-user flex items-center justify-center text-[10px] text-white shrink-0 select-none">
                    👤
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-fg truncate">
                      {member.member_id}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {agentMembers.length > 0 && (
            <div className="space-y-1">
              <div className="px-2 py-1 text-xs font-medium text-muted uppercase tracking-wider">
                Agent ({agentMembers.length})
              </div>
              {agentMembers.map((member) => (
                <div
                  key={member.member_id}
                  className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-accent/10 transition-colors"
                >
                  <span className="w-7 h-7 rounded-lg bg-accent/20 flex items-center justify-center text-sm shrink-0 select-none">
                    {member.agent.avatar || member.agent.name.charAt(0).toUpperCase()}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-fg truncate">
                      {member.agent.name}
                    </div>
                    <div className="text-xs text-muted truncate">
                      {member.agent.adapter_type} · {member.agent.capabilities.slice(0, 3).join(" · ")}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {members.length === 0 && (
            <div className="px-2 py-4 text-center text-xs text-muted">
              暂无成员
            </div>
          )}
        </div>
      </div>

      <div className="px-4 py-3 border-t border-border">
        <div className="text-xs text-muted">
          会话类型: {currentConv?.type === "group" ? "群聊" : "单聊"}
        </div>
        <div className="text-[10px] text-muted/60 mt-0.5">
          Pin 消息会在 Agent 调用时作为长期上下文注入
        </div>
      </div>
    </aside>
  );
}
