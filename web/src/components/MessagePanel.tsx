import { useEffect, useRef } from "react";

import { useChatStore } from "../stores/useChatStore";
import { MessageBubble } from "./MessageBubble";
import { TaskStatusCard } from "./TaskStatusCard";

interface Props {
  onEditArtifact?: (artifactId: string) => void;
}

export function MessagePanel({ onEditArtifact }: Props) {
  const messages = useChatStore((s) => s.messages);
  const streamingIds = useChatStore((s) => s.streamingMessageIds);
  const agentTyping = useChatStore((s) => s.agentTyping);
  const tasks = useChatStore((s) => s.tasks);
  const currentConvId = useChatStore((s) => s.currentConvId);
  const scrollRef = useRef<HTMLDivElement>(null);

  const currentTasks = currentConvId
    ? Object.values(tasks ?? {})
        .filter((t) => t.conversation_id === currentConvId)
        .sort((a, b) => a.created_at - b.created_at)
    : [];

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, agentTyping, tasks]);

  return (
    <div
      ref={scrollRef}
      className="flex-1 overflow-y-auto p-6 space-y-3 min-h-0"
    >
      {messages.length === 0 && currentTasks.length === 0 && (
        <div className="text-xs text-muted text-center mt-16">
          对话还是空的 —— 在下面输入一段话就开始吧。
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
      {currentTasks.map((task) => (
        <TaskStatusCard key={task.id} task={task} />
      ))}
      {agentTyping && (
        <div className="text-xs text-muted px-3 animate-fade-in">
          Agent 正在思考…
        </div>
      )}
    </div>
  );
}
