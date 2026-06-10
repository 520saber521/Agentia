/**
 * Multi-conversation tab bar (like browser/IDE tabs).
 *
 * Renders a horizontal tab strip above the message panel. Each open
 * conversation gets one tab with its title, an active indicator, and
 * a close button. Click to switch, X to close.
 */

import { useChatStore } from "../stores/useChatStore";

export function TabBar() {
  const openTabIds = useChatStore((s) => s.openTabIds);
  const activeTabId = useChatStore((s) => s.activeTabId);
  const conversations = useChatStore((s) => s.conversations);
  const switchTab = useChatStore((s) => s.switchTab);
  const closeTab = useChatStore((s) => s.closeTab);

  if (openTabIds.length <= 1) return null;

  return (
    <div className="flex shrink-0 items-center gap-0 overflow-x-auto border-b border-border bg-[var(--bg-tab-bar,var(--color-surface))] px-1 pt-1">
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
              // Middle-click to close
              if (e.button === 1) {
                e.preventDefault();
                closeTab(id);
              }
            }}
            className={
              "group flex shrink-0 items-center gap-1.5 rounded-t-md px-3 py-1.5 text-xs transition max-w-48" +
              (isActive
                ? " bg-[var(--color-bg)] text-fg border-x border-t border-border"
                : " text-muted hover:text-fg hover:bg-[var(--color-bg-hover,var(--color-surface-hover))]")
            }
            title={title}
          >
            <span className="truncate">{title}</span>
            <span
              className="ml-0.5 shrink-0 rounded-sm p-0.5 opacity-0 transition hover:bg-[var(--color-surface-hover)] group-hover:opacity-100"
              onClick={(e) => {
                e.stopPropagation();
                closeTab(id);
              }}
              title="Close tab"
            >
              <svg
                width="10"
                height="10"
                viewBox="0 0 10 10"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.2"
              >
                <path d="M1 1l8 8M9 1l-8 8" />
              </svg>
            </span>
          </button>
        );
      })}
    </div>
  );
}
