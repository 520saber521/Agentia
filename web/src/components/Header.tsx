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

export function Header() {
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

      <div className="ml-auto min-w-0 truncate text-xs text-muted">
        {cur ? (
          <>
            Conversation <span className="font-mono text-fg/80">{cur}</span>
          </>
        ) : (
          <span className="opacity-60">No conversation selected</span>
        )}
      </div>
    </header>
  );
}
