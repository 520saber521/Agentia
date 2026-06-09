"""Sub-Agent Gate — decides when the ReAct engine should suggest delegation.

The gate evaluates whether the current task justifies creating sub-agents
and, if so, returns a contextual hint that gets injected as a system message
into the ReAct conversation history.
"""

from __future__ import annotations

MULTI_DOMAIN_PAIRS = [
    ("frontend", "backend"),
    ("ui", "api"),
    ("前端", "后端"),
    ("页面", "接口"),
    ("界面", "服务"),
    ("设计", "实现"),
    ("react", "api"),
    ("vue", "api"),
    ("html", "server"),
    ("css", "database"),
    ("样式", "数据库"),
]


class SubAgentGate:
    """Static decision gate for sub-agent delegation hints."""

    @staticmethod
    def should_suggest_delegation(
        user_text: str,
        step_count: int,
        has_sub_agents: bool,
    ) -> str | None:
        """Return a system-level hint string if delegation should be suggested, or None.

        Conditions:
        - step_count >= 2 (agent has tried at least twice on its own)
        - No sub-agents already created via ``create_agent``
        - Task contains cross-domain keywords OR is long/complex (>200 chars)
        """
        if has_sub_agents:
            return None
        if step_count < 2:
            return None

        lower = user_text.lower()
        cross_domain = any(
            a in lower and b in lower for a, b in MULTI_DOMAIN_PAIRS
        )
        complex_task = len(user_text) > 200

        if cross_domain or complex_task:
            return (
                "[系统提示] 此任务涉及多个领域或较为复杂。"
                "你可以使用 create_agent 工具创建专门的子 Agent 来并行处理不同部分"
                "（例如创建 frontend agent 处理 UI、backend agent 处理 API），"
                "然后使用 send_message 向子 Agent 传递子任务。"
                "完成后使用 list_agents 查看可用的 Agent。"
            )
        return None
