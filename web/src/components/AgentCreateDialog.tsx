import { useEffect, useState } from "react";

import { describeApiError, fetchAgentPrompt, type SaveAgentInput } from "../api/client";
import { useChatStore } from "../stores/useChatStore";
import type { Agent } from "../types";

interface Props {
  open: boolean;
  agent?: Agent | null;
  onClose: () => void;
}

const MODEL_PROVIDERS = [
  { value: "codex", label: "OpenAI / Codex" },
  { value: "claude_code", label: "Claude Code" },
  { value: "opencode", label: "OpenCode" },
  { value: "mock", label: "Mock" },
];

const TOOL_OPTIONS = [
  { id: "code_editor", label: "Code editor", desc: "Read and revise code artifacts." },
  { id: "artifact_read", label: "Artifact read", desc: "Open generated files and previews." },
  { id: "artifact_write", label: "Artifact write", desc: "Create files, previews, and new versions." },
  { id: "web_preview", label: "Web preview", desc: "Render HTML and web artifacts." },
  { id: "deploy", label: "Deploy", desc: "Prepare deployment status and preview URLs." },
];

function parseCsv(value: string): string[] {
  return value
    .split(/[,，/]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function AgentCreateDialog({ open, agent, onClose }: Props) {
  const createAgentContact = useChatStore((s) => s.createAgentContact);
  const updateAgentContact = useChatStore((s) => s.updateAgentContact);
  const startAgentChat = useChatStore((s) => s.startAgentChat);

  const editing = Boolean(agent);
  const lockedPrompt = Boolean(agent?.locked_prompt || agent?.is_system);
  const isSystem = Boolean(agent?.is_system);
  const isOrchestrator = agent?.id === "agent_orchestrator";

  const [name, setName] = useState("");
  const [adapterType, setAdapterType] = useState("codex");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [capabilitiesText, setCapabilitiesText] = useState("");
  const [selectedTools, setSelectedTools] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Prompt preview
  const [showPrompt, setShowPrompt] = useState(false);
  const [promptText, setPromptText] = useState("");
  const [promptLoading, setPromptLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    setName(agent?.name ?? "");
    setAdapterType(agent?.adapter_type ?? "codex");
    setModel(agent?.model ?? "");
    setBaseUrl(agent?.base_url ?? "");
    setApiKey("");
    setSystemPrompt(agent?.system_prompt ?? "");
    setCapabilitiesText((agent?.capabilities ?? []).join(", "));
    setSelectedTools(new Set(agent?.tools ?? []));
    setError(null);
    setNotice(null);
    setShowPrompt(false);
    setPromptText("");
  }, [agent, open]);

  async function loadPrompt() {
    if (!agent) return;
    if (showPrompt) {
      setShowPrompt(false);
      return;
    }
    if (promptText) {
      setShowPrompt(true);
      return;
    }
    setPromptLoading(true);
    try {
      const res = await fetchAgentPrompt(agent.id);
      setPromptText(res.prompt);
      setShowPrompt(true);
    } catch {
      setPromptText(agent.system_prompt || "");
      setShowPrompt(true);
    } finally {
      setPromptLoading(false);
    }
  }

  if (!open) return null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      setError("Agent name is required");
      return;
    }
    if (!model.trim()) {
      setError("Model is required");
      return;
    }
    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      const payload: SaveAgentInput = {
        name: name.trim(),
        adapter_type: adapterType,
        model: model.trim(),
        base_url: baseUrl.trim(),
        system_prompt: lockedPrompt ? undefined : systemPrompt.trim(),
        capabilities: parseCsv(capabilitiesText),
        tools: Array.from(selectedTools),
      };
      if (apiKey.trim()) {
        payload.api_key = apiKey.trim();
      }
      if (agent) {
        await updateAgentContact(agent.id, payload);
        setNotice("Agent configuration saved and will apply to the next message.");
      } else {
        const created = await createAgentContact(payload);
        await startAgentChat(created.id);
        onClose();
      }
      setApiKey("");
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete() {
    if (!agent || !agent.can_delete) return;
    const ok = window.confirm(`Delete Agent "${agent.name}"? Existing chat history will be kept.`);
    if (!ok) return;
    setDeleting(true);
    setError(null);
    try {
      await useChatStore.getState().deleteAgentContact(agent.id);
      onClose();
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setDeleting(false);
    }
  }

  function toggleTool(toolId: string) {
    setSelectedTools((prev) => {
      const next = new Set(prev);
      if (next.has(toolId)) next.delete(toolId);
      else next.add(toolId);
      return next;
    });
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4 backdrop-blur-sm"
      onClick={onClose}
      role="presentation"
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={handleSubmit}
        className="w-full max-w-2xl rounded-2xl border border-border bg-panel p-5 shadow-2xl max-h-[90vh] overflow-y-auto"
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent/15 text-lg">
              {agent?.avatar || "🤖"}
            </span>
            <div>
              <h3 className="text-base font-semibold text-fg">
                {editing ? name : "Create custom Agent"}
              </h3>
              <p className="mt-0.5 text-xs text-muted">
                {isSystem
                  ? "System agent — configure provider, encrypted API key, and model."
                  : "Configure provider, encrypted API key, and model."}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-border px-2 py-1 text-xs text-muted hover:text-fg"
          >
            Close
          </button>
        </div>

        {/* System badge */}
        {isSystem && (
          <div className="mt-3 flex items-center gap-2 rounded-lg border border-accent/30 bg-accent/5 px-3 py-2">
            <span className="text-xs text-accent font-medium">🔒 System Agent</span>
            <span className="text-[10px] text-muted">
              Prompt locked · Configuration restricted
            </span>
          </div>
        )}

        {/* Config fields */}
        <div className="mt-4 grid grid-cols-2 gap-4">
          <label className="text-xs text-muted">
            Name
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={isOrchestrator || isSystem}
              className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent disabled:opacity-60"
              placeholder="Review Engineer"
            />
          </label>
          <label className="text-xs text-muted">
            Model provider
            <select
              value={adapterType}
              onChange={(e) => setAdapterType(e.target.value)}
              disabled={isOrchestrator}
              className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent disabled:opacity-60"
            >
              {MODEL_PROVIDERS.map((provider) => (
                <option key={provider.value} value={provider.value}>{provider.label}</option>
              ))}
            </select>
          </label>
          <label className="text-xs text-muted">
            Model
            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent"
              placeholder="gpt-4o, claude-sonnet, deepseek-chat"
            />
          </label>
          <label className="text-xs text-muted">
            API key {agent?.api_key_configured ? `(${agent.api_key_mask})` : ""}
            <input
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent"
              placeholder={agent?.api_key_configured ? "Leave blank to keep existing encrypted key" : "Paste API key"}
              type="password"
            />
          </label>
        </div>

        <label className="mt-4 block text-xs text-muted">
          Base URL
          <input
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent"
            placeholder="https://api.openai.com/v1"
          />
        </label>

        <label className="mt-4 block text-xs text-muted">
          System Prompt
          <textarea
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            disabled={lockedPrompt}
            className="mt-1 min-h-28 w-full resize-y rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent disabled:opacity-60"
            placeholder="Describe the role, boundaries, output style, and task responsibilities for this Agent."
          />
        </label>

        <label className="mt-4 block text-xs text-muted">
          Capabilities
          <input
            value={capabilitiesText}
            onChange={(e) => setCapabilitiesText(e.target.value)}
            disabled={isOrchestrator}
            className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent disabled:opacity-60"
            placeholder="frontend, react, code"
          />
        </label>

        <div className="mt-4">
          <div className="mb-1.5 text-xs text-muted">Tools</div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {TOOL_OPTIONS.map((tool) => {
              const checked = selectedTools.has(tool.id);
              return (
                <button
                  key={tool.id}
                  type="button"
                  onClick={() => toggleTool(tool.id)}
                  disabled={isOrchestrator}
                  className={`rounded-lg border px-3 py-2 text-left transition disabled:opacity-60 ${
                    checked
                      ? "border-accent bg-accent/10 text-fg"
                      : "border-border bg-bg/50 text-muted hover:border-accent/60 hover:text-fg"
                  }`}
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="text-xs font-medium">{tool.label}</span>
                    <span className={`h-3 w-3 rounded-sm border ${checked ? "border-accent bg-accent" : "border-border"}`} />
                  </span>
                  <span className="mt-1 block text-[10px] leading-relaxed text-muted">{tool.desc}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Prompt preview section */}
        {editing && (
          <div className="mt-4 rounded-lg border border-border bg-bg/50 overflow-hidden">
            <button
              type="button"
              onClick={() => void loadPrompt()}
              className="flex w-full items-center justify-between px-3 py-2.5 text-xs text-muted hover:text-fg transition-colors"
            >
              <span className="flex items-center gap-2">
                <span>{lockedPrompt ? "🔒" : "📝"} System Prompt</span>
                {lockedPrompt && (
                  <span className="rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-400">
                    🛜 read-only
                  </span>
                )}
              </span>
              <span className="text-[10px]">
                {promptLoading ? "Loading..." : showPrompt ? "▲ Hide" : "▼ View"}
              </span>
            </button>
            {showPrompt && promptText && (
              <div className="border-t border-border px-3 py-3 max-h-64 overflow-y-auto">
                {lockedPrompt && (
                  <div className="mb-2 rounded border border-accent/20 bg-accent/5 px-2 py-1.5 text-[10px] text-accent leading-relaxed">
                    系统提示词 · 只读（内容来自项目代码，不可修改）
                  </div>
                )}
                <pre className="text-[11px] text-muted leading-relaxed whitespace-pre-wrap font-mono">
                  {promptText}
                </pre>
              </div>
            )}
            {showPrompt && !promptText && !promptLoading && (
              <div className="border-t border-border px-3 py-2 text-[11px] text-muted italic">
                No prompt configured.
              </div>
            )}
          </div>
        )}

        {/* Capabilities display */}
        {agent && agent.tools.length > 0 && (
          <div className="mt-4">
            <div className="text-xs text-muted mb-1.5">Enabled tools</div>
            <div className="flex flex-wrap gap-1">
              {agent.tools.map((tool) => (
                <span
                  key={tool}
                  className="rounded-md border border-accent/30 bg-accent/5 px-2 py-0.5 text-[10px] text-accent"
                >
                  {tool}
                </span>
              ))}
            </div>
          </div>
        )}

        {agent && agent.capabilities.length > 0 && (
          <div className="mt-4">
            <div className="text-xs text-muted mb-1.5">Capabilities</div>
            <div className="flex flex-wrap gap-1">
              {agent.capabilities.map((cap) => (
                <span
                  key={cap}
                  className="rounded-md border border-border bg-bg/50 px-2 py-0.5 text-[10px] text-fg/70"
                >
                  {cap}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Notices */}
        {notice && <p className="mt-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">{notice}</p>}
        {error && <p className="mt-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">{error}</p>}

        {/* Actions */}
        <div className="mt-5 flex items-center justify-between">
          {editing && agent?.can_delete ? (
            <button
              type="button"
              onClick={() => void handleDelete()}
              disabled={deleting}
              className="rounded-lg border border-red-500/40 px-3 py-2 text-xs text-red-300 transition hover:bg-red-500/10 disabled:opacity-60"
            >
              {deleting ? "Deleting..." : "Delete Agent"}
            </button>
          ) : (
            <span />
          )}
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-border px-3 py-2 text-xs text-muted transition hover:text-fg"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="rounded-lg bg-accent px-4 py-2 text-xs font-medium text-white transition hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? "Saving..." : editing ? "Save" : "Create"}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
