import { useChatStore } from "../stores/useChatStore";

const STATUS_LABELS: Record<string, { label: string; cls: string; dot: string }> = {
  connected: {
    label: "Online",
    cls: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
    dot: "bg-emerald-400",
  },
  connecting: {
    label: "Connecting",
    cls: "border-amber-500/30 bg-amber-500/10 text-amber-200",
    dot: "bg-amber-400",
  },
  disconnected: {
    label: "Offline",
    cls: "border-rose-500/30 bg-rose-500/10 text-rose-200",
    dot: "bg-rose-400",
  },
};

interface HeaderProps {
  showAgentWorkspace?: boolean;
  onToggleAgentWorkspace?: () => void;
}

export function Header({ showAgentWorkspace, onToggleAgentWorkspace }: HeaderProps) {
  const status = useChatStore((s) => s.status);
  const serverInfo = useChatStore((s) => s.serverInfo);
  const cur = useChatStore((s) => s.currentConvId);
  const { label, cls, dot } = STATUS_LABELS[status] ?? STATUS_LABELS.disconnected;

  return (
    <header className="flex h-12 shrink-0 items-center gap-4 border-b border-border bg-[#07090d]/95 px-5">
      <div className="flex min-w-0 items-baseline gap-2">
        <span className="text-sm font-semibold tracking-wide text-fg">Agentia</span>
        <span className="text-[10px] uppercase tracking-[0.22em] text-muted">
          Swarm workspace
        </span>
      </div>

      <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] ${cls}`}>
        <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
        {label}
      </span>

      {serverInfo && (
        <span className="hidden truncate text-xs text-muted md:inline">via {serverInfo}</span>
      )}

      <div className="ml-auto flex min-w-0 items-center gap-3">
        <button
          type="button"
          onClick={onToggleAgentWorkspace}
          disabled={!cur}
          className="inline-flex h-8 shrink-0 items-center gap-2 rounded-lg border border-accent/30 bg-accent/10 px-3 text-xs font-semibold text-accent transition hover:border-accent/60 hover:bg-accent/15 disabled:cursor-not-allowed disabled:border-border disabled:bg-bg disabled:text-muted/50"
        >
          <span className="text-sm">{showAgentWorkspace ? "←" : "▣"}</span>
          {showAgentWorkspace ? "返回对话" : "Agent 工作区"}
        </button>

        <div className="min-w-0 truncate text-xs text-muted">
          {cur ? (
            <>
              Conversation <span className="font-mono text-fg/80">{cur}</span>
            </>
          ) : (
            <span className="opacity-60">No conversation selected</span>
          )}
        </div>
      </div>
    </header>
  );
}
