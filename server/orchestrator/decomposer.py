"""Orchestrator task decomposition: agent scoring, domain matching, conflict detection."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from sqlalchemy import select

from db.models import Agent, ConversationMember

ORCHESTRATOR_AGENT_ID = "agent_orchestrator"

AGENT_CODE_MAP: dict[str, str] = {
    "A": "agent_mock",
    "B": "agent_mock_2",
    "C": "agent_claude",
    "D": "agent_deepseek",
}


def _agent_code_to_display_name(code: str) -> str:
    AGENT_DISPLAY_NAMES = {
        "A": "MockAdapter (frontend)",
        "B": "CustomAgentAdapter",
        "C": "ClaudeCodeAdapter",
        "D": "CodexAdapter",
    }
    return AGENT_DISPLAY_NAMES.get(code, code)


def _agent_code_to_agent_id(code: str) -> str:
    return AGENT_CODE_MAP.get(code, "agent_mock")


def _agent_capability_score(agent: Agent, domain: str) -> int:
    name_text = (agent.name or "").lower()
    adapter_text = (agent.adapter_type or "").lower()

    try:
        cfg = json.loads(agent.config) if agent.config else {}
    except (TypeError, ValueError):
        cfg = {}
    prompt_text = str(cfg.get("system_prompt", "") or "").lower()

    score = 0

    # Mock adapters should never be chosen for real work
    if adapter_text == "mock":
        score -= 999

    domain_aliases = {
        "frontend": ["ui", "html", "css", "react", "preview", "前端", "界面", "页面", "component", "vue"],
        "backend": ["api", "server", "service", "python", "后端", "接口", "路由"],
        "database": ["db", "sql", "orm", "数据库", "schema", "query"],
        "test": ["test", "qa", "verify", "quality", "测试", "验证"],
        "docs": ["doc", "readme", "writer", "文档", "写作"],
        "devops": ["ci", "deploy", "ops", "docker", "部署"],
    }

    if domain.lower() in prompt_text:
        score += 30
    score += sum(5 for alias in domain_aliases.get(domain, []) if alias in prompt_text)

    if domain.lower() in name_text:
        score += 8
    score += sum(1 for alias in domain_aliases.get(domain, []) if alias in name_text)

    if adapter_text in ("claude_code", "anthropic", "codex", "openai", "deepseek", "opencode"):
        score += 1

    try:
        cfg = json.loads(agent.config) if agent.config else {}
    except (TypeError, ValueError):
        cfg = {}
    has_api_key = bool(cfg.get("api_key")) or (adapter_text == "codex" and os.environ.get("OPENAI_API_KEY"))
    if has_api_key:
        score += 5

    return score


async def _pick_agent_for_domain(
    s: Any,
    *,
    domain: str,
    conversation_id: str,
) -> tuple[str, str]:
    member_ids = (
        await s.scalars(
            select(ConversationMember.member_id).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.member_type == "agent",
                ConversationMember.member_id != ORCHESTRATOR_AGENT_ID,
            )
        )
    ).all()
    candidates: list[Agent] = []
    if member_ids:
        candidates = (
            await s.scalars(select(Agent).where(Agent.id.in_(list(member_ids))))
        ).all()
    if not candidates:
        candidates = (
            await s.scalars(
                select(Agent).where(Agent.id != ORCHESTRATOR_AGENT_ID)
            )
        ).all()

    if not candidates:
        fallback_code = {
            "frontend": "A",
            "backend": "B",
            "database": "C",
            "test": "D",
            "docs": "D",
            "devops": "D",
        }.get(domain, "B")
        return _agent_code_to_agent_id(fallback_code), _agent_code_to_display_name(fallback_code)

    best = max(
        candidates,
        key=lambda agent: (
            _agent_capability_score(agent, domain),
            agent.created_at or 0,
        ),
    )
    return best.id, best.name


def _conflict_resolution_note(subtask_records: list[tuple[Any, str, str, str, list[str]]]) -> str:
    by_domain: dict[str, list[str]] = {}
    for st, _agent_name, _agent_id, _input_summary, _deps in subtask_records:
        if st.domain:
            by_domain.setdefault(st.domain, []).append(st.title[:60])
    overlaps = {domain: titles for domain, titles in by_domain.items() if len(titles) > 1}
    if not overlaps:
        return "Conflict resolution: no overlapping domain writes detected; artifacts can be merged directly."
    parts = []
    for domain, titles in sorted(overlaps.items()):
        parts.append(f"{domain}: {len(titles)} competing outputs kept as separate review items")
    return "Conflict resolution: " + "; ".join(parts) + "."


def _ensure_preview_collaboration_domains(user_text: str, domains: set[str]) -> set[str]:
    expanded = set(domains)
    lower = user_text.lower()

    simple_html_keywords = ["生成.*html", "写.*html", "创建.*页面", "做个.*页面", "html页面", "一个页面"]
    is_simple_html = any(re.search(k, lower) for k in simple_html_keywords)
    if is_simple_html:
        expanded.add("frontend")
        return expanded

    from orchestrator.preview import _should_create_w4_preview
    if not _should_create_w4_preview(user_text):
        return domains or {"frontend"}

    expanded.add("frontend")
    if any(k in lower for k in ["登录", "注册", "订单", "商品", "api", "接口", "应用", "app"]):
        expanded.update({"backend", "database"})
    return expanded


def _build_subtask_description(subtask: Any, decompose_result: Any) -> str:
    return subtask.description or ""


def _agent_config(agent: Agent) -> dict[str, Any]:
    try:
        return json.loads(agent.config) if agent.config else {}
    except (TypeError, ValueError):
        return {}


def _agent_can_call_model(agent: Agent) -> bool:
    cfg = _agent_config(agent)
    if cfg.get("api_key"):
        return True
    if agent.adapter_type == "codex" and os.environ.get("OPENAI_API_KEY"):
        return True
    return False
