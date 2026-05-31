import { useState } from "react";
import { useChatStore } from "../stores/useChatStore";
import type { Agent, Member } from "../types";
import { AgentCreateDialog } from "./AgentCreateDialog";

/** 领域 → 适配器代码映射表（与 server/orchestrator.py AGENT_CODE_MAP 和 server/db/seed.py 对齐） */
const AGENT_DOMAIN_MAP: Record<string, { label: string; icon: string }> = {
  agent_mock:     { label: "前端专家", icon: "🎨" },
  agent_mock_2:   { label: "后端专家", icon: "⚙️" },
  agent_claude:   { label: "数据专家", icon: "🗄️" },
  agent_deepseek: { label: "辅助Agent", icon: "🛠️" },
  agent_opencode: { label: "产品需求分析",  icon: "📋" },
};

function resolveDomain(agent: Agent): { label: string; icon: string } | null {
  return AGENT_DOMAIN_MAP[agent.id] ?? null;
}

export function MemberPanel() {
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null);
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
    <aside className="w-64 min-w-64 max-w-64 flex flex-col bg-bg border-l border-border shrink-0 overflow-hidden">
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
              {agentMembers.map((member) => {
                const domain = resolveDomain(member.agent);
                return (
                  <div
                    key={member.member_id}
                    className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-accent/10 transition-colors group"
                  >
                    <span className="w-7 h-7 rounded-lg bg-accent/20 flex items-center justify-center text-sm shrink-0 select-none">
                      {domain?.icon || member.agent.avatar || member.agent.name.charAt(0).toUpperCase()}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-fg truncate flex items-center gap-1.5">
                        {member.agent.name}
                        {domain && (
                          <span className="text-[10px] text-accent font-medium bg-accent/10 rounded px-1 py-0.5">
                            {domain.label}
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-muted truncate mt-0.5">
                        {member.agent.adapter_type}
                        {member.agent.capabilities.length > 0 && (
                          <> · {member.agent.capabilities.slice(0, 4).join(" · ")}</>
                        )}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => setEditingAgent(member.agent)}
                      className="shrink-0 w-6 h-6 rounded-md opacity-0 group-hover:opacity-100 hover:bg-accent/20 flex items-center justify-center transition-all"
                      title={`Configure ${member.agent.name}`}
                    >
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-muted">
                        <circle cx="12" cy="12" r="3" />
                        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
                      </svg>
                    </button>
                  </div>
                );
              })}
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

      <AgentCreateDialog
        open={editingAgent !== null}
        agent={editingAgent}
        onClose={() => setEditingAgent(null)}
      />
    </aside>
  );
}
