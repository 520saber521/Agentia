"""Agent utility functions — loading, filtering, creation from chat."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import select

from adapters import build_adapter
from db import DEFAULT_USER_ID, get_sessionmaker
from db.models import Agent, ConversationMember
from orchestrator import ORCHESTRATOR_AGENT_ID
from services import create_message, message_to_dict
from services.agent import adapter_config_for_runtime, create_agent, list_agents
from ws import Connection, event

logger = logging.getLogger("agenthub.handlers.agent_ops")

_NO_API_KEY_ADAPTERS = {"mock", "claude_code", "opencode"}


async def filter_available_agents(agent_ids: list[str]) -> list[str]:
    Session = get_sessionmaker()
    async with Session() as s:
        rows = (
            await s.scalars(select(Agent).where(Agent.id.in_(agent_ids)))
        ).all()
    available: list[str] = []
    for a in rows:
        if a.id == ORCHESTRATOR_AGENT_ID:
            available.append(a.id)
            continue
        adapter_type = (a.adapter_type or "").strip().lower()
        config = adapter_config_for_runtime(a)
        if adapter_type in _NO_API_KEY_ADAPTERS:
            available.append(a.id)
        elif config.get("api_key"):
            available.append(a.id)
        else:
            logger.debug("skipping agent %s (%s): no api_key", a.id, a.name)
    return available


async def conversation_agent_members(conversation_id: str) -> set[str]:
    Session = get_sessionmaker()
    async with Session() as s:
        rows = (
            await s.scalars(
                select(ConversationMember).where(
                    ConversationMember.conversation_id == conversation_id,
                    ConversationMember.member_type == "agent",
                )
            )
        ).all()
    return {row.member_id for row in rows}


def looks_complex_task(user_text: str) -> bool:
    lower = user_text.lower()
    keywords = [
        "设计", "实现", "开发", "拆", "分派", "网页", "页面", "html", "web", "应用",
        "前端", "后端", "数据", "接口", "测试", "订单", "登录", "注册", "商品",
        "orchestrator", "协调", "多 agent", "multi-agent",
    ]
    return len(user_text) >= 24 or any(k in lower for k in keywords)


async def load_adapter_for(agent_id: str) -> tuple[Any, str] | None:
    Session = get_sessionmaker()
    async with Session() as s:
        row = await s.get(Agent, agent_id)
        if row is None:
            return None
        adapter_type = row.adapter_type
        name = row.name
        config = adapter_config_for_runtime(row)

    try:
        adapter = build_adapter(adapter_type, config)
    except ValueError:
        return None
    return adapter, name


def parse_agent_create_request(user_text: str) -> dict[str, Any] | None:
    text = user_text.strip()
    lower = text.lower()
    if not (
        lower.startswith("/agent create")
        or lower.startswith("create agent")
        or lower.startswith("创建agent")
        or lower.startswith("新建agent")
    ):
        return None

    body = re.sub(
        r"^(/agent\s+create|create\s+agent|创建agent|新建agent)\s*[:：-]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    if not body:
        return None

    fields: dict[str, str] = {}
    for part in re.split(r"\s+[|;]\s+|\n+", body):
        if ":" not in part and "：" not in part:
            continue
        key, value = re.split(r"[:：]", part, maxsplit=1)
        fields[key.strip().lower()] = value.strip()

    name = fields.get("name") or fields.get("名称") or body.splitlines()[0].split("|")[0].strip()
    adapter_type = fields.get("adapter") or fields.get("adapter_type") or fields.get("平台") or "codex"
    model = fields.get("model") or fields.get("模型") or ""
    system_prompt = fields.get("prompt") or fields.get("system_prompt") or fields.get("提示词") or ""
    capabilities_raw = fields.get("capabilities") or fields.get("tags") or fields.get("能力") or "code"
    capabilities = [x.strip() for x in re.split(r"[,，/]", capabilities_raw) if x.strip()]

    return {
        "name": name[:80] or "Custom Agent",
        "adapter_type": adapter_type,
        "model": model,
        "system_prompt": system_prompt,
        "capabilities": capabilities or ["code"],
    }


async def maybe_create_agent_from_chat(
    conn: Connection,
    conversation_id: str,
    user_text: str,
) -> bool:
    parsed = parse_agent_create_request(user_text)
    if parsed is None:
        return False

    Session = get_sessionmaker()
    async with Session() as s:
        user_msg = await create_message(
            s,
            conversation_id=conversation_id,
            sender_id=DEFAULT_USER_ID,
            sender_type="user",
            content={"type": "text", "text": user_text},
        )
        config = {
            key: parsed[key]
            for key in ("model", "system_prompt")
            if parsed.get(key)
        }
        agent = await create_agent(
            s,
            name=parsed["name"],
            adapter_type=parsed["adapter_type"],
            config=config,
            capabilities=parsed["capabilities"],
            owner_user_id=DEFAULT_USER_ID,
        )
        reply = await create_message(
            s,
            conversation_id=conversation_id,
            sender_id=ORCHESTRATOR_AGENT_ID,
            sender_type="agent",
            content={
                "type": "text",
                "text": (
                    f"Created Agent `{agent['name']}` with adapter `{agent['adapter_type']}` "
                    f"and tags: {', '.join(agent['capabilities'])}."
                ),
            },
        )
        agents = await list_agents(s)

    await conn.send(event("message_created", message=message_to_dict(user_msg)))
    await conn.send(event("message_created", message=message_to_dict(reply)))
    await conn.send(event(
        "message_done",
        message_id=reply.id,
        sender_id=ORCHESTRATOR_AGENT_ID,
        conversation_id=conversation_id,
        final_content=json.loads(reply.content),
    ))
    await conn.send(event("agents", agents=agents))
    return True
