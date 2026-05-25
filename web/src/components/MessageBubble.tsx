import { ContentRenderer } from "./ContentRenderer";
import { useChatStore } from "../stores/useChatStore";
import { pinMessage, unpinMessage } from "../api/client";
import type { Agent, Message } from "../types";

interface Props {
  msg: Message;
  streaming?: boolean;
  onEditArtifact?: (artifactId: string) => void;
  agentName?: string;
  agentColor?: string;
}

const AGENT_COLORS: Array<{
  bg: string;
  text: string;
  border: string;
  avatar: string;
}> = [
  { bg: "bg-blue-500/10", text: "text-blue-400", border: "border-blue-500/20", avatar: "bg-blue-500/20" },
  { bg: "bg-emerald-500/10", text: "text-emerald-400", border: "border-emerald-500/20", avatar: "bg-emerald-500/20" },
  { bg: "bg-amber-500/10", text: "text-amber-400", border: "border-amber-500/20", avatar: "bg-amber-500/20" },
  { bg: "bg-purple-500/10", text: "text-purple-400", border: "border-purple-500/20", avatar: "bg-purple-500/20" },
  { bg: "bg-rose-500/10", text: "text-rose-400", border: "border-rose-500/20", avatar: "bg-rose-500/20" },
  { bg: "bg-cyan-500/10", text: "text-cyan-400", border: "border-cyan-500/20", avatar: "bg-cyan-500/20" },
];

function getAgentColor(agentId: string) {
  let hash = 0;
  for (let i = 0; i < agentId.length; i++) {
    hash = ((hash << 5) - hash) + agentId.charCodeAt(i);
    hash |= 0;
  }
  return AGENT_COLORS[Math.abs(hash) % AGENT_COLORS.length];
}

function textOf(msg: Message): string {
  if (msg.content.type === "text") return msg.content.text;
  if ("title" in msg.content && typeof msg.content.title === "string") return msg.content.title;
  if ("fileName" in msg.content && typeof msg.content.fileName === "string") return msg.content.fileName;
  return msg.content.type;
}

