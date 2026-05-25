import { useEffect, useMemo, useRef } from "react";

import { useChatStore } from "../stores/useChatStore";
import type { Agent } from "../types";
import { MessageBubble } from "./MessageBubble";
import { CollaborationProgressCard } from "./CollaborationProgressCard";

interface Props {
  onEditArtifact?: (artifactId: string) => void;
}

export function MessagePanel({ onEditArtifact }: Props) {
  const messages = useChatStore((s) => s.messages);
  const streamingIds = useChatStore((s) => s.streamingMessageIds);
  const agentTyping = useChatStore((s) => s.agentTyping);
  const tasks = useChatStore((s) => s.tasks);
  const currentConvId = useChatStore((s) => s.currentConvId);
  const conversations = useChatStore((s) => s.conversations);
  const agents = useChatStore((s) => s.agents);
  const scrollRef = useRef<HTMLDivElement>(null);
  const shouldStickToBottomRef = useRef(true);

  const currentTasks = currentConvId
    ? Object.values(tasks ?? {})
        .filter((t) => t.conversation_id === currentConvId)
        .sort((a, b) => a.created_at - b.created_at)
    : [];

  const currentConv = conversations.find((c) => c.id === currentConvId);
  const memberAgents = (currentConv?.members ?? [])
    .filter((m) => m.member_type === "agent")
    .map((m) => agents.find((a) => a.id === m.member_id))
    .filter((a): a is NonNullable<typeof a> => a != null);

  const agentsById = useMemo(() => {
    const map = new Map<string, Agent>();
    for (const a of agents) {
      map.set(a.id, a);
    }
    return map;
  }, [agents]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !shouldStickToBottomRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, agentTyping, tasks]);

  function handleScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    shouldStickToBottomRef.current = distanceToBottom < 80;
  }

  useEffect(() => {
    shouldStickToBottomRef.current = true;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [currentConvId]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {currentConv && (
        <div className="shrink-0 border-b border-border bg-panel/70 px-5 py-2">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-fg">
                {currentConv.title}
              </div>
              <div className="text-[10.5px] text-muted">
                {currentConv.type === "group" ? "群聊协作" : "单聊"} · {currentConv.members.length} 成员
              </div>
            </div>
            <div className="flex min-w-0 items-center gap-1.5 overflow-x-auto">
              {memberAgents.map((agent) => (
                <div
                  key={agent.id}
                  className="flex shrink-0 items-center gap-1.5 rounded-md border border-border bg-bg px-2 py-1"
                  title={`${agent.name} · ${agent.capabilities.join(", ")}`}
                >
                  <span className="grid h-5 w-5 place-items-center rounded bg-accent/15 text-[10px] text-accent">
                    {agent.avatar || agent.name.charAt(0).toUpperCase()}
                  </span>
                  <span className="max-w-[10rem] truncate text-[11px] text-fg">
                    {agent.name}
                  </span>
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${
                      agent.api_key_configured || agent.adapter_type === "mock"
                        ? "bg-emerald-400"
                        : "bg-amber-400"
                    }`}
                  />
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
        </div>
      )}

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="min-h-0 flex-1 space-y-3 overflow-y-auto overscroll-contain p-6"
      >
        {messages.length === 0 && currentTasks.length === 0 && (
          <div className="mt-16 text-center text-xs text-muted">
            对话还是空的，在下方输入消息即可开始。
          </div>
        )}
        {messages.map((m) => (
          <MessageBubble
            key={m.id}
            msg={m}
            streaming={streamingIds.includes(m.id)}
            onEditArtifact={onEditArtifact}
          />
        ))}
        {currentTasks.length > 0 && (
          <CollaborationProgressCard tasks={currentTasks} />
        )}
        {agentTyping && (
          <div className="animate-fade-in px-3 text-xs text-muted">
            Agent 正在思考...
          </div>
        )}
      </div>
    </div>
  );
}
