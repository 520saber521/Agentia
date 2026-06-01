/**
 * Multi-conversation tab bar (like browser/IDE tabs).
 *
 * Renders a horizontal tab strip above the message panel. Each open
 * conversation gets one tab with its title, an active indicator, and
 * a close button. Click to switch, X to close.
 */

import { useChatStore } from "../stores/useChatStore";
import { X } from "./icons";

export function TabBar() {
  const openTabIds = useChatStore((s) => s.openTabIds);
  const activeTabId = useChatStore((s) => s.activeTabId);
  const conversations = useChatStore((s) => s.conversations);
  const switchTab = useChatStore((s) => s.switchTab);
  const closeTab = useChatStore((s) => s.closeTab);

  if (openTabIds.length <= 1) return null;

  return (
    <div className="flex shrink-0 items-center gap-0 overflow-x-auto border-b border-border bg-panel px-1 pt-1">
      {openTabIds.map((id) => {
        const conv = conversations.find((c) => c.id === id);
        const title = conv?.title ?? id;
        const isActive = id === activeTabId;

        return (
          <button
            key={id}
            type="button"
            onClick={() => switchTab(id)}
            onMouseDown={(e) => {
              if (e.button === 1) {
                e.preventDefault();
                closeTab(id);
              }
            }}
            className={
              "group flex shrink-0 items-center gap-1.5 rounded-t-lg px-3 py-1.5 text-xs transition max-w-48" +
              (isActive
                ? " bg-bg text-fg border-x border-t border-border"
                : " text-muted hover:text-fg hover:bg-surface-hover")
            }
            title={title}
          >
            <span className="truncate">{title}</span>
            <span
              className="ml-0.5 shrink-0 rounded-sm p-0.5 opacity-0 transition hover:bg-surface-hover group-hover:opacity-100"
              onClick={(e) => {
                e.stopPropagation();
                closeTab(id);
              }}
              title="Close tab"
            >
              <X className="h-2.5 w-2.5" />
            </span>
          </button>
        );
      })}
    </div>
  );
}