function isProblemText(text: string): boolean {
  return text.includes("[提示] 生成中断") || text.includes("[提示] 输出达到模型长度上限");
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

function MessageActions({
  msg,
  streaming,
  canCancel,
}: {
  msg: Message;
  streaming?: boolean;
  canCancel: boolean;
}) {
  const send = useChatStore((s) => s.sendText);
  const cancelMessage = useChatStore((s) => s.cancelMessage);
  const label = msg.sender_type === "user" ? "重新发送" : "重新生成";

  function copy() {
    void navigator.clipboard?.writeText(textOf(msg));
  }

  function quote() {
    window.dispatchEvent(
      new CustomEvent("agenthub:quote-message", {
        detail: {
          sender: msg.sender_id,
          text: textOf(msg),
        },
      }),
    );
  }

  function regenerate() {
    const text = textOf(msg);
    if (!text.trim()) return;
    if (msg.sender_type === "user") send(text);
    else send(`请重新生成上一条回答，并保持需求不变。\n\n参考上一条内容：\n${text.slice(0, 2000)}`);
  }

  async function handlePin() {
    try {
      if (msg.pinned) {
        await unpinMessage(msg.id);
      } else {
        await pinMessage(msg.id);
      }
    } catch {
    }
  }

  const pinLabel = msg.pinned ? "取消 Pin" : "Pin";

  return (
    <div className="mt-1 flex items-center gap-1 opacity-0 transition-opacity group-hover/message:opacity-100">
      <button type="button" onClick={copy} className="rounded border border-border px-2 py-0.5 text-[10px] text-muted hover:text-fg">
        复制
      </button>
      <button type="button" onClick={quote} className="rounded border border-border px-2 py-0.5 text-[10px] text-muted hover:text-fg">
        引用
      </button>
      <button type="button" onClick={regenerate} className="rounded border border-border px-2 py-0.5 text-[10px] text-muted hover:text-fg">
        {label}
      </button>
      <button
        type="button"
        onClick={handlePin}
        className={`rounded border px-2 py-0.5 text-[10px] transition ${
          msg.pinned
            ? "border-amber-500/40 text-amber-400 hover:bg-amber-500/10"
            : "border-border text-muted hover:text-amber-400 hover:border-amber-500/30"
        }`}
      >
        📌 {pinLabel}
      </button>
      {streaming && canCancel && (
        <button
          type="button"
          onClick={() => cancelMessage(msg.id)}
          className="rounded border border-rose-500/30 px-2 py-0.5 text-[10px] text-rose-300 hover:bg-rose-500/10"
        >
          取消
        </button>
      )}
    </div>
  );
}

function StatusBadge({
  streaming,
  text,
}: {
  streaming?: boolean;
  text: string;
}) {
  if (streaming) {
    return <span className="rounded border border-sky-500/30 px-1.5 py-0.5 text-[10px] text-sky-300">生成中</span>;
  }
  if (text.includes("输出达到模型长度上限")) {
    return <span className="rounded border border-amber-500/30 px-1.5 py-0.5 text-[10px] text-amber-300">被截断</span>;
  }
  if (text.includes("Retrying") || text.includes("重试")) {
    return <span className="rounded border border-amber-500/30 px-1.5 py-0.5 text-[10px] text-amber-300">已重试</span>;
  }
  if (isProblemText(text)) {
    return <span className="rounded border border-rose-500/30 px-1.5 py-0.5 text-[10px] text-rose-300">失败</span>;
  }
  return <span className="rounded border border-emerald-500/25 px-1.5 py-0.5 text-[10px] text-emerald-300">完成</span>;
}

export function MessageBubble({ msg, streaming, onEditArtifact }: Props) {
  const isUser = msg.sender_type === "user";
  const time = new Date(msg.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const agents = useChatStore((s) => s.agents);
  const conversations = useChatStore((s) => s.conversations);
  const currentConvId = useChatStore((s) => s.currentConvId);
  const currentConv = conversations.find((c) => c.id === currentConvId);
  const isGroup = currentConv?.type === "group";
  const text = textOf(msg);

  const agent = agents.find((a) => a.id === msg.sender_id);
  const agentName = agent?.name ?? "agent";
  const agentAvatar = agent?.avatar ?? null;

  if (isUser) {
    return (
      <div className="group/message flex animate-fade-in justify-end">
        <div className="flex max-w-[min(78%,56rem)] flex-col items-end">
          <div className="w-fit rounded-2xl rounded-br-md bg-user px-4 py-2.5 text-sm leading-relaxed text-white shadow-sm break-words">
            <ContentRenderer
              content={msg.content}
              artifactId={msg.artifact_id}
              onEditArtifact={onEditArtifact}
            />
          </div>
          <div className="mt-1 flex items-center gap-2 px-1 text-[10.5px] text-muted">
            <span>{time}</span>
            <span>已发送</span>
          </div>
          <MessageActions msg={msg} streaming={streaming} canCancel={false} />
        </div>
      </div>
    );
  }

  const color = getAgentColor(msg.sender_id);

  return (
    <div className="group/message flex animate-fade-in items-start gap-2.5">
      <div
        className={`mt-0.5 flex h-9 w-9 shrink-0 select-none items-center justify-center rounded-xl ${color.avatar} text-base`}
        title={agentName}
      >
        {agentAvatar || agentName.charAt(0).toUpperCase()}
      </div>

      <div className="min-w-0 max-w-[min(72%,56rem)]">
        <div className="mb-1 flex items-center gap-2 pl-0.5">
          {isGroup && (
            <span className={`max-w-[20ch] truncate text-xs font-semibold ${color.text}`}>
              {agentName}
            </span>
          )}
          <span className="text-[10px] text-muted/60">{time}</span>
          <StatusBadge streaming={streaming} text={text} />
          {msg.pinned && (
            <span className="inline-flex items-center gap-0.5 rounded border border-amber-500/30 bg-amber-500/10 px-1 py-0.5 text-[10px] text-amber-400">
              📌 已 Pin
            </span>
          )}
        </div>

        <div
          className={`w-fit rounded-2xl rounded-tl-sm border px-4 py-2.5 text-sm leading-relaxed shadow-sm break-words ${color.bg} ${color.border}`}
        >
          <ContentRenderer
            content={msg.content}
            artifactId={msg.artifact_id}
            onEditArtifact={onEditArtifact}
          />
          {streaming && msg.content.type === "text" && (
            <span className="ml-1 inline-block animate-blink text-fg/70">▌</span>
          )}
        </div>
        <MessageActions msg={msg} streaming={streaming} canCancel />
      </div>
    </div>
  );
}
