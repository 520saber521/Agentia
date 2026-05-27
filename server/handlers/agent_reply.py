"""Single-agent streaming reply — drives adapter, persists artifacts, emits WS events."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from sqlalchemy import desc, select

from db import get_sessionmaker
from db.models import Message, new_id
from handlers.agent_ops import load_adapter_for
from handlers.artifact_utils import (
    persist_artifact_chunk,
    persist_final,
    persist_message_content,
    try_create_artifact,
)
from services.agent import record_agent_execution_finish, record_agent_execution_start
from services.trace import create_trace_entry as create_trace
from ws import Connection, event

logger = logging.getLogger("agenthub.handlers.agent_reply")


async def run_agent_reply(
    conn: Connection,
    agent_id: str,
    ai_msg_id: str,
    conversation_id: str,
    user_text: str,
) -> None:
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

    Session = get_sessionmaker()
    async with Session() as s:
        await record_agent_execution_start(
            s,
            conversation_id=conversation_id,
            message_id=ai_msg_id,
            agent_id=agent_id,
            input_summary=user_text,
        )

    messages: list[dict[str, Any]] = []
    async with Session() as s:
        rows = (
            await s.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(desc(Message.created_at))
                .limit(50)
            )
        ).all()
        for m in reversed(rows):
            role = "assistant" if m.sender_type == "agent" else "user"
            raw = json.loads(m.content) if m.content else {}
            text = raw.get("text", "") if isinstance(raw, dict) else ""
            if text.strip():
                messages.append({"role": role, "content": text})

    if not any(msg["content"] == user_text for msg in messages):
        messages.append({"role": "user", "content": user_text})

    final_parts: list[str] = []
    artifact_messages: list[dict[str, Any]] = []
    seq = 0

    try:
        async for chunk in adapter.send(messages=messages):
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
            elif ctype == "artifact":
                artifact_payload = chunk.get("artifact") or {}
                artifact_message = await persist_artifact_chunk(
                    Session,
                    ai_msg_id,
                    conversation_id,
                    agent_id,
                    artifact_payload,
                )
                if artifact_message is not None:
                    artifact_messages.append(artifact_message)
                    await conn.send(
                        event(
                            "artifact_ready",
                            conversation_id=conversation_id,
                            artifact=artifact_message["artifact"],
                            message_id=ai_msg_id,
                        )
                    )
            elif ctype == "error":
                await persist_final(Session, ai_msg_id, "".join(final_parts))
                async with Session() as s:
                    await record_agent_execution_finish(
                        s,
                        message_id=ai_msg_id,
                        status="failed",
                        output_summary="".join(final_parts),
                        error=chunk.get("message", ""),
                    )
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

        final_text = "".join(final_parts)
        if artifact_messages:
            final_content = artifact_messages[-1]["content"]
        else:
            artifact_content = await try_create_artifact(
                Session, conn, ai_msg_id, conversation_id, agent_id, final_text
            )
            final_content = artifact_content or {"type": "text", "text": final_text}
        await persist_message_content(Session, ai_msg_id, final_content)
        async with Session() as s:
            await record_agent_execution_finish(
                s,
                message_id=ai_msg_id,
                status="done",
                output_summary=final_text,
            )
        await conn.send(
            event(
                "message_done",
                message_id=ai_msg_id,
                sender_id=agent_id,
                conversation_id=conversation_id,
                final_content=final_content,
            )
        )
        async with Session() as s:
            await create_trace(
                s,
                message_id=ai_msg_id,
                conversation_id=conversation_id,
                trace_id=new_id("trace"),
                node_id=agent_id,
                node_role="agent",
                event="message_done",
                status="ok",
                detail=final_text[:200],
                seq=0,
            )
    except asyncio.CancelledError:
        final_text = "".join(final_parts)
        await persist_final(Session, ai_msg_id, final_text)
        async with Session() as s:
            await record_agent_execution_finish(
                s,
                message_id=ai_msg_id,
                status="cancelled",
                output_summary=final_text,
            )
        await conn.send(
            event(
                "message_cancelled",
                message_id=ai_msg_id,
                sender_id=agent_id,
                conversation_id=conversation_id,
                final_content={"type": "text", "text": final_text},
            )
        )
        async with Session() as s:
            await create_trace(
                s,
                message_id=ai_msg_id,
                conversation_id=conversation_id,
                trace_id=new_id("trace"),
                node_id=agent_id,
                node_role="agent",
                event="message_cancelled",
                status="cancelled",
                seq=0,
            )
        raise
    except Exception as exc:
        logger.exception(
            "ws[%s] agent[%s] reply crashed", conn.conn_id, agent_id
        )
        final_text = "".join(final_parts)
        await persist_final(Session, ai_msg_id, final_text)
        async with Session() as s:
            await record_agent_execution_finish(
                s,
                message_id=ai_msg_id,
                status="failed",
                output_summary=final_text,
                error=str(exc),
            )
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
        async with Session() as s:
            await create_trace(
                s,
                message_id=ai_msg_id,
                conversation_id=conversation_id,
                trace_id=new_id("trace"),
                node_id=agent_id,
                node_role="agent",
                event="adapter_crash",
                status="failed",
                detail=str(exc)[:500],
                seq=0,
            )
