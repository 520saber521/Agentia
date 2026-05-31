import { useCallback, useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";

import { fetchAgents } from "../api/client";
import { useChatStore } from "../stores/useChatStore";
import type { Agent, Conversation } from "../types";
import { MentionPopover } from "./MentionPopover";

interface PendingCode {
  code: string;
  title: string;
}

function findMentionAtCursor(text: string, cursorPos: number): { start: number; query: string } | null {
  const beforeCursor = text.slice(0, cursorPos);
  const atIndex = beforeCursor.lastIndexOf("@");
  if (atIndex < 0) return null;
  const afterAt = beforeCursor.slice(atIndex + 1);
  if (afterAt.includes(" ")) return null;
  return { start: atIndex, query: afterAt };
}

function syncMentionsFromText(text: string, agentsByName: Map<string, Agent>): Map<string, Agent> {
  const result = new Map<string, Agent>();
  const mentionRegex = /@([^\s,.;:，。；：]+)/g;
  let match: RegExpExecArray | null;
  while ((match = mentionRegex.exec(text)) !== null) {
    const mentionedName = match[1].toLowerCase();
    for (const [agentName, agent] of agentsByName) {
      const normalizedName = agentName.toLowerCase();
      if (
        normalizedName.startsWith(mentionedName) ||
        agent.id.toLowerCase().includes(mentionedName) ||
        mentionedName.includes(normalizedName)
      ) {
        result.set(agent.id, agent);
        break;
      }
    }
  }
  return result;
}

export function Composer() {
  const [text, setText] = useState("");
  const [mentions, setMentions] = useState<Map<string, Agent>>(new Map());
  const [agents, setAgents] = useState<Map<string, Agent>>(new Map());
  const [agentsByName, setAgentsByName] = useState<Map<string, Agent>>(new Map());
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  const [mentionStart, setMentionStart] = useState(0);
  const [pendingCode, setPendingCode] = useState<PendingCode | null>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const cursorRef = useRef(0);

  const status = useChatStore((s) => s.status);
  const streamingCount = useChatStore((s) => s.streamingMessageIds.length);
  const streaming = streamingCount > 0;
  const send = useChatStore((s) => s.sendText);
  const cancel = useChatStore((s) => s.cancelAll);
  const currentConvId = useChatStore((s) => s.currentConvId);
  const conversations = useChatStore((s) => s.conversations);

  const currentConv: Conversation | undefined = conversations.find((c) => c.id === currentConvId);
  const isGroup = currentConv?.type === "group";

  const memberAgents: Agent[] = (currentConv?.members ?? [])
    .filter((m) => m.member_type === "agent")
    .map((m) => agents.get(m.member_id))
    .filter((a): a is Agent => a != null);

  useEffect(() => {
    function handler(e: Event) {
      const detail = (e as CustomEvent<PendingCode>).detail;
      setPendingCode({ code: detail.code, title: detail.title });
      textRef.current?.focus();
    }
    window.addEventListener("agenthub:code-to-chat", handler);
    return () => window.removeEventListener("agenthub:code-to-chat", handler);
  }, []);

  useEffect(() => {
    function handler(e: Event) {
      const detail = (e as CustomEvent<{ sender?: string; text?: string }>).detail;
      const quoted = (detail?.text ?? "").trim();
      if (!quoted) return;
      const senderAgent = detail.sender ? agents.get(detail.sender) : undefined;
      const mention = senderAgent ? `@${senderAgent.name} ` : "";
      const prefix = `> ${quoted.slice(0, 500).replace(/\n/g, "\n> ")}\n\n`;
      setText((prev) => `${mention}${prefix}${prev}`);
      textRef.current?.focus();
    }
    window.addEventListener("agenthub:quote-message", handler);
    return () => window.removeEventListener("agenthub:quote-message", handler);
  }, [agents]);

  useEffect(() => {
    let cancelled = false;
    fetchAgents()
      .then((list) => {
        if (cancelled) return;
        const byId = new Map<string, Agent>();
        const byName = new Map<string, Agent>();
        for (const a of list) {
          byId.set(a.id, a);
          byName.set(a.name, a);
          byName.set(a.id, a);
          byName.set(a.name.replace(/\s+/g, ""), a);
        }
        setAgents(byId);
        setAgentsByName(byName);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  function onTextChange(newText: string) {
    setText(newText);
    setMentions(syncMentionsFromText(newText, agentsByName));

    if (isGroup) {
      const found = findMentionAtCursor(newText, cursorRef.current);
      if (found) {
        setMentionQuery(found.query);
        setMentionStart(found.start);
      } else {
        setMentionQuery(null);
      }
    } else {
      setMentionQuery(null);
    }
  }

  function handleMentionSelect(agent: Agent) {
    const newText =
      text.slice(0, mentionStart) +
      `@${agent.name} ` +
      text.slice(mentionStart + (mentionQuery?.length ?? 0) + 1);
    setText(newText);
    setMentionQuery(null);
    setMentions(new Map(mentions).set(agent.id, agent));

    const ta = textRef.current;
    if (ta) {
      const pos = mentionStart + agent.name.length + 2;
      ta.focus();
      ta.setSelectionRange(pos, pos);
      cursorRef.current = pos;
    }
  }

  const canSend =
    status === "connected" &&
    !streaming &&
    currentConvId !== null &&
    text.trim().length > 0;

  function doSend() {
    if (!canSend) return;
    let fullText = text.trim();
    if (pendingCode) {
      fullText = `请修改以下代码（${pendingCode.title}）：\n\`\`\`\n${pendingCode.code}\n\`\`\`\n\n${fullText}`;
    }
    send(fullText, Array.from(mentions.keys()));
    setText("");
    setMentions(new Map());
    setPendingCode(null);
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (mentionQuery !== null) {
      if (["ArrowUp", "ArrowDown", "Enter", "Tab", "Escape"].includes(e.key)) {
        e.preventDefault();
      }
      return;
    }

    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      doSend();
    }
  }

  const clearPendingCode = useCallback(() => setPendingCode(null), []);

  function fillLoginDemoPrompt() {
    const orchestrator = memberAgents.find((a) => a.id === "agent_orchestrator");
    setText("@Orchestrator 帮我实现一个登录页，包括前端页面、后端接口、数据库表设计和测试建议");
    setMentions(orchestrator ? new Map([[orchestrator.id, orchestrator]]) : new Map());
    textRef.current?.focus();
  }

  return (
    <div className="relative shrink-0 border-t border-border bg-panel p-3">
      {isGroup && (
        <MentionPopover
          open={mentionQuery !== null}
          filter={mentionQuery ?? ""}
          agents={memberAgents}
          onSelect={handleMentionSelect}
          onClose={() => setMentionQuery(null)}
        />
      )}

      {pendingCode && (
        <div className="mb-2 flex items-center gap-2 rounded-md border border-info/20 bg-info/10 px-2 py-1.5">
          <span className="min-w-0 flex-1 truncate text-2xs text-info/80">
            代码上下文：{pendingCode.title}
          </span>
          <span className="text-2xs text-muted/60">发送时会附加到消息中</span>
          <button type="button" onClick={clearPendingCode} aria-label="清除代码上下文" className="shrink-0 text-muted transition-colors hover:text-fg cursor-pointer">
            ×
          </button>
        </div>
      )}

      {isGroup && (
        <div className="mb-2 flex items-center justify-between gap-2">
          <button
            type="button"
            onClick={fillLoginDemoPrompt}
            className="rounded-md border border-accent/50 px-2.5 py-1.5 text-xs text-accent transition hover:bg-accent/10"
          >
            登录页协作 Demo
          </button>
          <span className="truncate text-2xs text-muted">
            Orchestrator 会分派给 Frontend / Backend / Database / Test Agent
          </span>
        </div>
      )}

      <div className="flex items-end gap-2">
        <textarea
          ref={textRef}
          value={text}
          onChange={(e) => {
            cursorRef.current = e.target.selectionStart;
            onTextChange(e.target.value);
          }}
          onKeyDown={onKey}
          placeholder={
            !currentConvId
              ? "请先在左侧选择一个会话"
              : pendingCode
                ? "描述你要如何修改这段代码..."
                : isGroup
                  ? "输入消息，使用 @ 提及 Agent，Enter 发送"
                  : "输入消息，Enter 发送，Shift+Enter 换行"
          }
          className="max-h-32 min-h-[40px] flex-1 resize-none rounded-md border border-border bg-bg px-3 py-2 text-sm text-fg focus:border-accent focus:outline-none"
          rows={1}
          disabled={!currentConvId}
        />
        {streaming ? (
          <button
            type="button"
            onClick={cancel}
            className="shrink-0 rounded-md bg-rose-700 px-4 py-2 text-sm text-white transition hover:bg-rose-600"
            title={streamingCount > 1 ? `取消全部 ${streamingCount} 条流式回复` : "取消当前回复"}
          >
            {streamingCount > 1 ? `取消 (${streamingCount})` : "取消"}
          </button>
        ) : (
          <>
            <button
              type="button"
              onClick={() => send("部署")}
              disabled={!currentConvId}
              className="shrink-0 rounded-md border border-border bg-panel px-3 py-2 text-sm text-muted transition hover:border-accent hover:text-accent disabled:opacity-50"
              title="构建并预览当前项目"
            >
              部署
            </button>
            <button
              type="button"
              onClick={doSend}
              disabled={!canSend}
              className="shrink-0 rounded-md bg-accent px-4 py-2 text-sm text-white transition hover:bg-accent-hover disabled:bg-border disabled:text-muted"
            >
              发送
            </button>
          </>
        )}
      </div>
    </div>
  );
}
