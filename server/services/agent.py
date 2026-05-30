from __future__ import annotations

import json
import time
from typing import Any, Optional

from sqlalchemy import asc, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Agent, AgentExecution, new_id
from services.secrets import decrypt_secret, encrypt_secret, mask_secret

ORCHESTRATOR_AGENT_ID = "agent_orchestrator"
ORCHESTRATOR_SYSTEM_PROMPT = """你是 Agentia 的 Orchestrator，负责在群聊中理解用户意图、拆解复杂任务、选择合适的子 Agent 并行执行、聚合结果、识别失败与代码冲突并给出降级方案。你必须保持协调者身份，不直接伪造子 Agent 的专业结论。

【协调规则】
- 拆解任务后，每个子任务必须指定一个明确的单一领域：frontend/backend/database/test/docs/devops
- 向子 Agent 分派任务时，明确告知只做其领域内的工作，不要越界
- 汇总时不要逐条重复子任务列表，直接说明完成情况和关键产出
- 不要重复输出已由子 Agent 输出的内容

当用户请求"部署"或"deploy"时，检测项目类型并创建 devops 子任务来构建项目（npm install && npm run build），构建完成后返回预览 URL。"""

SENSITIVE_CONFIG_KEYS = {"api_key"}


def _loads_json(value: str | None, fallback: Any) -> Any:
    try:
        data = json.loads(value) if value else fallback
        return data if data is not None else fallback
    except (TypeError, ValueError):
        return fallback


