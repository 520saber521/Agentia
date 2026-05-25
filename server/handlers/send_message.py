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
import re
from typing import Any

from sqlalchemy import desc, select

from adapters import build_adapter
from db import DEFAULT_CONV_ID, DEFAULT_USER_ID, get_sessionmaker
from db.models import Agent, Conversation, ConversationMember, Message, new_id
from orchestrator import ORCHESTRATOR_AGENT_ID, handle_orchestrator_mention
from router_client import get_router_client
from services import create_message, message_to_dict, update_message_content
from services.artifact import create_artifact as create_service_artifact
from services.agent import (
    adapter_config_for_runtime,
    create_agent,
    list_agents,
    record_agent_execution_finish,
    record_agent_execution_start,
)
from services.trace import create_trace_entry as create_trace
from ws import Connection, event

logger = logging.getLogger("agenthub.handlers.send_message")

_NO_API_KEY_ADAPTERS = {"mock", "claude_code", "opencode"}


async def _filter_available_agents(agent_ids: list[str]) -> list[str]:
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


async def _conversation_agent_members(conversation_id: str) -> set[str]:
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


def _looks_complex_task(user_text: str) -> bool:
    lower = user_text.lower()
    keywords = [
        "设计", "实现", "开发", "拆", "分派", "网页", "页面", "html", "web", "应用",
        "前端", "后端", "数据", "接口", "测试", "订单", "登录", "注册", "商品",
        "orchestrator", "协调", "多 agent", "multi-agent",
    ]
    return len(user_text) >= 24 or any(k in lower for k in keywords)


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
    if ORCHESTRATOR_AGENT_ID in agent_member_ids and _looks_complex_task(user_text):
        return [ORCHESTRATOR_AGENT_ID], None
    if conv_type == "group" and len(agent_member_ids) > 1:
        available = await _filter_available_agents(list(agent_member_ids))
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
    if await _maybe_create_agent_from_chat(conn, conversation_id, user_text):
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


def _parse_agent_create_request(user_text: str) -> dict[str, Any] | None:
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


async def _maybe_create_agent_from_chat(
    conn: Connection,
    conversation_id: str,
    user_text: str,
) -> bool:
    parsed = _parse_agent_create_request(user_text)
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


async def load_adapter_for(agent_id: str) -> tuple[Any, str] | None:
    """Load ``(adapter_instance, agent_display_name)`` from DB row.

    Returns ``None`` if agent not found or config is broken.
    """
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


