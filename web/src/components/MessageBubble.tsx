import { ContentRenderer } from "./ContentRenderer";
import { useChatStore } from "../stores/useChatStore";
import type { Message } from "../types";

interface Props {
  msg: Message;
  streaming?: boolean;
  onEditArtifact?: (artifactId: string) => void;
}

export function MessageBubble({ msg, streaming, onEditArtifact }: Props) {
  const isUser = msg.sender_type === "user";
  const time = new Date(msg.created_at).toLocaleTimeString();
  const agents = useChatStore((s) => s.agents);
  const agentName = agents.find((a) => a.id === msg.sender_id)?.name;

  return (
    <div
      className={`flex animate-fade-in ${
        isUser ? "justify-end" : "justify-start"
      }`}
    >
      <div
        className={`w-fit max-w-[min(78%,56rem)] rounded-xl px-3.5 py-2 text-sm leading-relaxed break-words ${
          isUser
            ? "bg-user text-white"
            : "bg-agent text-fg border border-border"
        }`}
      >
        <ContentRenderer
          content={msg.content}
          artifactId={msg.artifact_id}
          onEditArtifact={onEditArtifact}
        />
        {streaming && msg.content.type === "text" && (
          <span className="ml-1 inline-block text-fg/70 animate-blink">▍</span>
        )}
        <div className="text-[10.5px] text-muted mt-1.5 select-none">
          {isUser ? "user" : agentName ?? "agent"} · {time}
        </div>
      </div>
    </div>
  );
}
