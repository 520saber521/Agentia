import type { Message } from "../types";

interface Props {
  msg: Message;
  streaming?: boolean;
}

function extractText(content: Message["content"]): string {
  if (content && typeof content === "object" && "text" in content) {
    const t = (content as { text?: unknown }).text;
    if (typeof t === "string") return t;
  }
  return "";
}

export function MessageBubble({ msg, streaming }: Props) {
  const isUser = msg.sender_type === "user";
  const text = extractText(msg.content);
  const time = new Date(msg.created_at).toLocaleTimeString();

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
        <span>{text}</span>
        {streaming && (
          <span className="ml-1 inline-block text-fg/70 animate-blink">▍</span>
        )}
        <div className="text-[10.5px] text-muted mt-1.5 select-none">
          {isUser ? "user" : "agent"} · {msg.sender_id} · {time}
        </div>
      </div>
    </div>
  );
}
