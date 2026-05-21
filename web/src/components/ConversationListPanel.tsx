import { useState } from "react";

import { useChatStore } from "../stores/useChatStore";
import { NewConversationDialog } from "./NewConversationDialog";

export function ConversationListPanel() {
  const items = useChatStore((s) => s.conversations);
  const current = useChatStore((s) => s.currentConvId);
  const select = useChatStore((s) => s.selectConversation);
  const refresh = useChatStore((s) => s.refreshConversations);

  const [showCreate, setShowCreate] = useState(false);

  return (
    <aside className="bg-panel flex flex-col min-h-0">
      <div className="px-4 h-12 flex items-center justify-between border-b border-border shrink-0">
        <h2 className="text-xs uppercase tracking-[0.08em] text-muted font-semibold">
          会话
        </h2>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowCreate(true)}
            className="text-xs px-2 py-1 rounded-md border border-border text-muted hover:text-fg hover:border-accent/60 transition"
            title="新建会话"
          >
            ＋ 新建
          </button>
          <button
            onClick={() => void refresh()}
            className="text-xs text-muted hover:text-fg transition"
          >
            刷新
          </button>
        </div>
      </div>
      <NewConversationDialog
        open={showCreate}
        onClose={() => setShowCreate(false)}
      />
      <ul className="flex-1 overflow-y-auto p-2 space-y-1">
        {items.length === 0 && (
          <li className="px-3 py-4 text-xs text-muted">(无会话)</li>
        )}
        {items.map((c) => {
          const active = c.id === current;
          return (
            <li key={c.id}>
              <button
                type="button"
                onClick={() => void select(c.id)}
                className={`w-full text-left p-3 rounded-md border transition ${
                  active
                    ? "border-accent bg-accent/10"
                    : "border-border hover:border-accent/60"
                }`}
              >
                <div className="font-medium text-sm text-fg truncate">
                  {c.title}
                </div>
                <div className="text-xs text-muted truncate mt-1">
                  {c.last_msg_preview || "(暂无消息)"}
                </div>
                <div className="text-[10.5px] text-muted mt-1 truncate">
                  {c.type} · {c.members.length} 成员 · {c.id}
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
