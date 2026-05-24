import { useEffect, useMemo, useState } from "react";

import { describeApiError } from "../api/client";
import { useChatStore } from "../stores/useChatStore";
import type { Agent } from "../types";

interface Props {
  open: boolean;
  agent?: Agent | null;
  onClose: () => void;
}

const DEFAULT_TOOLS = ["code", "terminal", "files", "web_search"];
const MODEL_PROVIDERS = [
  { value: "codex", label: "OpenAI / Codex" },
  { value: "claude_code", label: "Claude Code" },
  { value: "opencode", label: "OpenCode" },
  { value: "mock", label: "Mock" },
];

function splitTags(value: string): string[] {
  return value
    .split(/[,，]/)
    .map((x) => x.trim())
    .filter(Boolean);
}

function joinEditableTags(agent?: Agent | null): string {
  if (!agent) return "code, backend";
  return agent.capabilities.filter((cap) => !DEFAULT_TOOLS.includes(cap)).join(", ");
}

export function AgentCreateDialog({ open, agent, onClose }: Props) {
  const createAgentContact = useChatStore((s) => s.createAgentContact);
  const updateAgentContact = useChatStore((s) => s.updateAgentContact);
  const startAgentChat = useChatStore((s) => s.startAgentChat);

  const editing = Boolean(agent);
  const lockedPrompt = Boolean(agent?.locked_prompt);

  const [name, setName] = useState("");
  const [adapterType, setAdapterType] = useState("codex");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [capabilities, setCapabilities] = useState("code, backend");
  const [toolset, setToolset] = useState<Set<string>>(new Set(["code", "files"]));
  const [submitting, setSubmitting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setName(agent?.name ?? "");
    setAdapterType(agent?.adapter_type ?? "codex");
    setModel(agent?.model ?? "");
    setBaseUrl(agent?.base_url ?? "");
    setApiKey("");
    setSystemPrompt(agent?.system_prompt ?? "");
    setCapabilities(joinEditableTags(agent));
    setToolset(new Set((agent?.capabilities ?? ["code", "files"]).filter((cap) => DEFAULT_TOOLS.includes(cap))));
    setError(null);
    setNotice(null);
  }, [agent, open]);

  const capabilityTags = useMemo(() => {
    const tags = new Set(splitTags(capabilities));
    for (const tool of toolset) tags.add(tool);
    return Array.from(tags);
  }, [capabilities, toolset]);

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
    if (!lockedPrompt && !systemPrompt.trim()) {
      setError("System prompt is required");
      return;
    }
    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      const payload = {
        name: name.trim(),
        adapter_type: adapterType,
        api_key: apiKey.trim(),
        model: model.trim(),
        base_url: baseUrl.trim(),
        system_prompt: lockedPrompt ? undefined : systemPrompt.trim(),
        capabilities: capabilityTags,
      };
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

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4 backdrop-blur-sm"
      onClick={onClose}
      role="presentation"
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={handleSubmit}
        className="w-full max-w-3xl rounded-2xl border border-border bg-panel p-5 shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-base font-semibold text-fg">
              {editing ? "Edit Agent" : "Create custom Agent"}
            </h3>
            <p className="mt-1 text-xs text-muted">
              Configure provider, encrypted API key, model, role prompt, and capability tags.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-border px-2 py-1 text-xs text-muted hover:text-fg"
          >
            Close
          </button>
        </div>

        <div className="mt-5 grid grid-cols-2 gap-4">
          <label className="text-xs text-muted">
            Name
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={agent?.id === "agent_orchestrator"}
              className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent disabled:opacity-60"
              placeholder="Review Engineer"
            />
          </label>
          <label className="text-xs text-muted">
            Model provider
            <select
              value={adapterType}
              onChange={(e) => setAdapterType(e.target.value)}
              className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent"
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
              placeholder="gpt-4o, claude-sonnet, opencode-default"
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
          Role prompt {lockedPrompt ? "(locked by system)" : ""}
          <textarea
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            disabled={lockedPrompt}
            className="mt-1 h-28 w-full resize-none rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent disabled:opacity-70"
            placeholder="You are a careful implementation agent focused on..."
          />
        </label>

        <label className="mt-4 block text-xs text-muted">
          Capability tags
          <input
            value={capabilities}
            onChange={(e) => setCapabilities(e.target.value)}
            disabled={agent?.id === "agent_orchestrator"}
            className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent disabled:opacity-60"
            placeholder="frontend, code, tests"
          />
        </label>

        <div className="mt-4">
          <div className="text-xs text-muted">Toolset</div>
          <div className="mt-2 flex flex-wrap gap-2">
            {DEFAULT_TOOLS.map((tool) => {
              const active = toolset.has(tool);
              return (
                <button
                  key={tool}
                  type="button"
                  disabled={agent?.id === "agent_orchestrator"}
                  onClick={() =>
                    setToolset((prev) => {
                      const next = new Set(prev);
                      if (next.has(tool)) next.delete(tool);
                      else next.add(tool);
                      return next;
                    })
                  }
                  className={`rounded-lg border px-3 py-1.5 text-xs transition disabled:opacity-50 ${
                    active
                      ? "border-accent bg-accent/15 text-fg"
                      : "border-border text-muted hover:text-fg"
                  }`}
                >
                  {tool}
                </button>
              );
            })}
          </div>
        </div>

        {notice && <p className="mt-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">{notice}</p>}
        {error && <p className="mt-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">{error}</p>}

        <div className="mt-6 flex items-center justify-between">
          {editing && agent?.can_delete ? (
            <button
              type="button"
              onClick={() => void handleDelete()}
              disabled={deleting}
              className="rounded-lg border border-red-500/40 px-3 py-2 text-xs text-red-300 transition hover:bg-red-500/10 disabled:opacity-60"
            >
              {deleting ? "Deleting..." : "Delete Agent"}
            </button>
          ) : <span />}
          <button
            type="submit"
            disabled={submitting}
            className="rounded-lg bg-accent px-4 py-2 text-xs font-medium text-white transition hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {submitting ? "Saving..." : editing ? "Save Agent" : "Create Agent"}
          </button>
        </div>
      </form>
    </div>
  );
}
