import { useEffect, useRef, useState } from "react";

import type { Agent } from "../types";

interface Props {
  open: boolean;
  filter: string;
  agents: Agent[];
  onSelect: (agent: Agent) => void;
  onClose: () => void;
  anchorRect?: DOMRect | null;
}

export function MentionPopover({ open, filter, agents, onSelect, onClose }: Props) {
  const [highlightIdx, setHighlightIdx] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);

  const matched = agents.filter((a) =>
    a.name.toLowerCase().includes(filter.toLowerCase()),
  );

  useEffect(() => {
    setHighlightIdx(0);
  }, [filter, open]);

  useEffect(() => {
    if (!open) return;

    function onKey(e: KeyboardEvent) {
      if (!open) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setHighlightIdx((i) => Math.min(i + 1, matched.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setHighlightIdx((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        if (matched[highlightIdx]) {
          onSelect(matched[highlightIdx]);
        }
      } else if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    }

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, matched, highlightIdx, onSelect, onClose]);

  useEffect(() => {
    if (open && listRef.current) {
      const active = listRef.current.querySelector('[data-highlighted="true"]');
      active?.scrollIntoView({ block: "nearest" });
    }
  }, [highlightIdx, open]);

  if (!open || matched.length === 0) return null;

  return (
    <div
      className="absolute left-0 right-0 bottom-full mb-1 z-50 bg-panel border border-border rounded-lg shadow-xl max-h-48 overflow-y-auto"
      ref={listRef}
    >
      {matched.map((a, i) => (
        <button
          key={a.id}
          type="button"
          data-highlighted={i === highlightIdx}
          onMouseEnter={() => setHighlightIdx(i)}
          onMouseDown={(e) => {
            e.preventDefault();
            onSelect(a);
          }}
          className={`w-full flex items-center gap-2.5 px-3 py-2 text-left text-sm transition-colors ${
            i === highlightIdx
              ? "bg-accent/15 text-fg"
              : "text-fg hover:bg-bg/60"
          }`}
        >
          <span className="w-6 h-6 rounded-lg bg-accent/20 flex items-center justify-center text-xs shrink-0 select-none">
            {a.avatar || a.name.charAt(0).toUpperCase()}
          </span>
          <span className="font-medium truncate">{a.name}</span>
          <span className="ml-auto text-[10px] text-muted truncate shrink-0">
            {a.capabilities.slice(0, 2).join(" · ")}
          </span>
        </button>
      ))}
      {matched.length === 0 && (
        <div className="px-3 py-2 text-xs text-muted">无匹配 Agent</div>
      )}
    </div>
  );
}
