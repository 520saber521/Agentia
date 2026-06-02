"""Subtask dispatch: fan-out to agents with retry, artifact creation, and status tracking."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from db.engine import get_sessionmaker
from db.models import Message as MessageModel
from db.models import new_id
from services import create_message as create_service_message
from services import message_to_dict, update_message_content
from services.artifact import create_artifact as create_service_artifact
from services.task import update_task_status, task_to_dict
from ws import Connection, event

logger = logging.getLogger("agenthub.orchestrator.executor")

ORCHESTRATOR_AGENT_ID = "agent_orchestrator"
RETRY_LIMIT = 1
FRONTEND_PREVIEW_MAX_TOKENS = 24000


async def _dispatch_subtask_with_result(
    conn: Connection,
    st: Any,
    agent_id: str,
    conversation_id: str,
    user_text: str,
    pinned_context: list[str] | None = None,
) -> str:
    """Dispatch a subtask to an agent and create a message bubble for it.

    Returns the message_id of the agent's reply message.
    """
    from orchestrator.preview import (
        _close_partial_html,
        _compact_frontend_prompt,
        _extract_html_from_text,
        _html_title,
        _is_frontend_preview_subtask,
        _looks_like_html,
        _preview_message_content,
        _visible_generation_error,
    )

    Session = get_sessionmaker()

    # Create agent placeholder message for this subtask
    async with Session() as s:
        agent_msg = await create_service_message(
            s,
            conversation_id=conversation_id,
            sender_id=agent_id,
            sender_type="agent",
            content={"type": "text", "text": f"⏳ Working on: {st.title[:80]}..."},
        )
        msg_id = agent_msg.id
        msg_dict = message_to_dict(agent_msg)

    await conn.send(event("message_created", message=msg_dict))
    await conn.send(event("agent_typing", agent_id=agent_id, conversation_id=conversation_id))

    # Build a concise subtask message with pinned context
    pinned_block = ""
    if pinned_context:
        pinned_block = (
            "\n**Pinned Context (长期上下文):**\n"
            + "\n---\n".join(pc[:500] for pc in pinned_context[:5])
            + "\n"
        )

    agent_prompt = (
        f"[Orchestrator Subtask Assignment]\n\n"
        f"**Original Input**: {user_text}\n"
        f"**Task**: {st.title}\n"
        f"**Domain**: {st.domain}\n"
        f"**Description**: {st.description}\n"
        f"{pinned_block}"
    )

    from handlers.agent_ops import load_adapter_for
    from handlers.artifact_utils import persist_final
    loaded = await load_adapter_for(agent_id)

    if loaded is None:
        async with Session() as s:
            await update_message_content(s, msg_id, {
                "type": "text",
                "text": f"❌ Agent `{agent_id}` not available for subtask: {st.title[:60]}",
            })
        await conn.send(event(
            "message_done",
            message_id=msg_id,
            sender_id=agent_id,
            conversation_id=conversation_id,
            final_content={"type": "text", "text": "❌ Agent unavailable."},
        ))
        async with Session() as s:
            updated = await update_task_status(s, st.id, "failed",
                result_summary=f"Agent {agent_id} not available")
        if updated is not None:
            await conn.send(event(
                "task_update",
                conversation_id=conversation_id,
                task=task_to_dict(updated),
                task_id=updated.parent_task_id or updated.id,
                subtask_id=updated.id if updated.parent_task_id else None,
                status=updated.status,
                progress=updated.progress_pct,
                message_id=msg_id,
                action="status_changed",
            ))
        raise RuntimeError(f"Agent {agent_id} not available")

    adapter, _agent_name = loaded
    is_frontend_preview = _is_frontend_preview_subtask(st, user_text)
    if is_frontend_preview:
        agent_prompt = _compact_frontend_prompt(agent_prompt)
        if hasattr(adapter, "max_tokens"):
            try:
                adapter.max_tokens = max(int(getattr(adapter, "max_tokens", 0)), FRONTEND_PREVIEW_MAX_TOKENS)
            except (TypeError, ValueError):
                adapter.max_tokens = FRONTEND_PREVIEW_MAX_TOKENS
    final_parts: list[str] = []
    error_parts: list[str] = []
    seq = 0

    try:
        async for chunk in adapter.send(
            messages=[{"role": "user", "content": agent_prompt}]
        ):
            ctype = chunk.get("type")
            if ctype == "text":
                seq += 1
                delta = chunk.get("delta", "")
                final_parts.append(delta)
                await conn.send(event(
                    "stream_chunk",
                    message_id=msg_id,
                    sender_id=agent_id,
                    conversation_id=conversation_id,
                    seq=seq,
                    delta=delta,
                ))
            elif ctype == "error":
                code = chunk.get("code") or "adapter_error"
                message = chunk.get("message") or "Agent adapter error"
                error_parts.append(f"{code}: {message}")

        if error_parts and is_frontend_preview:
            error_text = "; ".join(error_parts)
            final_text = "".join(final_parts)
            html_doc = _extract_html_from_text(final_text) or _close_partial_html(
                final_text,
                user_text,
                error_text,
            )
            async with Session() as s:
                artifact_payload = await create_service_artifact(
                    s,
                    conversation_id=conversation_id,
                    kind="preview",
                    title=_html_title(html_doc, st.title),
                    mime_type="text/html",
                    file_name="subtask-preview.html",
                    content=html_doc,
                    source_message_id=msg_id,
                    created_by=agent_id,
                    meta={
                        "source": "frontend_recovered_html",
                        "language": "html",
                        "task_id": st.id,
                        "recovery_reason": error_text,
                    },
                )
                content_payload = _preview_message_content(artifact_payload, html_doc)
                await update_message_content(s, msg_id, content_payload)
                row = await s.get(MessageModel, msg_id)
                if row is not None:
                    row.artifact_id = artifact_payload["id"]
                    await s.commit()
            await conn.send(event(
                "artifact_ready",
                conversation_id=conversation_id,
                artifact=artifact_payload,
                message_id=msg_id,
            ))
            await conn.send(event(
                "message_done",
                message_id=msg_id,
                sender_id=agent_id,
                conversation_id=conversation_id,
                final_content=content_payload,
            ))
            display_text = f"已生成可预览 HTML（截断后恢复）：{artifact_payload['title']}"
            async with Session() as s:
                updated = await update_task_status(
                    s,
                    st.id,
                    "done",
                    result_summary=f"{display_text}; recovery_reason={error_text}"[:200],
                    progress_pct=100,
                )
            if updated is not None:
                await conn.send(event(
                    "task_update",
                    conversation_id=conversation_id,
                    task=task_to_dict(updated),
                    task_id=updated.parent_task_id or updated.id,
                    subtask_id=updated.id if updated.parent_task_id else None,
                    status=updated.status,
                    progress=updated.progress_pct,
                    message_id=msg_id,
                    action="status_changed",
                ))
            return msg_id

        if error_parts:
            final_text = "".join(final_parts) + _visible_generation_error(
                str(code),
                str(message),
            )
            async with Session() as s:
                await update_message_content(s, msg_id, {"type": "text", "text": final_text})
            await conn.send(event(
                "message_done",
                message_id=msg_id,
                sender_id=agent_id,
                conversation_id=conversation_id,
                final_content={"type": "text", "text": final_text},
            ))
            async with Session() as s:
                updated = await update_task_status(s, st.id, "failed",
                    result_summary=final_text[:200])
            if updated is not None:
                await conn.send(event(
                    "task_update",
                    conversation_id=conversation_id,
                    task=task_to_dict(updated),
                    task_id=updated.parent_task_id or updated.id,
                    subtask_id=updated.id if updated.parent_task_id else None,
                    status=updated.status,
                    progress=updated.progress_pct,
                    message_id=msg_id,
                    action="status_changed",
                ))
            raise RuntimeError(final_text)

        final_text = "".join(final_parts) or f"✅ Subtask completed: {st.title[:100]}"
        async with Session() as s:
            await update_message_content(s, msg_id, {"type": "text", "text": final_text})
        await conn.send(event(
            "message_done",
            message_id=msg_id,
            sender_id=agent_id,
            conversation_id=conversation_id,
            final_content={"type": "text", "text": final_text},
        ))

        display_text = final_text
        artifact_payload = None
        if agent_id.startswith("agent_mock") or is_frontend_preview:
            html_doc = _extract_html_from_text(final_text)
            if html_doc is None and is_frontend_preview and _looks_like_html(final_text):
                html_doc = _close_partial_html(final_text, user_text, "frontend_html_incomplete")
            if html_doc:
                async with Session() as s:
                    artifact_payload = await create_service_artifact(
                        s,
                        conversation_id=conversation_id,
                        kind="preview",
                        title=_html_title(html_doc, st.title),
                        mime_type="text/html",
                        file_name="subtask-preview.html",
                        content=html_doc,
                        source_message_id=msg_id,
                        created_by=agent_id,
                        meta={"source": "subtask_html", "language": "html", "task_id": st.id},
                    )
                    await update_message_content(s, msg_id, _preview_message_content(artifact_payload, html_doc))
                    row = await s.get(MessageModel, msg_id)
                    if row is not None:
                        row.artifact_id = artifact_payload["id"]
                        await s.commit()
                display_text = f"已生成可预览 HTML：{artifact_payload['title']}"
                await conn.send(event(
                    "artifact_ready",
                    conversation_id=conversation_id,
                    artifact=artifact_payload,
                    message_id=msg_id,
                ))

        # Mark subtask as done
        async with Session() as s:
            updated = await update_task_status(s, st.id, "done",
                result_summary=display_text[:200],
                progress_pct=100)
        if updated is not None:
            await conn.send(event(
                "task_update",
                conversation_id=conversation_id,
                task=task_to_dict(updated),
                task_id=updated.parent_task_id or updated.id,
                subtask_id=updated.id if updated.parent_task_id else None,
                status=updated.status,
                progress=updated.progress_pct,
                message_id=msg_id,
                action="status_changed",
            ))

    except asyncio.CancelledError:
        async with Session() as s:
            await update_message_content(s, msg_id, {"type": "text", "text": "[cancelled]"})
        raise

    return msg_id


async def _dispatch_subtask_with_retry(
    conn: Connection,
    st: Any,
    agent_id: str,
    conversation_id: str,
    user_text: str,
    pinned_context: list[str] | None = None,
) -> str:
    last_exc: Exception | None = None
    for attempt in range(RETRY_LIMIT + 1):
        try:
            return await _dispatch_subtask_with_result(
                conn,
                st,
                agent_id=agent_id,
                conversation_id=conversation_id,
                user_text=user_text,
                pinned_context=pinned_context,
            )
        except Exception as exc:
            last_exc = exc
            if attempt >= RETRY_LIMIT:
                break
            Session = get_sessionmaker()
            async with Session() as s:
                updated = await update_task_status(
                    s,
                    st.id,
                    "running",
                    result_summary=f"Retrying after adapter failure: {str(exc)[:120]}",
                    progress_pct=25,
                )
            if updated is not None:
                await conn.send(event(
                    "task_update",
                    conversation_id=conversation_id,
                    task=task_to_dict(updated),
                    action="status_changed",
                ))
            await asyncio.sleep(0.25)
    raise RuntimeError(f"subtask degraded after retry: {last_exc}") from last_exc
