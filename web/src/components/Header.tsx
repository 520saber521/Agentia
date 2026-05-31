import { useChatStore } from "../stores/useChatStore";
import { useTheme } from "../hooks/useTheme";
import { Menu, Sun, Moon } from "./icons";

const STATUS_LABELS: Record<string, { label: string; cls: string; dot: string }> = {
  connected: {
    label: "Online",
    cls: "border-success/30 bg-success/10 text-success/80",
    dot: "bg-success",
  },
  connecting: {
    label: "Connecting",
    cls: "border-warning/30 bg-warning/10 text-warning/80",
    dot: "bg-warning",
  },
  disconnected: {
    label: "Offline",
    cls: "border-danger/30 bg-danger/10 text-danger/80",
    dot: "bg-danger",
  },
};

export function Header() {
  const status = useChatStore((s) => s.status);
  const serverInfo = useChatStore((s) => s.serverInfo);
  const cur = useChatStore((s) => s.currentConvId);
  const { label, cls, dot } = STATUS_LABELS[status] ?? STATUS_LABELS.disconnected;
  const { theme, toggle: toggleTheme } = useTheme();

  return (
    <header className="flex h-12 shrink-0 items-center gap-4 border-b border-border bg-bg/90 backdrop-blur-lg px-5">
      <button
        type="button"
        onClick={() => useChatStore.getState().toggleSidebar?.()}
        className="md:hidden mr-1 rounded p-1 text-muted hover:text-fg"
        aria-label="切换侧边栏"
      >
        <Menu className="h-5 w-5" />
      </button>
      <div className="flex min-w-0 items-baseline gap-2">
        <span className="text-sm font-semibold tracking-wide text-fg">Agentia</span>
        <span className="text-2xs uppercase tracking-[0.22em] text-muted">
          Swarm workspace
        </span>
      </div>

      <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-2xs ${cls}`}>
        <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
        {label}
      </span>

      {serverInfo && (
        <span className="hidden truncate text-xs text-muted md:inline">via {serverInfo}</span>
      )}

      <div className="ml-auto flex items-center gap-3">
        <button
          type="button"
          onClick={toggleTheme}
          className="rounded p-1.5 text-muted hover:text-fg transition-colors"
          aria-label={theme === "dark" ? "切换到亮色模式" : "切换到暗色模式"}
          title={theme === "dark" ? "亮色模式" : "暗色模式"}
        >
          {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
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
