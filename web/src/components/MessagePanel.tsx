import { useEffect, useMemo, useRef } from "react";

import { useChatStore } from "../stores/useChatStore";
import type { Agent } from "../types";
import { MessageBubble } from "./MessageBubble";

export function MessagePanel() {
  const messages = useChatStore((s) => s.messages);
  const streamingIds = useChatStore((s) => s.streamingMessageIds);
  const agentTyping = useChatStore((s) => s.agentTyping);
  const agents = useChatStore((s) => s.agents);
  const scrollRef = useRef<HTMLDivElement>(null);

  const agentsById = useMemo(() => {
    const map = new Map<string, Agent>();
    for (const a of agents) {
      map.set(a.id, a);
    }
    return map;
  }, [agents]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, agentTyping]);

  return (
    <div
      ref={scrollRef}
      className="flex-1 overflow-y-auto p-6 space-y-3 min-h-0"
    >
      {messages.length === 0 && (
        <div className="text-xs text-muted text-center mt-16">
          对话还是空的 —— 在下面输入一段话就开始吧。
        </div>
      )}
      {messages.map((m) => {
        const agent = m.sender_type === "agent" ? agentsById.get(m.sender_id) : undefined;
        return (
          <MessageBubble
            key={m.id}
            msg={m}
            streaming={streamingIds.includes(m.id)}
            agentName={agent?.name}
          />
        );
      })}
      {agentTyping && (
        <div className="text-xs text-muted px-3 animate-fade-in">
          Agent 正在思考…
        </div>
      )}
    </div>
  );
}
