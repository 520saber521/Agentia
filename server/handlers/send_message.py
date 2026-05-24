"""``send_message`` handler — single & group fan-out.

Extracted from ``main.py`` during W2-D1 split.

Owns:
- :func:`handle` — entry point, validates & routes
- :func:`resolve_targets` — maps mentions + conv-type to agent ids
- :func:`load_adapter_for` — loads AgentAdapter from DB row
- :func:`run_agent_reply` — drives single-agent streaming loop
- :func:`persist_final` — writes final text back to DB
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from sqlalchemy import select

from adapters import build_adapter
from db import DEFAULT_CONV_ID, DEFAULT_USER_ID, get_sessionmaker
from db.models import Agent, Conversation, ConversationMember, new_id
from orchestrator import ORCHESTRATOR_AGENT_ID, handle_orchestrator_mention
from services import create_message, list_messages, message_to_dict, update_message_content
from ws import Connection, event

logger = logging.getLogger("agenthub.handlers.send_message")

AGENT_TIMEOUT_S = 120


def _build_messages_context(
    history: list[dict[str, Any]],
    current_user_text: str,
) -> list[dict[str, str]]:
    """Convert DB message history + current message to OpenAI-style message list.

    Args:
        history: List of message dicts from ``list_messages()``, ordered by created_at ASC.
        current_user_text: The user's latest message text.

    Returns:
        OpenAI-style messages list with role and content fields.
    """
    messages: list[dict[str, str]] = []
    for msg in history:
        content = msg.get("content", {})
        if isinstance(content, dict):
            text = content.get("text", "")
        elif isinstance(content, str):
            text = content
        else:
            text = str(content)

        sender_type = msg.get("sender_type", "user")
        role = "assistant" if sender_type == "agent" else "user"
        messages.append({"role": role, "content": text})
    messages.append({"role": "user", "content": current_user_text})
    return messages


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
        return [], event(
            "error",
            code="bad_mentions",
            message="text contains @ but mentions[] is empty",
        )
    return [], event(
        "error",
        code="no_target",
        message="group conversation requires explicit @mentions until W3",
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

    await conn.send(event("message_created", message=user_msg_dict))
    for _aid, _mid, mdict in agent_msgs:
        await conn.send(event("message_created", message=mdict))

    has_orchestrator = ORCHESTRATOR_AGENT_ID in target_agent_ids
    non_orch_agents = [a for a in target_agent_ids if a != ORCHESTRATOR_AGENT_ID]

    for aid, mid, _mdict in agent_msgs:
        if aid == ORCHESTRATOR_AGENT_ID:
            task = asyncio.create_task(
                _run_orchestrator(conn, mid, conversation_id, user_text, target_agent_ids),
                name=f"orchestrator-{mid}",
            )
        else:
            task = asyncio.create_task(
                run_agent_reply(conn, aid, mid, conversation_id, user_text),
                name=f"agent-reply-{mid}",
            )
        conn.in_flight[mid] = task
        task.add_done_callback(
            lambda _t, _m=mid: conn.in_flight.pop(_m, None)
        )

    # If Orchestrator is mentioned alongside other agents, also fan-out
    if has_orchestrator and non_orch_agents:
        logger.info(
            "Orchestrator + %d other agents mentioned in same message",
            len(non_orch_agents),
        )


async def load_adapter_for(agent_id: str) -> tuple[Any, str] | None:
    """Load ``(adapter_instance, agent_display_name)`` from DB row.

    Returns ``None`` if agent not found or config is broken.
    """
    Session = get_sessionmaker()
    async with Session() as s:
        row = await s.get(Agent, agent_id)
        if row is None:
            return None
        try:
            config = json.loads(row.config) if row.config else {}
        except json.JSONDecodeError:
            config = {}
        adapter_type = row.adapter_type
        name = row.name

    try:
        adapter = build_adapter(adapter_type, config)
    except ValueError:
        return None
    return adapter, name


async def _iterate_with_timeout(agen, timeout_s: float):
    """Wrap an async generator so total iteration time is bounded by ``timeout_s``."""
    it = agen.__aiter__()
    deadline = asyncio.get_event_loop().time() + timeout_s
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError()
        try:
            chunk = await asyncio.wait_for(it.__anext__(), remaining)
            yield chunk
        except StopAsyncIteration:
            return


async def run_agent_reply(
    conn: Connection,
    agent_id: str,
    ai_msg_id: str,
    conversation_id: str,
    user_text: str,
) -> None:
    """Drive a single agent's streaming reply (may be one of N concurrent fan-out tasks).

    All outbound events include ``message_id`` + ``sender_id`` for frontend routing.
    """
    loaded = await load_adapter_for(agent_id)
    if loaded is None:
        await conn.send(
            event(
                "error",
                message_id=ai_msg_id,
                conversation_id=conversation_id,
                code="adapter_init_failed",
                message=f"cannot init adapter for agent {agent_id!r}",
            )
        )
        return
    adapter, _agent_name = loaded

    await conn.send(
        event("agent_typing", agent_id=agent_id, conversation_id=conversation_id)
    )

    final_parts: list[str] = []
    seq = 0
    Session = get_sessionmaker()

    async with Session() as s:
        history = await list_messages(s, conversation_id, limit=50)

    messages_context = _build_messages_context(history, user_text)

    try:
        async for chunk in _iterate_with_timeout(
            adapter.send(messages=messages_context), AGENT_TIMEOUT_S
        ):
            ctype = chunk.get("type")
            if ctype == "text":
                seq += 1
                delta = chunk.get("delta", "")
                final_parts.append(delta)
                await conn.send(
                    event(
                        "stream_chunk",
                        message_id=ai_msg_id,
                        sender_id=agent_id,
                        conversation_id=conversation_id,
                        seq=seq,
                        delta=delta,
                    )
                )
            elif ctype == "usage":
                await conn.send(
                    event(
                        "usage",
                        message_id=ai_msg_id,
                        sender_id=agent_id,
                        input_tokens=chunk.get("input_tokens", 0),
                        output_tokens=chunk.get("output_tokens", 0),
                    )
                )
            elif ctype == "error":
                await persist_final(Session, ai_msg_id, "".join(final_parts))
                await conn.send(
                    event(
                        "error",
                        message_id=ai_msg_id,
                        sender_id=agent_id,
                        conversation_id=conversation_id,
                        code=chunk.get("code", "adapter_error"),
                        message=chunk.get("message", ""),
                    )
                )
                return
            elif ctype == "done":
                break

        await persist_final(Session, ai_msg_id, "".join(final_parts))
        await conn.send(
            event(
                "message_done",
                message_id=ai_msg_id,
                sender_id=agent_id,
                conversation_id=conversation_id,
                final_content={"type": "text", "text": "".join(final_parts)},
            )
        )
    except asyncio.TimeoutError:
        logger.warning(
            "ws[%s] agent[%s] timed out after %ds",
            conn.conn_id, agent_id, AGENT_TIMEOUT_S,
        )
        await persist_final(Session, ai_msg_id, "".join(final_parts))
        await conn.send(
            event(
                "error",
                message_id=ai_msg_id,
                sender_id=agent_id,
                conversation_id=conversation_id,
                code="agent_timeout",
                message=f"Agent did not complete within {AGENT_TIMEOUT_S}s",
            )
        )
    except asyncio.CancelledError:
        await persist_final(Session, ai_msg_id, "".join(final_parts))
        await conn.send(
            event(
                "message_cancelled",
                message_id=ai_msg_id,
                sender_id=agent_id,
                conversation_id=conversation_id,
                final_content={"type": "text", "text": "".join(final_parts)},
            )
        )
        raise
    except Exception as exc:
        logger.exception(
            "ws[%s] agent[%s] reply crashed", conn.conn_id, agent_id
        )
        await persist_final(Session, ai_msg_id, "".join(final_parts))
        await conn.send(
            event(
                "error",
                message_id=ai_msg_id,
                sender_id=agent_id,
                conversation_id=conversation_id,
                code="adapter_crash",
                message=str(exc),
            )
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
        await persist_final(Session, ai_msg_id, f"✅ Task analysis complete for: {user_text[:100]}")
        await conn.send(
            event(
                "message_done",
                message_id=ai_msg_id,
                sender_id=ORCHESTRATOR_AGENT_ID,
                conversation_id=conversation_id,
                final_content={"type": "text", "text": f"✅ Orchestrator has analyzed the task and dispatched subtasks."},
            )
        )
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


async def persist_final(Session, message_id: str, text: str) -> None:
    """Write the accumulated (possibly partial) text back to the DB message row."""
    async with Session() as s:
        await update_message_content(s, message_id, {"type": "text", "text": text})