async def run_agent_reply(
    conn: Connection,
    agent_id: str,
    ai_msg_id: str,
    conversation_id: str,
    user_text: str,
) -> None:
    """Drive a single agent's streaming reply (may be one of N concurrent fan-out tasks).

    Builds full conversation context from DB history for multi-turn memory.
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

    # Build conversation context from DB history
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

    # Fallback: ensure at least the current user message
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
            artifact_content = await _try_create_artifact(
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
        # Record agent completion in trace
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


CODE_BLOCK_RE = re.compile(r"```(\w+)?\n([\s\S]*?)```", re.MULTILINE)


async def _try_create_artifact(
    Session, conn: Connection, message_id: str, conversation_id: str, agent_id: str, text: str
) -> dict[str, Any] | None:
    """Parse final text for code blocks and create artifacts for each found.

    Only creates artifacts for ``code`` / ``html`` / ``javascript`` / ``typescript`` / ``python``
    and similar programming language blocks. Sends ``artifact_ready`` WS event.
    """
    matches = list(CODE_BLOCK_RE.finditer(text))
    if not matches:
        return None

    first_artifact_id: str | None = None
    first_content_payload: dict[str, Any] | None = None

    for idx, m in enumerate(matches):
        lang = (m.group(1) or "text").strip().lower()
        code = m.group(2).strip()
        if not code:
            continue

        title = f"{lang.capitalize()} Block"
        if idx == 0:
            title = f"Code ({lang})"
        elif idx > 0:
            title = f"Code Block {idx + 1} ({lang})"

        kind = "preview" if lang == "html" else "code"
        mime_type = "text/plain"
        ext_map = {
            "python": ("text/x-python", ".py"),
            "javascript": ("text/javascript", ".js"),
            "typescript": ("text/typescript", ".ts"),
            "jsx": ("text/jsx", ".jsx"),
            "tsx": ("text/tsx", ".tsx"),
            "html": ("text/html", ".html"),
            "css": ("text/css", ".css"),
            "json": ("application/json", ".json"),
            "yaml": ("text/yaml", ".yaml"),
            "markdown": ("text/markdown", ".md"),
            "bash": ("text/x-shellscript", ".sh"),
            "sql": ("text/x-sql", ".sql"),
        }
        if lang in ext_map:
            mime_type, ext = ext_map[lang]
            file_name = f"code{ext}"
        else:
            file_name = "code.txt"

        async with Session() as s:
            artifact = await create_service_artifact(
                s,
                conversation_id=conversation_id,
                kind=kind,
                title=title,
                mime_type=mime_type,
                file_name=file_name,
                content=code,
                source_message_id=message_id,
                created_by=agent_id,
                meta={"language": lang},
            )

        if idx == 0:
            first_artifact_id = artifact["id"]
            content_payload = _artifact_message_content(artifact)
            first_content_payload = content_payload
            async with Session() as s:
                await update_message_content(s, message_id, content_payload)
                from sqlalchemy import select
                from db.models import Message as MessageModel
                m = await s.scalar(select(MessageModel).where(MessageModel.id == message_id))
                if m:
                    m.artifact_id = first_artifact_id
                    await s.commit()

        await conn.send(
            event(
                "artifact_ready",
                conversation_id=conversation_id,
                artifact=artifact,
                message_id=message_id if idx == 0 else None,
            )
        )

    if first_artifact_id:
        return first_content_payload
    return None


async def persist_message_content(Session, message_id: str, content: dict[str, Any]) -> None:
    async with Session() as s:
        await update_message_content(s, message_id, content)


def _artifact_message_content(artifact: dict[str, Any]) -> dict[str, Any]:
    meta = artifact.get("meta") or {}
    base = {
        "artifact_id": artifact["id"],
        "title": artifact["title"],
        "mimeType": artifact["mime_type"],
        "fileSize": artifact["file_size"],
        "url": artifact.get("url"),
        "previewUrl": artifact.get("preview_url"),
        "version": artifact.get("version", 1),
    }
    if artifact["kind"] == "preview":
        return {"type": "preview", **base}
    if artifact["kind"] == "file":
        return {
            "type": "file",
            **base,
            "fileName": artifact["file_name"] or artifact["title"],
        }
    if artifact["kind"] == "diff":
        return {
            "type": "diff",
            **base,
            "fileName": artifact["file_name"] or artifact["title"],
            "summary": meta.get("diff_summary") or "产物版本变更",
            "applied_artifact_id": artifact["id"],
        }
    return {
        "type": "code",
        **base,
        "fileName": artifact["file_name"] or artifact["title"],
        "language": meta.get("language") or "plaintext",
    }


async def persist_artifact_chunk(
    Session,
    message_id: str,
    conversation_id: str,
    agent_id: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    kind = str(payload.get("kind") or "file")
    title = str(payload.get("title") or payload.get("file_name") or "Artifact")
    mime_type = str(payload.get("mime_type") or payload.get("mimeType") or "text/plain")
    file_name = payload.get("file_name") or payload.get("fileName")
    content = payload.get("content")
    if content is None:
        content = payload.get("text", "")
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    parent_id = payload.get("parent_id") or payload.get("parentId")

    async with Session() as s:
        artifact = await create_service_artifact(
            s,
            conversation_id=conversation_id,
            kind=kind,
            title=title,
            mime_type=mime_type,
            file_name=str(file_name) if file_name else None,
            content=str(content),
            source_message_id=message_id,
            created_by=agent_id,
            parent_id=str(parent_id) if parent_id else None,
            meta=meta,
        )
        content_payload = _artifact_message_content(artifact)
        await update_message_content(s, message_id, content_payload)
        from sqlalchemy import select
        from db.models import Message as MessageModel
        m = await s.scalar(select(MessageModel).where(MessageModel.id == message_id))
        if m:
            m.artifact_id = artifact["id"]
            await s.commit()
    return {"artifact": artifact, "content": content_payload}


async def persist_final(Session, message_id: str, text: str) -> None:
    async with Session() as s:
        await update_message_content(s, message_id, {"type": "text", "text": text})
