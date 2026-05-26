import { useState } from "react";
import { useChatStore } from "../stores/useChatStore";
import type { Agent, Conversation } from "../types";

interface Props {
  conversations: Conversation[];
  currentId: string | null;
  onNewAgent?: () => void;
}

type ViewTab = "agents" | "chats";

export function ConversationListPanel({ conversations = [], currentId, onNewAgent }: Props) {
  const [tab, setTab] = useState<ViewTab>("agents");
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [groupMode, setGroupMode] = useState(false);
  const [selectedAgents, setSelectedAgents] = useState<Set<string>>(new Set());

  const agents = useChatStore((s) => s.agents);
  const selectConversation = useChatStore((s) => s.selectConversation);
  const removeConversation = useChatStore((s) => s.removeConversation);
  const createAndSelect = useChatStore((s) => s.createAndSelect);
  const startAgentChat = useChatStore((s) => s.startAgentChat);

  async function handleDelete(e: React.MouseEvent, convId: string) {
    e.stopPropagation();
    if (confirmDelete === convId) {
      await removeConversation(convId);
      setConfirmDelete(null);
      setGroupMode(false);
      setSelectedAgents(new Set());
    } else {
      setConfirmDelete(convId);
    }
  }

  function toggleAgentSelection(agentId: string) {
    setSelectedAgents((prev) => {
      const next = new Set(prev);
      if (next.has(agentId)) next.delete(agentId);
      else next.add(agentId);
      return next;
    });
  }

  async function handleStartSingleChat(agentId: string) {
    await startAgentChat(agentId);
    setTab("chats");
  }

  async function handleCreateGroup() {
    if (selectedAgents.size === 0) return;
    const agentIds = Array.from(selectedAgents);
    await createAndSelect({
      title: `群聊 (${agentIds.length} 个 Agent)`,
      type: "group",
      agent_ids: agentIds,
    });
    setGroupMode(false);
    setSelectedAgents(new Set());
    setTab("chats");
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-3 py-2 border-b border-border shrink-0">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted">
            AGENT CONTACTS
          </h2>
          {onNewAgent && (
            <button
              type="button"
              onClick={onNewAgent}
              className="text-[11px] text-accent hover:text-accent/80 transition-colors"
            >
              New Agent
            </button>
          )}
        </div>

        {/* Tab 切换 */}
        <div className="flex gap-1 bg-bg rounded-lg p-0.5">
          <button
            type="button"
            onClick={() => { setTab("agents"); setGroupMode(false); setSelectedAgents(new Set()); }}
            className={`flex-1 rounded-md px-2 py-1 text-[11px] font-medium transition ${
              tab === "agents" ? "bg-panel text-fg shadow-sm" : "text-muted hover:text-fg"
            }`}
          >
            Agents ({agents.length})
          </button>
          <button
            type="button"
            onClick={() => { setTab("chats"); setGroupMode(false); setSelectedAgents(new Set()); }}
            className={`flex-1 rounded-md px-2 py-1 text-[11px] font-medium transition ${
              tab === "chats" ? "bg-panel text-fg shadow-sm" : "text-muted hover:text-fg"
            }`}
          >
            Chats ({conversations.length})
          </button>
        </div>
      </div>

      {/* Agent 群聊操作栏 */}
      {tab === "agents" && groupMode && selectedAgents.size > 0 && (
        <div className="mx-3 mt-2 p-2 rounded-lg bg-accent/10 border border-accent/30 flex items-center justify-between">
          <span className="text-[11px] text-accent">已选 {selectedAgents.size} 个 Agent</span>
          <div className="flex gap-1.5">
            <button
              type="button"
              onClick={() => { setGroupMode(false); setSelectedAgents(new Set()); }}
              className="rounded-md px-2 py-1 text-[10px] text-muted hover:text-fg border border-border"
            >
              取消
            </button>
            <button
              type="button"
              onClick={handleCreateGroup}
              className="rounded-md bg-accent px-2 py-1 text-[10px] font-medium text-white hover:bg-accent/90"
            >
              建立群聊
            </button>
          </div>
        </div>
      )}

      {/* Agent 群聊模式提示 */}
      {tab === "agents" && !groupMode && (
        <div className="mx-3 mt-2 flex gap-1.5">
          <button
            type="button"
            onClick={() => setGroupMode(true)}
            className="flex-1 rounded-md border border-border px-2 py-1.5 text-[10px] text-muted hover:text-fg hover:border-accent/40 transition-colors"
          >
            ☰ 多选建群聊
          </button>
          <button
            type="button"
            onClick={() => createAndSelect({ title: "New Chat" })}
            className="flex-1 rounded-md border border-border px-2 py-1.5 text-[10px] text-muted hover:text-fg hover:border-accent/40 transition-colors"
          >
            + 新对话
          </button>
        </div>
      )}

      {/* ===== Agent 列表 ===== */}
      {tab === "agents" && (
        <ul className="flex-1 overflow-y-auto p-2 space-y-1.5">
          {agents.map((agent) => {
            const isSelected = selectedAgents.has(agent.id);
            return (
              <li key={agent.id}>
                <div
                  className={`relative w-full p-3 rounded-lg border transition cursor-pointer group ${
                    isSelected
                      ? "border-accent bg-accent/10"
                      : "border-border hover:border-accent/50 bg-panel/50"
                  }`}
                  onClick={() => groupMode ? toggleAgentSelection(agent.id) : void handleStartSingleChat(agent.id)}
                >
                  {/* 头像 + 名称行 */}
                  <div className="flex items-center gap-2.5">
                    <span className="shrink-0 w-8 h-8 rounded-lg bg-bg flex items-center justify-center text-base leading-none border border-border">
                      {agent.avatar || "🤖"}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="font-semibold text-sm text-fg truncate">{agent.name}</div>
                      <div className="text-[10.5px] text-muted truncate mt-0.5">
                        {agent.adapter_type} · {agent.model || "—"}
                      </div>
                    </div>

                    {!groupMode && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onNewAgent?.();
                        }}
                        className="shrink-0 rounded-md border border-border px-2 py-0.5 text-[10px] text-muted opacity-0 group-hover:opacity-100 hover:text-fg hover:border-accent/40 transition-all"
                      >
                        Edit
                      </button>
                    )}

                    {groupMode && (
                      <span className={`shrink-0 w-5 h-5 rounded-md border flex items-center justify-center text-[10px] font-bold transition ${
                        isSelected ? "bg-accent border-accent text-white" : "border-border text-muted"
                      }`}>
                        {isSelected ? "✓" : ""}
                      </span>
                    )}
                  </div>

                  {/* 能力标签 */}
                  <div className="flex flex-wrap gap-1 mt-2">
                    {agent.capabilities.slice(0, 6).map((cap) => (
                      <span
                        key={cap}
                        className="inline-block rounded-md border border-border bg-bg px-1.5 py-0.5 text-[10px] text-muted leading-tight"
                      >
                        {cap}
                      </span>
                    ))}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {/* ===== 对话列表 ===== */}
      {tab === "chats" && (
        <ul className="flex-1 overflow-y-auto p-2 space-y-1">
          {conversations.map((conv) => (
            <li key={conv.id}>
              <button
                type="button"
                onClick={() => selectConversation(conv.id)}
                className={`group relative w-full text-left p-3 rounded-md border transition ${
                  currentId === conv.id
                    ? "border-accent bg-accent/10"
                    : "border-border hover:border-accent/60"
                }`}
              >
                <div className="font-medium text-sm text-fg truncate pr-8">
                  {conv.title}
                </div>
                {conv.last_message && (
                  <div className="text-xs text-muted truncate mt-1">
                    {conv.last_message}
                  </div>
                )}
                <div className="text-[10.5px] text-muted mt-1 truncate">
                  {conv.type}
                  {" · "}
                  {conv.member_count} 成员
                  {" · "}
                  {conv.id.slice(0, 16)}
                </div>

                {/* 删除按钮 */}
                <button
                  type="button"
                  onClick={(e) => handleDelete(e, conv.id)}
                  className={`absolute top-2 right-2 p-1 rounded-md text-[10px] font-bold opacity-0 group-hover:opacity-100 transition-opacity ${
                    confirmDelete === conv.id
                      ? "bg-red-500 text-white px-2 py-0.5 opacity-100"
                      : "bg-red-50 text-red-400 hover:bg-red-100 hover:text-red-600"
                  }`}
                  title={confirmDelete === conv.id ? "确认删除？" : "删除对话"}
                >
                  {confirmDelete === conv.id ? "✓ 确认" : "✕"}
                </button>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
