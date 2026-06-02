import { useEffect, useRef } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";

import { useChatStore } from "../stores/useChatStore";
import { MessageBubble } from "./MessageBubble";
import { CollaborationProgressCard } from "./CollaborationProgressCard";
import { AgentGraph } from "./AgentGraph";

interface Props {
  onEditArtifact?: (artifactId: string) => void;
}

export function MessagePanel({ onEditArtifact }: Props) {
  const messages = useChatStore((s) => s.messages);
  const streamingIds = useChatStore((s) => s.streamingMessageIds);
  const agentTyping = useChatStore((s) => s.agentTyping);
  const tasks = useChatStore((s) => s.tasks);
  const currentConvId = useChatStore((s) => s.currentConvId);
  const conversations = useChatStore((s) => s.conversations);
  const agents = useChatStore((s) => s.agents);
  const scrollRef = useRef<HTMLDivElement>(null);
  const shouldStickToBottomRef = useRef(true);
  const scrollRafRef = useRef<number | null>(null);
  const prefersReducedMotion = useReducedMotion();

  const currentTasks = currentConvId
    ? Object.values(tasks ?? {})
        .filter((t) => t.conversation_id === currentConvId)
        .sort((a, b) => a.created_at - b.created_at)
    : [];

  const currentConv = conversations.find((c) => c.id === currentConvId);
  const memberAgents = (currentConv?.members ?? [])
    .filter((m) => m.member_type === "agent")
    .map((m) => agents.find((a) => a.id === m.member_id))
    .filter((a): a is NonNullable<typeof a> => a != null);
  const showGraph = Boolean(currentConv && memberAgents.length > 0);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !shouldStickToBottomRef.current) return;

    // Defer scroll to next animation frame to avoid layout thrash
    if (scrollRafRef.current !== null) {
      cancelAnimationFrame(scrollRafRef.current);
    }
    scrollRafRef.current = requestAnimationFrame(() => {
      scrollRafRef.current = null;
      if (el && shouldStickToBottomRef.current) {
        el.scrollTop = el.scrollHeight;
      }
    });

    return () => {
      if (scrollRafRef.current !== null) {
        cancelAnimationFrame(scrollRafRef.current);
        scrollRafRef.current = null;
      }
    };
  }, [messages, agentTyping, tasks]);

  function handleScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    shouldStickToBottomRef.current = distanceToBottom < 80;
  }

  useEffect(() => {
    shouldStickToBottomRef.current = true;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [currentConvId]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {currentConv && (
        <div className="shrink-0 border-b border-border bg-panel/70 px-5 py-2">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-fg">
                {currentConv.title}
              </div>
              <div className="text-2xs text-muted">
                {currentConv.type === "group" ? "群聊协作" : "单聊"} · {currentConv.members.length} 成员
              </div>
            </div>
            <div className="flex min-w-0 items-center gap-1.5 overflow-x-auto">
              {memberAgents.map((agent) => (
                <div
                  key={agent.id}
                  className="flex shrink-0 items-center gap-1.5 rounded-md border border-border bg-bg px-2 py-1"
                  title={`${agent.name} · ${agent.capabilities.join(", ")}`}
                >
                  <span className="grid h-5 w-5 place-items-center rounded bg-accent/15 text-3xs text-accent">
                    {agent.avatar || agent.name.charAt(0).toUpperCase()}
                  </span>
                  <span className="max-w-[10rem] truncate text-xs text-fg">
                    {agent.name}
                  </span>
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${
                      agent.api_key_configured || agent.adapter_type === "mock"
                        ? "bg-success"
                        : "bg-warning"
                    }`}
                  />
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {showGraph && (
        <div className="shrink-0 border-b border-border bg-bg/80">
          <AgentGraph height={220} />
        </div>
      )}

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="min-h-0 flex-1 space-y-3 overflow-y-auto overscroll-contain p-6"
      >
        {messages.length === 0 && currentTasks.length === 0 && (
          <div className="mt-16 text-center text-xs text-muted">
            对话还是空的，在下方输入消息即可开始。
          </div>
        )}
        <AnimatePresence initial={false}>
          {messages.map((m) => (
            <motion.div
              key={m.id}
              initial={prefersReducedMotion ? undefined : { opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.15, ease: "easeOut" }}
            >
              <MessageBubble
                msg={m}
                streaming={streamingIds.includes(m.id)}
                onEditArtifact={onEditArtifact}
              />
            </motion.div>
          ))}
        </AnimatePresence>
        {currentTasks.length > 0 && (
          <>
            <CollaborationProgressCard tasks={currentTasks} />
          </>
        )}
        {agentTyping && (
          <div className="animate-fade-in px-3 text-xs text-muted inline-flex items-center gap-1.5">
            Agent 正在思考
            <span className="inline-flex items-center gap-0.5">
              <span className="inline-block h-1 w-1 rounded-full bg-accent animate-dot-pulse" />
              <span className="inline-block h-1 w-1 rounded-full bg-accent animate-dot-pulse" style={{ animationDelay: "0.16s" }} />
              <span className="inline-block h-1 w-1 rounded-full bg-accent animate-dot-pulse" style={{ animationDelay: "0.32s" }} />
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
