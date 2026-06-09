import { useEffect, useMemo, useRef, useState } from "react";

import { fetchConversationArtifacts } from "../api/client";
import { useChatStore } from "../stores/useChatStore";
import type { Agent, Artifact, Message, MessageContent } from "../types";
import { ContentRenderer } from "./ContentRenderer";

interface Props {
  onClose: () => void;
  onEditArtifact?: (artifactId: string) => void;
}

interface AgentWithOutputs {
  agent: Agent;
  artifacts: Artifact[];
  messages: Message[];
}

function formatTime(ts: number): string {
  return new Date(ts).toLocaleString([], {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function artifactTitle(artifact: Artifact): string {
  return artifact.file_name || artifact.title || artifact.kind;
}

function agentTopic(agent: Agent): string {
  const name = agent.name.toLowerCase();
  const capabilities = agent.capabilities.join(" ").toLowerCase();
  const combined = `${name} ${capabilities}`;

  if (combined.includes("database") || combined.includes("sql") || combined.includes("data")) {
    return `${agent.name}：数据库：设计数据模型与表结构`;
  }
  if (combined.includes("frontend") || combined.includes("react") || combined.includes("ui")) {
    return `${agent.name}：前端：实现页面与交互体验`;
  }
  if (combined.includes("backend") || combined.includes("api") || combined.includes("service")) {
    return `${agent.name}：后端：设计接口与业务逻辑`;
  }
  if (combined.includes("product") || combined.includes("prd") || combined.includes("需求")) {
    return `${agent.name}：产品：梳理需求与功能规划`;
  }
  if (combined.includes("test") || combined.includes("docs") || combined.includes("doc")) {
    return `${agent.name}：测试：制定测试用例与验收标准`;
  }
  if (combined.includes("orchestrator") || combined.includes("task") || combined.includes("management")) {
    return `${agent.name}：编排：拆解任务与协调协作流程`;
  }
  return `${agent.name}：${agent.capabilities.slice(0, 2).join("、") || agent.adapter_type}`;
}

function messageTitle(message: Message): string {
  if (message.content.type === "text") return message.content.text.slice(0, 80) || "文本回复";
  if ("title" in message.content && typeof message.content.title === "string") return message.content.title;
  if ("fileName" in message.content && typeof message.content.fileName === "string") return message.content.fileName;
  return message.content.type;
}

function artifactToContent(artifact: Artifact): MessageContent {
  const base = {
    artifact_id: artifact.id,
    title: artifact.title,
    mimeType: artifact.mime_type,
    fileSize: artifact.file_size,
    url: artifact.url,
    previewUrl: artifact.preview_url,
    version: artifact.version,
  };

  if (artifact.kind === "preview") {
    return { type: "preview", ...base };
  }

  if (artifact.kind === "file") {
    return {
      type: "file",
      ...base,
      fileName: artifact.file_name || artifact.title,
    };
  }

  if (artifact.kind === "diff") {
    return {
      type: "diff",
      ...base,
      fileName: artifact.file_name || artifact.title,
      summary: typeof artifact.meta.diff_summary === "string" ? artifact.meta.diff_summary : "产物版本变更",
      base_artifact_id: artifact.parent_id ?? undefined,
      applied_artifact_id: artifact.id,
    };
  }

  const language = typeof artifact.meta.language === "string" ? artifact.meta.language : "plaintext";
  return {
    type: "code",
    ...base,
    fileName: artifact.file_name || artifact.title,
    language,
  };
}

function getMessageArtifactId(message: Message): string | null {
  if (message.artifact_id) return message.artifact_id;
  if ("artifact_id" in message.content && typeof message.content.artifact_id === "string") {
    return message.content.artifact_id;
  }
  if (message.content.type === "diff" && typeof message.content.applied_artifact_id === "string") {
    return message.content.applied_artifact_id;
  }
  return null;
}

function getAgentBadge(agent: Agent, index: number): string {
  return agent.avatar || String(index + 1).padStart(2, "0");
}

function EmptyWorkspace({ agentName }: { agentName?: string }) {
  return (
    <div className="flex h-full min-h-[28rem] flex-col items-center justify-center text-center">
      <div className="mb-5 grid h-16 w-16 place-items-center rounded-full border border-slate-200 bg-slate-50 text-3xl text-slate-300">
        ∴
      </div>
      <h3 className="text-2xl font-bold tracking-tight text-slate-950">
        等待 Agent 工作区内容
      </h3>
      <p className="mt-3 max-w-md text-sm leading-6 text-slate-500">
        {agentName
          ? `${agentName} 生成的产物、任务结果和工具输出会显示在这里。`
          : "该对话中的 Agent 生成产物后，会自动归档到这个工作区。"}
      </p>
    </div>
  );
}

export function AgentWorkspacePage({ onClose, onEditArtifact }: Props) {
  const currentConvId = useChatStore((s) => s.currentConvId);
  const conversations = useChatStore((s) => s.conversations);
  const agents = useChatStore((s) => s.agents);
  const messages = useChatStore((s) => s.messages);
  const streamingMessageIds = useChatStore((s) => s.streamingMessageIds);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [loadingArtifacts, setLoadingArtifacts] = useState(false);
  const [artifactError, setArtifactError] = useState<string | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(null);
  const [selectedMessageId, setSelectedMessageId] = useState<string | null>(null);
  const [showArtifactPanel, setShowArtifactPanel] = useState(false);
  const artifactPanelRef = useRef<HTMLDivElement>(null);

  const currentConv = conversations.find((conversation) => conversation.id === currentConvId);

  useEffect(() => {
    if (!showArtifactPanel) return;
    function handleClick(e: MouseEvent) {
      if (artifactPanelRef.current && !artifactPanelRef.current.contains(e.target as Node)) {
        setShowArtifactPanel(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [showArtifactPanel]);

  useEffect(() => {
    if (!currentConvId) return;
    let cancelled = false;
    setLoadingArtifacts(true);
    setArtifactError(null);
    fetchConversationArtifacts(currentConvId, { limit: 200 })
      .then((items) => {
        if (!cancelled) setArtifacts(items);
      })
      .catch(() => {
        if (!cancelled) {
          setArtifactError("产物列表加载失败");
          setArtifacts([]);
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingArtifacts(false);
      });
    return () => {
      cancelled = true;
    };
  }, [currentConvId, messages.length]);

  const agentOutputs = useMemo<AgentWithOutputs[]>(() => {
    const members = currentConv?.members ?? [];
    const agentMembers = members
      .filter((member) => member.member_type === "agent")
      .map((member) => agents.find((agent) => agent.id === member.member_id))
      .filter((agent): agent is Agent => agent != null);
    const fallbackAgents = agentMembers.length > 0
      ? agentMembers
      : agents.filter((agent) => messages.some((message) => message.sender_id === agent.id));

    return fallbackAgents.map((agent) => {
      const agentMessages = messages
        .filter((message) => message.sender_type === "agent" && message.sender_id === agent.id)
        .sort((a, b) => b.created_at - a.created_at);
      const agentMessageIds = new Set(agentMessages.map((message) => message.id));
      const agentArtifactIds = new Set(
        agentMessages
          .map(getMessageArtifactId)
          .filter((id): id is string => Boolean(id)),
      );
      const agentArtifacts = artifacts
        .filter((artifact) => (
          artifact.created_by === agent.id ||
          (artifact.source_message_id != null && agentMessageIds.has(artifact.source_message_id)) ||
          agentArtifactIds.has(artifact.id)
        ))
        .sort((a, b) => b.created_at - a.created_at);
      return { agent, artifacts: agentArtifacts, messages: agentMessages };
    });
  }, [agents, artifacts, currentConv?.members, messages]);

  useEffect(() => {
    if (agentOutputs.length === 0) {
      setSelectedAgentId(null);
      return;
    }
    if (!selectedAgentId || !agentOutputs.some((item) => item.agent.id === selectedAgentId)) {
      setSelectedAgentId(agentOutputs[0].agent.id);
    }
  }, [agentOutputs, selectedAgentId]);

  const selectedOutput = agentOutputs.find((item) => item.agent.id === selectedAgentId) ?? null;
  const selectedMessageFromId = selectedOutput?.messages.find((m) => m.id === selectedMessageId) ?? null;
  const selectedArtifact = selectedOutput?.artifacts.find((artifact) => artifact.id === selectedArtifactId) ?? selectedOutput?.artifacts[0] ?? null;
  const selectedMessage = selectedMessageFromId ?? (selectedArtifact ? null : (selectedOutput?.messages[0] ?? null));
  const syncTotal = agentOutputs.length || 1;
  const syncDone = agentOutputs.filter((o) => !streamingMessageIds.includes(o.messages[0]?.id ?? "")).length;

  function handleSelectAgent(agentId: string) {
    setSelectedAgentId(agentId);
    const nextOutput = agentOutputs.find((item) => item.agent.id === agentId);
    setSelectedArtifactId(nextOutput?.artifacts[0]?.id ?? null);
    setSelectedMessageId(null);
    setShowArtifactPanel(false);
  }

  function handleSelectMessage(messageId: string) {
    setSelectedMessageId(messageId);
    setShowArtifactPanel(false);
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-[#f3f2f0] text-slate-950">
      <div className="flex min-h-0 flex-1 flex-col px-3 py-3 md:px-4">
        <header className="mb-3 flex shrink-0 items-center gap-3">
          <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl border-[3px] border-slate-950 text-2xl font-black leading-none">
            A
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="truncate text-2xl font-black tracking-tight">Agentia</h1>
              <span className="truncate text-lg font-semibold text-slate-800">{currentConv?.title ?? "Agent 工作区"}</span>
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs font-semibold text-slate-500">
              <span className="inline-flex items-center gap-2 text-slate-900">
                <span className="h-3 w-3 rounded-full bg-emerald-500" />
                多 Agent 协作 {syncDone}/{syncTotal}
              </span>
              <span className="h-5 w-px bg-slate-300" />
              <span>{agentOutputs.length} 个 Agent · 点击底部卡片选择 Agent，点击归档查看消息</span>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-white/70 text-lg font-bold text-slate-700 shadow-sm transition hover:bg-white hover:text-slate-950"
            aria-label="返回对话"
          >
            ×
          </button>
        </header>

        <main className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-slate-200/80">
          <div className="flex h-11 shrink-0 items-center justify-between border-b border-slate-200 px-4">
            <div className="min-w-0 flex-1 text-center font-mono text-sm font-black tracking-wide">
              {selectedOutput ? selectedOutput.agent.name : "Agent 工作区"}
            </div>
            <div className="relative ml-4 hidden items-center gap-2 text-sm font-medium text-slate-500 md:flex">
              <button
                type="button"
                onClick={() => setShowArtifactPanel((prev) => !prev)}
                className={`flex items-center gap-2 rounded-md px-2 py-1 text-xs transition ${showArtifactPanel ? "bg-slate-100 text-slate-900" : "hover:bg-slate-50 hover:text-slate-700"}`}
              >
                <span className="grid h-5 w-5 place-items-center rounded border border-slate-400 text-[10px]">▤</span>
                {loadingArtifacts ? "同步中" : artifactError ?? "消息归档"}
                {selectedOutput && selectedOutput.messages.length > 0 && (
                  <span className="ml-0.5 grid h-4 min-w-[1rem] place-items-center rounded-full bg-slate-200 px-1 text-[10px] font-bold text-slate-600">
                    {selectedOutput.messages.length}
                  </span>
                )}
              </button>
              {showArtifactPanel && selectedOutput && (
                <div ref={artifactPanelRef} className="absolute right-0 top-full z-30 mt-1 w-80 rounded-xl border border-slate-200 bg-white shadow-xl">
                  <div className="border-b border-slate-100 px-3 py-2">
                    <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wide">
                      {selectedOutput.agent.name} 的消息归档
                    </span>
                  </div>
                  <div className="max-h-72 overflow-y-auto p-1">
                    {selectedOutput.messages.length === 0 ? (
                      <div className="px-3 py-6 text-center text-xs text-slate-400">
                        暂无消息
                      </div>
                    ) : (
                      selectedOutput.messages.map((msg) => {
                        const isActive = msg.id === selectedMessageId;
                        const msgTitle = messageTitle(msg);
                        return (
                          <button
                            key={msg.id}
                            type="button"
                            onClick={() => handleSelectMessage(msg.id)}
                            className={`w-full rounded-lg px-3 py-2.5 text-left transition ${isActive ? "bg-slate-100" : "hover:bg-slate-50"}`}
                          >
                            <div className="flex items-start gap-2.5">
                              <span className={`shrink-0 mt-0.5 grid h-6 w-6 place-items-center rounded border text-[9px] font-bold ${isActive ? "border-slate-950 bg-slate-950 text-white" : "border-slate-300 text-slate-500"}`}>
                                {msg.content.type === "preview" ? "◧" : msg.content.type === "diff" ? "⇄" : msg.content.type === "file" ? "⬇" : msg.content.type === "code" ? "{ }" : "T"}
                              </span>
                              <span className="min-w-0 flex-1">
                                <span className="block truncate text-xs font-bold text-slate-800">
                                  {msgTitle}
                                </span>
                                <span className="block text-[10px] text-slate-400">
                                  {msg.content.type} · {formatTime(msg.created_at)}
                                </span>
                              </span>
                            </div>
                          </button>
                        );
                      })
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-3 md:p-4">
            {!selectedOutput && <EmptyWorkspace />}
            {selectedOutput && !selectedArtifact && !selectedMessage && <EmptyWorkspace agentName={selectedOutput.agent.name} />}
            {selectedOutput && (selectedArtifact || selectedMessage) && (
              <section className="min-h-full min-w-0 rounded-xl border border-slate-200 bg-slate-50/70 p-3">
                {selectedMessageId && selectedMessage ? (
                  /* 从消息归档中选择的消息 — 优先渲染 */
                  <div className="flex min-h-[20rem] flex-col">
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                      <div className="min-w-0">
                        <h2 className="truncate text-lg font-black text-slate-950">{agentTopic(selectedOutput.agent)}</h2>
                        <p className="mt-1 text-xs text-slate-500">Agent 回复 · {messageTitle(selectedMessage)} · {formatTime(selectedMessage.created_at)}</p>
                      </div>
                      <button
                        type="button"
                        onClick={() => { setSelectedMessageId(null); setSelectedArtifactId(selectedOutput.artifacts[0]?.id ?? null); }}
                        className="rounded-full border border-slate-300 bg-white px-3 py-1.5 text-xs font-bold text-slate-600 transition hover:border-slate-950 hover:text-slate-950"
                      >
                        ← 返回产物
                      </button>
                    </div>
                    <div className="min-h-[16rem] overflow-x-auto rounded-xl border border-border bg-panel p-3 text-fg shadow-inner">
                      <ContentRenderer
                        content={selectedMessage.content}
                        artifactId={selectedMessage.artifact_id}
                        onEditArtifact={onEditArtifact}
                        sourceAgentId={selectedOutput.agent.id}
                        sourceAgentName={selectedOutput.agent.name}
                        sourceMessageId={selectedMessage.id}
                        fillHeight
                      />
                    </div>
                  </div>
                ) : selectedArtifact ? (
                  <div className="flex min-h-[20rem] flex-col">
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                      <div className="min-w-0">
                        <h2 className="truncate text-lg font-black text-slate-950">{agentTopic(selectedOutput.agent)}</h2>
                        <p className="mt-1 text-xs text-slate-500">
                          {selectedArtifact.mime_type} · {selectedArtifact.file_size.toLocaleString()} bytes · {formatTime(selectedArtifact.created_at)}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => onEditArtifact?.(selectedArtifact.id)}
                        className="rounded-full border border-slate-300 bg-white px-3 py-1.5 text-xs font-bold text-slate-700 transition hover:border-slate-950 hover:text-slate-950"
                      >
                        打开编辑器
                      </button>
                    </div>

                    {selectedOutput.artifacts.length > 1 && (
                      <div className="mb-3 flex shrink-0 gap-2 overflow-x-auto pb-1">
                        {selectedOutput.artifacts.map((artifact) => (
                          <button
                            key={artifact.id}
                            type="button"
                            onClick={() => setSelectedArtifactId(artifact.id)}
                            className={`shrink-0 rounded-full border px-3 py-1.5 text-xs font-semibold transition ${selectedArtifact.id === artifact.id ? "border-slate-950 bg-slate-950 text-white" : "border-slate-300 bg-white text-slate-600 hover:border-slate-950 hover:text-slate-950"}`}
                          >
                            {artifactTitle(artifact)} · v{artifact.version}
                          </button>
                        ))}
                      </div>
                    )}

                    <div className="min-h-[16rem] overflow-x-auto rounded-xl border border-border bg-panel p-3 text-fg shadow-inner">
                      <ContentRenderer
                        content={artifactToContent(selectedArtifact)}
                        artifactId={selectedArtifact.id}
                        onEditArtifact={onEditArtifact}
                        sourceAgentId={selectedOutput.agent.id}
                        sourceAgentName={selectedOutput.agent.name}
                        sourceMessageId={selectedArtifact.source_message_id ?? undefined}
                        fillHeight
                      />
                    </div>
                  </div>
                ) : selectedMessage ? (
                  <div className="flex min-h-[20rem] flex-col">
                    <div className="mb-2">
                      <h2 className="text-lg font-black text-slate-950">{agentTopic(selectedOutput.agent)}</h2>
                      <p className="mt-1 text-xs text-slate-500">Agent 回复 · {messageTitle(selectedMessage)} · {formatTime(selectedMessage.created_at)}</p>
                    </div>
                    <div className="min-h-[16rem] overflow-x-auto rounded-xl border border-border bg-panel p-3 text-fg shadow-inner">
                      <ContentRenderer
                        content={selectedMessage.content}
                        artifactId={selectedMessage.artifact_id}
                        onEditArtifact={onEditArtifact}
                        sourceAgentId={selectedOutput.agent.id}
                        sourceAgentName={selectedOutput.agent.name}
                        sourceMessageId={selectedMessage.id}
                        fillHeight
                      />
                    </div>
                  </div>
                ) : null}
              </section>
            )}
          </div>
        </main>

        <footer className="mt-3 shrink-0 rounded-xl bg-white px-3 py-2 shadow-sm ring-1 ring-slate-200/80">
          <div className="flex gap-2 overflow-x-auto pb-1">
            {agentOutputs.map((item, index) => {
              const active = item.agent.id === selectedAgentId;
              return (
                <button
                  key={item.agent.id}
                  type="button"
                  onClick={() => handleSelectAgent(item.agent.id)}
                  className={`flex min-w-[10.5rem] items-center gap-2 rounded-lg border px-2.5 py-2 text-left transition ${active ? "border-slate-950 bg-white shadow-sm" : "border-transparent bg-slate-50 hover:border-slate-300 hover:bg-white"}`}
                >
                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full border border-slate-200 bg-white font-mono text-xs font-black text-slate-700">
                    {getAgentBadge(item.agent, index)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs font-bold text-slate-900">{item.agent.name}</span>
                    <span className="mt-0.5 block text-[10px] font-semibold text-slate-400">Agent {String(index + 1).padStart(2, "0")}</span>
                  </span>
                </button>
              );
            })}
            {agentOutputs.length === 0 && (
              <div className="w-full rounded-xl border border-dashed border-slate-300 px-5 py-6 text-center text-sm text-slate-500">
                当前对话还没有 Agent 成员
              </div>
            )}
          </div>
        </footer>
      </div>
    </div>
  );
}
