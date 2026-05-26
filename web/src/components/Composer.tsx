import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";

import { fetchAgents } from "../api/client";
import { useChatStore } from "../stores/useChatStore";
import type { Agent, Conversation } from "../types";
import { MentionPopover } from "./MentionPopover";

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
    send(text.trim(), Array.from(mentions.keys()));
    setText("");
    setMentions(new Map());
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
            currentConvId
              ? isGroup
                ? "输入消息，使用 @ 提及 Agent（Enter 发送）"
                : "输入消息，Enter 发送（Shift+Enter 换行）"
              : "请先在左侧选择一个会话"
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