def _normalize_config(config: Optional[dict[str, Any]], *, existing: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    merged = dict(existing or {})
    for key, value in (config or {}).items():
        if value is None:
            continue
        if key == "api_key":
            if str(value).strip():
                merged[key] = encrypt_secret(str(value))
            continue
        merged[key] = value
    return merged


def adapter_config_for_runtime(a: Agent) -> dict[str, Any]:
    config = _loads_json(a.config, {})
    if not isinstance(config, dict):
        return {}
    runtime = dict(config)
    if "api_key" in runtime:
        runtime["api_key"] = decrypt_secret(str(runtime.get("api_key") or ""))
    return runtime


def agent_to_dict(a: Agent) -> dict[str, Any]:
    capabilities = _loads_json(a.capabilities, [])
    if not isinstance(capabilities, list):
        capabilities = []

    config = _loads_json(a.config, {})
    if not isinstance(config, dict):
        config = {}

    is_orchestrator = a.id == ORCHESTRATOR_AGENT_ID
    locked_prompt = bool(a.locked_prompt or is_orchestrator)
    system_prompt = ORCHESTRATOR_SYSTEM_PROMPT if is_orchestrator else str(config.get("system_prompt") or "")
    api_key_value = str(config.get("api_key") or "")
    tools = config.get("tools") or []
    if not isinstance(tools, list):
        tools = []
    return {
        "id": a.id,
        "name": a.name,
        "avatar": a.avatar,
        "adapter_type": a.adapter_type,
        "model": str(config.get("model") or ""),
        "base_url": str(config.get("base_url") or ""),
        "system_prompt": system_prompt,
        "tools": [str(tool) for tool in tools],
        "capabilities": [str(cap) for cap in capabilities],
        "api_key_configured": bool(decrypt_secret(api_key_value)),
        "api_key_mask": mask_secret(api_key_value),
        "is_system": bool(a.is_system or is_orchestrator),
        "locked_prompt": locked_prompt,
        "can_delete": not is_orchestrator,
        "owner_user_id": a.owner_user_id,
        "created_at": a.created_at,
        "updated_at": a.updated_at,
    }


async def list_agents(s: AsyncSession) -> list[dict[str, Any]]:
    rows = (await s.scalars(select(Agent).order_by(asc(Agent.name)))).all()
    return [agent_to_dict(a) for a in rows]


async def get_existing_agent_ids(s: AsyncSession, agent_ids: list[str]) -> set[str]:
    if not agent_ids:
        return set()
    rows = (await s.scalars(select(Agent.id).where(Agent.id.in_(agent_ids)))).all()
    return set(rows)


async def create_agent(
    s: AsyncSession,
    *,
    name: str,
    adapter_type: str = "mock",
    config: Optional[dict[str, Any]] = None,
    capabilities: Optional[list[str]] = None,
    avatar: Optional[str] = None,
    owner_user_id: Optional[str] = None,
    is_system: bool = False,
    locked_prompt: bool = False,
    agent_id: str | None = None,
) -> dict[str, Any]:
    now = int(time.time() * 1000)
    final_id = agent_id or new_id("agent")
    final_config = _normalize_config(config or {})
    if final_id == ORCHESTRATOR_AGENT_ID:
        final_config["system_prompt"] = ORCHESTRATOR_SYSTEM_PROMPT
        is_system = True
        locked_prompt = True
    agent = Agent(
        id=final_id,
        name=name.strip() or "Custom Agent",
        avatar=avatar,
        adapter_type=(adapter_type or "mock").strip(),
        config=json.dumps(final_config, ensure_ascii=False),
        capabilities=json.dumps(capabilities or ["text"], ensure_ascii=False),
        owner_user_id=owner_user_id,
        is_system=1 if is_system else 0,
        locked_prompt=1 if locked_prompt else 0,
        created_at=now,
        updated_at=now,
    )
    s.add(agent)
    await s.commit()
    return agent_to_dict(agent)


async def update_agent(
    s: AsyncSession,
    agent_id: str,
    *,
    name: Optional[str] = None,
    avatar: Optional[str] = None,
    adapter_type: Optional[str] = None,
    config: Optional[dict[str, Any]] = None,
    capabilities: Optional[list[str]] = None,
) -> Optional[dict[str, Any]]:
    agent = await s.get(Agent, agent_id)
    if agent is None:
        return None
    is_orchestrator = agent.id == ORCHESTRATOR_AGENT_ID
    if name is not None and not is_orchestrator:
        agent.name = name.strip() or agent.name
    if avatar is not None:
        agent.avatar = avatar
    if adapter_type is not None:
        agent.adapter_type = adapter_type.strip() or agent.adapter_type
    prompt_locked = bool(is_orchestrator or agent.locked_prompt)
    if config is not None:
        existing_cfg = _loads_json(agent.config, {})
        if not isinstance(existing_cfg, dict):
            existing_cfg = {}
        next_config = dict(config)
        if prompt_locked:
            next_config.pop("system_prompt", None)
        existing_cfg = _normalize_config(next_config, existing=existing_cfg)
        if is_orchestrator:
            existing_cfg["system_prompt"] = ORCHESTRATOR_SYSTEM_PROMPT
        agent.config = json.dumps(existing_cfg, ensure_ascii=False)
    if capabilities is not None and not is_orchestrator:
        agent.capabilities = json.dumps(capabilities, ensure_ascii=False)
    agent.updated_at = int(time.time() * 1000)
    await s.commit()
    return agent_to_dict(agent)


async def delete_agent(s: AsyncSession, agent_id: str) -> str:
    agent = await s.get(Agent, agent_id)
    if agent is None:
        return "not_found"
    if agent.id == ORCHESTRATOR_AGENT_ID:
        return "protected"
    await s.delete(agent)
    await s.commit()
    return "deleted"


async def record_agent_execution_start(
    s: AsyncSession,
    *,
    conversation_id: str,
    message_id: str,
    agent_id: str,
    input_summary: str,
) -> AgentExecution:
    row = AgentExecution(
        id=new_id("exec"),
        conversation_id=conversation_id,
        message_id=message_id,
        agent_id=agent_id,
        status="running",
        input_summary=input_summary[:2000],
        started_at=int(time.time() * 1000),
    )
    s.add(row)
    await s.commit()
    return row


async def record_agent_execution_finish(
    s: AsyncSession,
    *,
    message_id: str,
    status: str,
    output_summary: str = "",
    error: str = "",
) -> None:
    row = await s.scalar(
        select(AgentExecution).where(AgentExecution.message_id == message_id).order_by(desc(AgentExecution.started_at))
    )
    if row is None:
        return
    row.status = status
    row.output_summary = output_summary[:4000] if output_summary else None
    row.error = error[:4000] if error else None
    row.finished_at = int(time.time() * 1000)
    await s.commit()


async def list_agent_executions(s: AsyncSession, agent_id: str, limit: int = 50) -> list[dict[str, Any]]:
    rows = (
        await s.scalars(
            select(AgentExecution)
            .where(AgentExecution.agent_id == agent_id)
            .order_by(desc(AgentExecution.started_at))
            .limit(limit)
        )
    ).all()
    return [
        {
            "id": row.id,
            "conversation_id": row.conversation_id,
            "message_id": row.message_id,
            "agent_id": row.agent_id,
            "status": row.status,
            "input_summary": row.input_summary,
            "output_summary": row.output_summary,
            "error": row.error,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
        }
        for row in rows
    ]
