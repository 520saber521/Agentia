"""``send_message`` handler — single & group fan-out.

Extracted from ``main.py`` during W2-D1 split.

Owns:
- :func:`handle` — entry point, validates & routes
- :func:`resolve_targets` — maps mentions + conv-type to agent ids
- :func:`_run_orchestrator` — hands off to the orchestrator pipeline
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from sqlalchemy import select

from db import DEFAULT_CONV_ID, DEFAULT_USER_ID, get_sessionmaker
from db.models import Conversation, ConversationMember, new_id
from handlers.agent_ops import (
    conversation_agent_members,
    filter_available_agents,
    looks_complex_task,
    maybe_create_agent_from_chat,
)
from handlers.agent_reply import run_agent_reply
from handlers.artifact_utils import persist_final
from orchestrator import ORCHESTRATOR_AGENT_ID, handle_orchestrator_mention
from services import create_message, message_to_dict
from services.trace import create_trace_entry as create_trace
from ws import Connection, event

logger = logging.getLogger("agenthub.handlers.send_message")


async def resolve_targets(
    conversation_id: str,
    mentions: list[str],
    user_text: str,
) -> tuple[list[str], dict[str, Any] | None]:
    """Determine which agents to fan-out to based on conv type + mentions.

    Returns ``(target_agent_ids, error_event)``.
    See ``ai-collab/SPEC.md`` F-W2-1 for the exact semantics.
    """
    Session = get_sessionmaker()
    async with Session() as s:
        conv = await s.get(Conversation, conversation_id)
        if conv is None:
            return [], event(
                "error",
                code="not_found",
                message=f"conversation {conversation_id} not found",
            )
        members = (
            await s.scalars(
                select(ConversationMember).where(
                    ConversationMember.conversation_id == conversation_id
                )
            )
        ).all()
        agent_member_ids = {
            m.member_id for m in members if m.member_type == "agent"
        }
        conv_type = conv.type

    requested: list[str] = []
    seen: set[str] = set()
    for aid in mentions:
        if isinstance(aid, str) and aid and aid not in seen:
            seen.add(aid)
            requested.append(aid)

    if requested:
        valid = [aid for aid in requested if aid in agent_member_ids]
        unknown = [aid for aid in requested if aid not in agent_member_ids]
        if unknown and not valid:
            return [], event(
                "error",
                code="not_member",
                message=f"agents not in conversation: {unknown}",
            )
        if unknown:
            return valid, event(
                "error",
                code="not_member",
                message=f"agents not in conversation: {unknown}",
                degraded=True,
            )
        return valid, None

    if conv_type == "single":
        if not agent_member_ids:
            return [], event(
                "error",
                code="no_agent",
                message="no agent in conversation",
            )
        return [next(iter(agent_member_ids))], None

    if "@" in user_text:
        if "@orchestrator" in user_text.lower() or "@任务编排器" in user_text:
            if ORCHESTRATOR_AGENT_ID in agent_member_ids:
                return [ORCHESTRATOR_AGENT_ID], None
        return [], event(
            "error",
            code="bad_mentions",
            message="text contains @ but mentions[] is empty",
        )
    if ORCHESTRATOR_AGENT_ID in agent_member_ids and looks_complex_task(user_text):
        return [ORCHESTRATOR_AGENT_ID], None
    if conv_type == "group" and len(agent_member_ids) > 1:
        available = await filter_available_agents(list(agent_member_ids))
        if not available:
            return [ORCHESTRATOR_AGENT_ID] if ORCHESTRATOR_AGENT_ID in agent_member_ids else [], None
        if ORCHESTRATOR_AGENT_ID in agent_member_ids:
            if ORCHESTRATOR_AGENT_ID not in available:
                available.insert(0, ORCHESTRATOR_AGENT_ID)
        return available, None
    return [], event(
        "error",
        code="no_target",
        message="group conversation requires explicit @mentions or a complex task for Orchestrator",
    )


async def handle(conn: Connection, evt: dict[str, Any]) -> None:
    content = evt.get("content") or {}
    user_text = content.get("text") if isinstance(content, dict) else None
    if not isinstance(user_text, str) or not user_text.strip():
        await conn.send(
            event(
                "error",
                code="bad_content",
                message="send_message.content.text must be non-empty string",
            )
        )
        return

    conversation_id = evt.get("conversation_id") or DEFAULT_CONV_ID
    if await maybe_create_agent_from_chat(conn, conversation_id, user_text):
        return

    raw_mentions = evt.get("mentions") or []
    if not isinstance(raw_mentions, list):
        await conn.send(
            event(
                "error",
                code="bad_mentions",
                message="send_message.mentions must be a list",
            )
        )
        return

    target_agent_ids, err = await resolve_targets(
        conversation_id, [str(x) for x in raw_mentions], user_text
    )
    if err is not None:
        await conn.send(err)
        if not target_agent_ids:
            return

    if not target_agent_ids:
        return

    # Generate a shared trace_id for this fan-out
    trace_id = new_id("trace")
    seq_counter = 0

    Session = get_sessionmaker()
    async with Session() as s:
        user_msg = await create_message(
            s,
            conversation_id=conversation_id,
            sender_id=DEFAULT_USER_ID,
            sender_type="user",
            content={"type": "text", "text": user_text},
            mentions=target_agent_ids,
        )
        user_msg_dict = message_to_dict(user_msg)
        agent_msgs: list[tuple[str, str, dict[str, Any]]] = []
        for aid in target_agent_ids:
            am = await create_message(
                s,
                conversation_id=conversation_id,
                sender_id=aid,
                sender_type="agent",
                content={"type": "text", "text": ""},
            )
            agent_msgs.append((aid, am.id, message_to_dict(am)))

        # Record user message trace entry
        await create_trace(
            s,
            message_id=user_msg.id,
            conversation_id=conversation_id,
            trace_id=trace_id,
            node_id=DEFAULT_USER_ID,
            node_role="user",
            event="send_message",
            seq=seq_counter,
        )

    # Try to route through Router (F-W3-1)
    from router_client import get_router_client
    router = get_router_client()
    router_ok = await router.health()

    async with Session() as s:
        for idx, (aid, mid, _mdict) in enumerate(agent_msgs):
            seq_counter += 1
            detail_json = json.dumps({
                "agent_id": aid,
                "message_id": mid,
                "user_text": user_text[:200],
            })

            if router_ok:
                try:
                    router_resp = await router.send_message({
                        "trace_id": trace_id,
                        "conversation_id": conversation_id,
                        "agent_id": aid,
                        "message_id": mid,
                        "content": user_text,
                    })
                    await create_trace(
                        s,
                        message_id=mid,
                        conversation_id=conversation_id,
                        trace_id=trace_id,
                        node_id="router",
                        node_role="router",
                        event="dispatch",
                        status="ok",
                        detail=detail_json,
                        seq=seq_counter,
                    )
                except Exception as exc:
                    router_ok = False
                    await create_trace(
                        s,
                        message_id=mid,
                        conversation_id=conversation_id,
                        trace_id=trace_id,
                        node_id="router",
                        node_role="router",
                        event="dispatch",
                        status="failed",
                        detail=str(exc),
                        seq=seq_counter,
                    )
            else:
                await create_trace(
                    s,
                    message_id=mid,
                    conversation_id=conversation_id,
                    trace_id=trace_id,
                    node_id="bff",
                    node_role="bff",
                    event="dispatch_direct",
                    status="ok" if not router_ok else "degraded",
                    detail=detail_json,
                    seq=seq_counter,
                )

    await conn.send(event("message_created", message=user_msg_dict))
    for _aid, _mid, mdict in agent_msgs:
        await conn.send(event("message_created", message=mdict))

    has_orchestrator = ORCHESTRATOR_AGENT_ID in target_agent_ids
    non_orch_agents = [a for a in target_agent_ids if a != ORCHESTRATOR_AGENT_ID]

    active_count = len(agent_msgs)
    active_lock = asyncio.Lock()

    async def _on_agent_done(mid: str) -> None:
        nonlocal active_count
        async with active_lock:
            active_count -= 1
            if active_count == 0:
                await conn.send(
                    event(
                        "fan_out_done",
                        conversation_id=conversation_id,
                        total_agents=len(agent_msgs),
                    )
                )
                logger.debug(
                    "ws[%s] fan-out complete for conv=%s (%d agents)",
                    conn.conn_id, conversation_id, len(agent_msgs),
                )

    async def _wrap_agent_task(coro, mid: str) -> None:
        try:
            await coro
        finally:
            await _on_agent_done(mid)

    for aid, mid, _mdict in agent_msgs:
        if aid == ORCHESTRATOR_AGENT_ID:
            coro = _run_orchestrator(conn, mid, conversation_id, user_text, target_agent_ids)
            task = asyncio.create_task(
                _wrap_agent_task(coro, mid),
                name=f"orchestrator-{mid}",
            )
        else:
            coro = run_agent_reply(conn, aid, mid, conversation_id, user_text)
            task = asyncio.create_task(
                _wrap_agent_task(coro, mid),
                name=f"agent-reply-{mid}",
            )
        conn.in_flight[mid] = task
        task.add_done_callback(
            lambda _t, _m=mid: conn.in_flight.pop(_m, None)
        )

    if has_orchestrator and non_orch_agents:
        logger.info(
            "Orchestrator + %d other agents mentioned in same message",
            len(non_orch_agents),
        )


async def _run_orchestrator(
    conn: Connection,
    ai_msg_id: str,
    conversation_id: str,
    user_text: str,
    target_agent_ids: list[str],
) -> None:
    """Handle a message sent to @Orchestrator.

    The Orchestrator doesn't stream text through the normal adapter path.
    Instead, it runs task decomposition and emits task_update events.
    We still emit a brief message_done so the frontend sees the bubble.
    """
    await conn.send(
        event("agent_typing", agent_id=ORCHESTRATOR_AGENT_ID, conversation_id=conversation_id)
    )

    try:
        await handle_orchestrator_mention(
            conn=conn,
            conversation_id=conversation_id,
            user_text=user_text,
            mentions=target_agent_ids,
            originating_message_id=ai_msg_id,
        )

        Session = get_sessionmaker()
        await persist_final(Session, ai_msg_id, f"✅ Orchestrator completed coordination for: {user_text[:100]}")
    except asyncio.CancelledError:
        Session = get_sessionmaker()
        await persist_final(Session, ai_msg_id, "[cancelled]")
        await conn.send(
            event(
                "message_cancelled",
                message_id=ai_msg_id,
                sender_id=ORCHESTRATOR_AGENT_ID,
                conversation_id=conversation_id,
                final_content={"type": "text", "text": "[cancelled]"},
            )
        )
        raise
    except Exception as exc:
        logger.exception("orchestrator[%s] crashed", ai_msg_id)
        Session = get_sessionmaker()
        await persist_final(Session, ai_msg_id, f"[error] {exc}")
        await conn.send(
            event(
                "error",
                message_id=ai_msg_id,
                sender_id=ORCHESTRATOR_AGENT_ID,
                conversation_id=conversation_id,
                code="orchestrator_crash",
                message=str(exc),
            )
        )
