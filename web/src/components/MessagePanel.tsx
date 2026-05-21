import { useEffect, useRef } from "react";

import { useChatStore } from "../stores/useChatStore";
import { MessageBubble } from "./MessageBubble";

export function MessagePanel() {
  const messages = useChatStore((s) => s.messages);
  const streamingIds = useChatStore((s) => s.streamingMessageIds);
  const agentTyping = useChatStore((s) => s.agentTyping);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    // 简单粗暴：每次消息更新就滚到底
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
      {messages.map((m) => (
        <MessageBubble key={m.id} msg={m} streaming={streamingIds.includes(m.id)} />
      ))}
      {agentTyping && (
        <div className="text-xs text-muted px-3 animate-fade-in">
          Agent 正在思考…
        </div>
      )}
    </div>
  );
}
