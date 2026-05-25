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

function findMentionAtCursor(
  text: string,
  cursorPos: number,
): { start: number; query: string } | null {
  const beforeCursor = text.slice(0, cursorPos);
  const atIndex = beforeCursor.lastIndexOf("@");
  if (atIndex < 0) return null;

  const afterAt = beforeCursor.slice(atIndex + 1);
  if (afterAt.includes(" ")) return null;

  return { start: atIndex, query: afterAt };
}

function syncMentionsFromText(
  text: string,
  agentsByName: Map<string, Agent>,
): Map<string, Agent> {
  const result = new Map<string, Agent>();
  const mentionRegex = /@([^\s，,。；;：:]+)/g;
  let match;
  while ((match = mentionRegex.exec(text)) !== null) {
    const mentionedName = match[1];
    for (const [agentName, agent] of agentsByName) {
      const normalizedAgentName = agentName.toLowerCase();
      const normalizedMention = mentionedName.toLowerCase();
      if (
        normalizedAgentName.startsWith(normalizedMention) ||
        agent.id.toLowerCase().includes(normalizedMention) ||
        normalizedMention.includes(normalizedAgentName)
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

  const currentConv: Conversation | undefined = conversations.find(
    (c) => c.id === currentConvId,
  );
  const isGroup = currentConv?.type === "group";

  const memberAgents: Agent[] = (currentConv?.members ?? [])
    .filter((m) => m.member_type === "agent")
    .map((m) => agents.get(m.member_id))
    .filter((a): a is Agent => a != null);

  // Listen for code-to-chat events from PreviewCard / CodeBlock
  useEffect(() => {
    function handler(e: Event) {
      const detail = (e as CustomEvent<PendingCode>).detail;
      setPendingCode({
        code: detail.code,
        title: detail.title,
      });
      // Focus the composer and show a hint
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
      const prefix = `> ${quoted.slice(0, 500).replace(/\n/g, "\n> ")}\n\n`;
      setText((prev) => `${prefix}${prev}`);
      textRef.current?.focus();
    }
    window.addEventListener("agenthub:quote-message", handler);
    return () => window.removeEventListener("agenthub:quote-message", handler);
  }, []);

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
    const cursorPos = cursorRef.current;

    const newMentions = syncMentionsFromText(newText, agentsByName);
    setMentions(newMentions);

    if (isGroup) {
      const found = findMentionAtCursor(newText, cursorPos);
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
      text.slice(mentionStart + mentionQuery!.length + 1);

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

  function closeMention() {
    setMentionQuery(null);
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
      fullText =
        `修改以下代码（${pendingCode.title}）：\n\`\`\`\n${pendingCode.code}\n\`\`\`\n\n${fullText}`;
    }
    send(fullText, Array.from(mentions.keys()));
    setText("");
    setMentions(new Map());
    setPendingCode(null);
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (mentionQuery !== null) {
      if (
        e.key === "ArrowUp" ||
        e.key === "ArrowDown" ||
        e.key === "Enter" ||
        e.key === "Tab" ||
        e.key === "Escape"
      ) {
        e.preventDefault();
        return;
      }
      return;
    }

    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      doSend();
    }
  }

  const clearPendingCode = useCallback(() => setPendingCode(null), []);

  return (
    <div className="border-t border-border bg-panel p-3 shrink-0 relative">
      {isGroup && (
        <MentionPopover
          open={mentionQuery !== null}
          filter={mentionQuery ?? ""}
          agents={memberAgents}
          onSelect={handleMentionSelect}
          onClose={closeMention}
        />
      )}

      {/* Pending code context chip */}
      {pendingCode && (
        <div className="flex items-center gap-2 mb-2 px-2 py-1.5 rounded-md bg-sky-500/10 border border-sky-500/20">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-sky-400 shrink-0">
            <polyline points="16 18 22 12 16 6" /><polyline points="8 6 2 12 8 18" />
          </svg>
          <span className="text-[11px] text-sky-300 truncate flex-1 min-w-0">
            代码：{pendingCode.title}
          </span>
          <span className="text-[10px] text-muted/60">将在发送时附加上下文</span>
          <button
            type="button"
            onClick={clearPendingCode}
            className="text-muted hover:text-fg transition-colors shrink-0"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      )}

      <div className="flex gap-2 items-end">
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
                ? "描述你要如何修改这段代码…"
                : isGroup
                  ? "输入消息，使用 @ 提及 Agent（Enter 发送）"
                  : "输入消息，Enter 发送（Shift+Enter 换行）"
          }
          className="flex-1 resize-none bg-bg border border-border rounded-md px-3 py-2 text-sm text-fg outline-none focus:border-accent min-h-[40px] max-h-32"
          rows={1}
          disabled={!currentConvId}
        />
        {streaming ? (
          <button
            type="button"
            onClick={cancel}
            className="px-4 py-2 rounded-md text-sm bg-rose-700 hover:bg-rose-600 text-white transition shrink-0"
            title={
              streamingCount > 1
                ? `取消全部 ${streamingCount} 条流式回复`
                : "取消当前回复"
            }
          >
            {streamingCount > 1 ? `取消 (${streamingCount})` : "取消"}
          </button>
        ) : (
          <button
            type="button"
            onClick={doSend}
            disabled={!canSend}
            className="px-4 py-2 rounded-md text-sm bg-accent hover:bg-accent-hover disabled:bg-border disabled:text-muted text-white transition shrink-0"
          >
            发送
          </button>
        )}
      </div>
    </div>
  );
}
