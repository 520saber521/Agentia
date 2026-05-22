import { useChatStore } from "../stores/useChatStore";
import type { Agent, Member } from "../types";

export function MemberPanel() {
  const conversations = useChatStore((s) => s.conversations);
  const agents = useChatStore((s) => s.agents);
  const currentConvId = useChatStore((s) => s.currentConvId);

  const currentConv = conversations.find((c) => c.id === currentConvId);
  const members = currentConv?.members ?? [];

  const agentMembers = members
    .filter((m) => m.member_type === "agent")
    .map((m) => ({
      ...m,
      agent: agents.find((a) => a.id === m.member_id),
    }))
    .filter((m): m is Member & { agent: Agent } => m.agent != null);

  const userMembers = members.filter((m) => m.member_type === "user");

  return (
    <aside className="w-64 flex flex-col bg-bg border-l border-border shrink-0">
      <div className="px-4 py-3 border-b border-border">
        <h3 className="text-sm font-medium text-fg">成员列表</h3>
        <p className="text-xs text-muted mt-0.5">
          {members.length} 位成员
        </p>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="px-2 py-2">
          {userMembers.length > 0 && (
            <div className="space-y-1">
              <div className="px-2 py-1 text-xs font-medium text-muted uppercase tracking-wider">
                用户
              </div>
              {userMembers.map((member) => (
                <div
                  key={member.member_id}
                  className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-accent/10 transition-colors"
                >
                  <span className="w-6 h-6 rounded-full bg-blue-500/20 flex items-center justify-center text-xs font-medium text-blue-400 shrink-0">
                    {member.member_id.charAt(0).toUpperCase()}
                  </span>
                  <span className="text-sm text-fg truncate">
                    {member.member_id.replace("user_", "")}
                  </span>
                </div>
              ))}
            </div>
          )}

          {agentMembers.length > 0 && (
            <div className="space-y-1 mt-2">
              <div className="px-2 py-1 text-xs font-medium text-muted uppercase tracking-wider">
                Agent
              </div>
              {agentMembers.map((member) => (
                <div
                  key={member.member_id}
                  className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-accent/10 transition-colors"
                >
                  <span className="w-6 h-6 rounded-full bg-accent/20 flex items-center justify-center text-xs font-medium text-accent shrink-0">
                    {member.agent.name.charAt(0).toUpperCase()}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-fg truncate">
                      {member.agent.name}
                    </div>
                    <div className="text-xs text-muted truncate">
                      {member.agent.adapter_type} · {member.agent.capabilities.slice(0, 3).join(" · ")}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {members.length === 0 && (
            <div className="px-2 py-4 text-center text-xs text-muted">
              暂无成员
            </div>
          )}
        </div>
      </div>

      <div className="px-4 py-3 border-t border-border">
        <div className="text-xs text-muted">
          会话类型: {currentConv?.type === "group" ? "群聊" : "单聊"}
        </div>
      </div>
    </aside>
  );
}
