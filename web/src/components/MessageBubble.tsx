import type { Agent, Message } from "../types";

interface Props {
  msg: Message;
  streaming?: boolean;
  agentName?: string;
  agentColor?: string;
}

function extractText(content: Message["content"]): string {
  if (content && typeof content === "object" && "text" in content) {
    const t = (content as { text?: unknown }).text;
    if (typeof t === "string") return t;
  }
  return "";
}

function hashColor(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = id.charCodeAt(i) + ((hash << 5) - hash);
  }
  const hue = ((hash % 360) + 360) % 360;
  return `hsl(${hue}, 42%, 48%)`;
}

function initials(name: string): string {
  return name.slice(0, 2).toUpperCase();
}

export function MessageBubble({ msg, streaming, agentName, agentColor }: Props) {
  const isUser = msg.sender_type === "user";
  const text = extractText(msg.content);
  const time = new Date(msg.created_at).toLocaleTimeString();
  const displayName = agentName || msg.sender_id;
  const color = agentColor || (isUser ? undefined : hashColor(msg.sender_id));

  return (
    <div
      className={`flex animate-fade-in ${
        isUser ? "justify-end" : "justify-start"
      }`}
    >
      <div
        className={`max-w-[78%] rounded-xl px-3.5 py-2 text-sm leading-relaxed whitespace-pre-wrap break-words ${
          isUser
            ? "bg-user text-white"
            : "bg-agent text-fg border border-border"
        }`}
      >
        {!isUser && (
          <div className="flex items-center gap-2 mb-1.5">
            <span
              className="inline-flex items-center justify-center w-5 h-5 rounded-full text-[10px] font-semibold text-white shrink-0"
              style={{ backgroundColor: color }}
            >
              {initials(displayName)}
            </span>
            <span className="text-xs font-semibold text-fg truncate">
              {displayName}
            </span>
          </div>
        )}
        <span>{text}</span>
        {streaming && (
          <span className="ml-1 inline-block text-fg/70 animate-blink">▍</span>
        )}
        <div className="text-[10.5px] text-muted mt-1.5 select-none">
          {time}
        </div>
      </div>
    </div>
  );
}
