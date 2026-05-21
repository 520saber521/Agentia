import { useChatStore } from "../stores/useChatStore";

const STATUS_LABELS: Record<string, { label: string; cls: string }> = {
  connected: { label: "在线", cls: "bg-emerald-900/70 text-emerald-300" },
  connecting: { label: "连接中", cls: "bg-amber-900/60 text-amber-200" },
  disconnected: { label: "离线", cls: "bg-rose-900/60 text-rose-200" },
};

export function Header() {
  const status = useChatStore((s) => s.status);
  const serverInfo = useChatStore((s) => s.serverInfo);
  const cur = useChatStore((s) => s.currentConvId);
  const { label, cls } = STATUS_LABELS[status] ?? STATUS_LABELS.disconnected;

  return (
    <header className="flex items-center gap-4 px-6 h-12 bg-panel border-b border-border shrink-0">
      <span className="text-sm font-semibold text-fg">
        AgentHub <span className="text-muted font-normal">· 多 Agent 协作平台</span>
      </span>
      <span className={`text-xs px-2.5 py-1 rounded-full select-none ${cls}`}>
        {label}
      </span>
      {serverInfo && (
        <span className="text-xs text-muted truncate">via {serverInfo}</span>
      )}
      <div className="ml-auto text-xs text-muted truncate">
        {cur ? (
          <>
            当前会话 · <span className="text-fg">{cur}</span>
          </>
        ) : (
          <span className="opacity-60">未选会话</span>
        )}
      </div>
    </header>
  );
}
