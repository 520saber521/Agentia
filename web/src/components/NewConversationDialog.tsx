import { useEffect, useRef, useState } from "react";

import { describeApiError, fetchAgents } from "../api/client";
import { useChatStore } from "../stores/useChatStore";
import type { Agent } from "../types";

interface Props {
  open: boolean;
  onClose: () => void;
}

type ConvType = "single" | "group";

/**
 * "新建会话"模态框（W2 F-W2-5 起）。
 *
 * - 打开模态时拉 `GET /api/agents`，列出全部可选 Agent；
 * - `type=single` 时 Agent 选择器为**单选**（沿用 W1 行为）；
 * - `type=group` 时 Agent 选择器为**多选**，必须选 ≥1；
 * - 错误统一走 `describeApiError`，覆盖 422 `group_requires_agents` /
 *   `unknown_agent` 等稳定枚举（参考 `ai-collab/SPEC.md` F-W2-5）。
 */
export function NewConversationDialog({ open, onClose }: Props) {
  const createAndSelect = useChatStore((s) => s.createAndSelect);

  const [title, setTitle] = useState("");
  const [type, setType] = useState<ConvType>("single");
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loadingAgents, setLoadingAgents] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // 模态每次打开时重置 + 拉 agents
  useEffect(() => {
    if (!open) return;
    setTitle("");
    setType("single");
    setSelected(new Set());
    setError(null);
    setSubmitting(false);
    setLoadingAgents(true);

    let cancelled = false;
    void (async () => {
      try {
        const list = await fetchAgents();
        if (cancelled) return;
        setAgents(list);
        // 单聊默认选第一个 Agent（最常见路径）
        if (list.length > 0) setSelected(new Set([list[0].id]));
      } catch (err) {
        if (!cancelled) setError(describeApiError(err));
      } finally {
        if (!cancelled) setLoadingAgents(false);
      }
    })();

    setTimeout(() => inputRef.current?.focus(), 0);
    return () => {
      cancelled = true;
    };
  }, [open]);

  if (!open) return null;

  function handleTypeChange(next: ConvType) {
    setType(next);
    // single → group：保持当前选中；group → single：只保留首个
    if (next === "single" && selected.size > 1) {
      const first = Array.from(selected)[0];
      setSelected(new Set([first]));
    }
  }

  function toggleAgent(id: string) {
    setSelected((prev) => {
      const out = new Set(prev);
      if (type === "single") {
        // 单选语义：永远只保留点中的那个（如果点的就是当前选中，保持不变）
        out.clear();
        out.add(id);
        return out;
      }
      // group：多选 toggle
      if (out.has(id)) out.delete(id);
      else out.add(id);
      return out;
    });
  }

  const canSubmit =
    !submitting &&
    !loadingAgents &&
    title.trim().length > 0 &&
    selected.size > 0 &&
    (type !== "group" || selected.size >= 1);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = title.trim();
    if (!trimmed) {
      setError("会话标题不能为空");
      return;
    }
    if (selected.size === 0) {
      setError(
        type === "group" ? "群聊需要至少 1 个 Agent" : "请选择一个 Agent",
      );
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await createAndSelect({
        title: trimmed,
        type,
        agent_ids: Array.from(selected),
      });
      onClose();
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center px-4"
      onClick={onClose}
      role="presentation"
    >
      <form
        onSubmit={handleSubmit}
        onClick={(e) => e.stopPropagation()}
        className="bg-panel border border-border rounded-lg w-full max-w-md p-5 shadow-2xl"
      >
        <h3 className="text-sm font-semibold text-fg">新建会话</h3>
        <p className="text-xs text-muted mt-1">
          单聊选 1 个 Agent；群聊可选多个 Agent，由你 @ 不同成员分头干活。
        </p>

        <label className="block mt-4 text-xs text-muted">会话标题</label>
        <input
          ref={inputRef}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="例如：写一篇博客 / OAuth 登录流程"
          maxLength={200}
          className="mt-1 w-full bg-bg border border-border rounded-md px-3 py-2 text-sm text-fg focus:outline-none focus:border-accent"
        />

        <label className="block mt-4 text-xs text-muted">会话类型</label>
        <div className="mt-1 flex gap-2">
          {(["single", "group"] as const).map((opt) => (
            <button
              key={opt}
              type="button"
              onClick={() => handleTypeChange(opt)}
              className={`px-3 py-1.5 rounded-md text-xs border transition ${
                type === opt
                  ? "border-accent bg-accent/10 text-fg"
                  : "border-border text-muted hover:border-accent/60"
              }`}
            >
              {opt === "single" ? "单聊" : "群聊"}
            </button>
          ))}
        </div>

        <div className="mt-4 flex items-center justify-between">
          <label className="text-xs text-muted">
            选择 Agent{type === "group" ? "（可多选，至少 1 个）" : "（单选）"}
          </label>
          {selected.size > 0 && (
            <span className="text-[10px] text-muted">
              已选 {selected.size} 个
            </span>
          )}
        </div>
        <div className="mt-1 max-h-44 overflow-y-auto rounded-md border border-border divide-y divide-border">
          {loadingAgents && (
            <div className="px-3 py-3 text-xs text-muted">加载 Agent 列表…</div>
          )}
          {!loadingAgents && agents.length === 0 && (
            <div className="px-3 py-3 text-xs text-muted">暂无可选 Agent</div>
          )}
          {!loadingAgents &&
            agents.map((a) => {
              const isSelected = selected.has(a.id);
              return (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => toggleAgent(a.id)}
                  className={`w-full flex items-center gap-2 px-3 py-2 text-left transition ${
                    isSelected
                      ? "bg-accent/10 text-fg"
                      : "text-muted hover:text-fg hover:bg-bg"
                  }`}
                >
                  <span
                    className={`inline-flex w-4 h-4 items-center justify-center rounded ${
                      type === "group"
                        ? "border border-border"
                        : "rounded-full border border-border"
                    } ${isSelected ? "bg-accent border-accent" : ""}`}
                    aria-hidden="true"
                  >
                    {isSelected && (
                      <span className="block w-2 h-2 bg-white rounded-sm" />
                    )}
                  </span>
                  <span className="flex-1">
                    <span className="text-sm font-medium text-fg">
                      {a.name}
                    </span>
                    <span className="ml-2 text-[10px] text-muted">
                      {a.adapter_type}
                    </span>
                  </span>
                  {a.capabilities.length > 0 && (
                    <span className="flex gap-1">
                      {a.capabilities.slice(0, 3).map((cap) => (
                        <span
                          key={cap}
                          className="px-1.5 py-0.5 text-[10px] rounded bg-bg border border-border text-muted"
                        >
                          {cap}
                        </span>
                      ))}
                    </span>
                  )}
                </button>
              );
            })}
        </div>

        {error && (
          <p className="mt-3 text-xs text-red-400" role="alert">
            {error}
          </p>
        )}

        <div className="mt-5 flex items-center justify-end gap-2">
          {!canSubmit && !submitting && !loadingAgents && title.trim().length === 0 && (
            <span className="text-[10px] text-muted mr-auto">
              请先输入会话标题
            </span>
          )}
          {!canSubmit && !submitting && !loadingAgents && title.trim().length > 0 && selected.size === 0 && (
            <span className="text-[10px] text-muted mr-auto">
              {type === "group" ? "群聊需要至少 1 个 Agent" : "请选择一个 Agent"}
            </span>
          )}
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 rounded-md text-xs text-muted border border-border hover:text-fg transition"
            disabled={submitting}
          >
            取消
          </button>
          <button
            type="submit"
            className="px-3 py-1.5 rounded-md text-xs bg-accent text-white hover:bg-accent/90 transition disabled:opacity-60 disabled:cursor-not-allowed"
            disabled={!canSubmit}
            title={
              !canSubmit && !submitting && !loadingAgents
                ? title.trim().length === 0
                  ? "请先输入会话标题"
                  : type === "group" && selected.size === 0
                    ? "群聊需要至少 1 个 Agent"
                    : "请选择一个 Agent"
                : undefined
            }
          >
            {submitting ? "创建中…" : "创建"}
          </button>
        </div>
      </form>
    </div>
  );
}
