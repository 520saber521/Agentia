"""Agent 业务封装。

W2 F-W2-5 起：暴露 ``list_agents`` 给 ``GET /api/agents``，前端用它在
"新建群聊"模态里列出可选 Agent。

后续：
- W2-T3 加 ``check_agents_exist`` 给 ``create_conversation`` 用（agent_ids 校验）。
- W5 F-W5-1 加 ``create_agent`` / ``delete_agent`` 给"用户自建 Agent"。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import asc, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Agent

logger = logging.getLogger("agenthub.services.agent")


ORCHESTRATOR_SYSTEM_PROMPT = """【身份】你是 Orchestrator 协作协调 Agent，负责多 Agent 团队的任务拆解、分派与汇总。

【核心职责 — 最高优先级】
1. 接收用户需求，拆解为多个领域子任务
2. 为每个子任务匹配合适的领域 Agent
3. 汇总各 Agent 输出，生成完整的协作交付物

【工作流程】
- 分析需求 → 拆解子任务 → 分配 Agent → 汇总结果
- 不可直接执行子任务本身，必须分配给其他 Agent"""


def adapter_config_for_runtime(agent: Agent) -> dict[str, Any]:
    try:
        return json.loads(agent.config) if agent.config else {}
    except (TypeError, ValueError):
        return {}


async def record_agent_execution_start(
    s: AsyncSession,
    conversation_id: str,
    message_id: str,
    agent_id: str,
    input_summary: str,
) -> None:
    logger.info("execution start: agent=%s conv=%s msg=%s", agent_id, conversation_id, message_id)


async def record_agent_execution_finish(
    s: AsyncSession,
    message_id: str,
    status: str,
    output_summary: str,
    error: str | None = None,
) -> None:
    logger.info("execution finish: msg=%s status=%s", message_id, status)


def _safe_parse_json(val: str | None, default: Any = None) -> Any:
    """安全解析 JSON 字符串，解析失败返回 default。"""
    if not val:
        return default
    try:
        return json.loads(val)
    except (TypeError, ValueError):
        return default


def _mask_key(key: str) -> str:
    """对 API key 做掩码处理，只保留前后各 4 位。"""
    if not key or len(key) < 8:
        return "****"
    return key[:4] + "****" + key[-4:]


def agent_to_dict(a: Agent) -> dict[str, Any]:
    """ORM -> 对外 dict。capabilities / config 是 DB 里的 JSON 字符串，这里解开。

    config 不暴露给前端的字段统一在这里黑名单化（W5 起接 API key 等敏感配置时关键）。
    """
    capabilities = _safe_parse_json(a.capabilities, [])
    if not isinstance(capabilities, list):
        capabilities = []

    config = _safe_parse_json(a.config, {})
    if not isinstance(config, dict):
        config = {}

    api_key = config.get("api_key", "") or ""
    tools = config.get("tools", [])

    return {
        "id": a.id,
        "name": a.name,
        "avatar": a.avatar,
        "adapter_type": a.adapter_type,
        "model": config.get("model", ""),
        "base_url": config.get("base_url", ""),
        "system_prompt": config.get("system_prompt", ""),
        "tools": tools if isinstance(tools, list) else [],
        "capabilities": capabilities,
        "api_key_configured": bool(api_key),
        "api_key_mask": _mask_key(api_key) if api_key else "",
        "is_system": bool(a.is_system),
        "locked_prompt": bool(a.locked_prompt),
        "can_delete": not bool(a.is_system),
        "owner_user_id": a.owner_user_id,
        "created_at": a.created_at,
        "updated_at": a.updated_at,
    }


async def list_agents(s: AsyncSession) -> list[dict[str, Any]]:
    """按 name 升序列出所有 Agent。"""
    rows = (await s.scalars(select(Agent).order_by(asc(Agent.name)))).all()
    return [agent_to_dict(a) for a in rows]


async def get_existing_agent_ids(
    s: AsyncSession, agent_ids: list[str]
) -> set[str]:
    """返回 agent_ids 中实际存在于 agent 表的 id 集合。

    上层用 set(agent_ids) - get_existing_agent_ids(...) 算未知集合。
    """
    if not agent_ids:
        return set()
    rows = (
        await s.scalars(select(Agent.id).where(Agent.id.in_(agent_ids)))
    ).all()
    return set(rows)


async def create_agent(
    s: AsyncSession,
    name: str,
    adapter_type: str,
    config: dict[str, Any],
    capabilities: list[str],
    avatar: str | None = None,
    owner_user_id: str | None = None,
) -> dict[str, Any]:
    """创建新的 Agent。"""
    from db.models import new_id

    agent = Agent(
        id=new_id("agent"),
        name=name,
        avatar=avatar,
        adapter_type=adapter_type,
        config=json.dumps(config),
        capabilities=json.dumps(capabilities),
        owner_user_id=owner_user_id,
    )
    s.add(agent)
    await s.commit()
    await s.refresh(agent)
    return agent_to_dict(agent)


async def update_agent(
    s: AsyncSession,
    agent_id: str,
    name: str | None = None,
    avatar: str | None = None,
    adapter_type: str | None = None,
    config: dict[str, Any] | None = None,
    capabilities: list[str] | None = None,
) -> dict[str, Any] | None:
    """更新 Agent 信息。"""
    agent = await s.get(Agent, agent_id)
    if agent is None:
        return None

    if name is not None:
        agent.name = name
    if avatar is not None:
        agent.avatar = avatar
    if adapter_type is not None:
        agent.adapter_type = adapter_type
    if config is not None:
        agent.config = json.dumps(config)
    if capabilities is not None:
        agent.capabilities = json.dumps(capabilities)

    await s.commit()
    await s.refresh(agent)
    return agent_to_dict(agent)


async def delete_agent(s: AsyncSession, agent_id: str) -> str:
    """删除 Agent。返回 'ok' | 'not_found' | 'protected'。"""
    agent = await s.get(Agent, agent_id)
    if agent is None:
        return "not_found"

    if agent.id == "agent_orchestrator":
        return "protected"

    await s.delete(agent)
    await s.commit()
    return "ok"


async def list_agent_executions(
    s: AsyncSession, agent_id: str, limit: int = 50
) -> list[dict[str, Any]]:
    """列出 Agent 的执行记录。（W3 功能，当前返回空列表）"""
    return []
