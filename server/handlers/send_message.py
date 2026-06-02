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
from services.animation_bus import animation_bus
from services.agent import (
    adapter_config_for_runtime,
    create_agent,
    list_agents,
    record_agent_execution_finish,
    record_agent_execution_start,
)
from services.context_manager import ContextManager
from services.react_loop import ReActEngine
from services.tool_registry import ToolRegistry, get_tool_registry
from services.spells import expand_spell
from services.trace import create_trace_entry as create_trace
from ws import Connection, event

logger = logging.getLogger("agenthub.handlers.send_message")

DSML_TOOL_CALL_RE = re.compile(
    r"<[|｜]{2}DSML[|｜]{2}tool_calls>[\s\S]*?</[|｜]{2}DSML[|｜]{2}tool_calls>",
    re.DOTALL,
)
DSML_INVOKE_RE = re.compile(r"</?[|｜]{2}DSML[|｜]{2}invoke[^>]*>", re.DOTALL)
TOOL_CALL_BLOCK_RE = re.compile(r"```(?:tool_call|tool|tool_call_call)[\s\S]*?(?:```|$)", re.MULTILINE)
TOOL_CALL_LEAK_RE = re.compile(r"(?:^|\n)\s*(?:tool)?`{0,3}(?:tool_call|tool_call_call)\b[\s\S]*$", re.MULTILINE)

# Raw XML tool-call tags that some models (especially in SDK-based paths) leak
# into visible text output. These cover Anthropic-style and generic XML formats.
_RAW_TOOL_CALLS_BLOCK_RE = re.compile(
    r"<\s*tool_calls\s*>[\s\S]*?<\s*/\s*tool_calls\s*>",
    re.DOTALL | re.IGNORECASE,
)
_RAW_INVOKE_BLOCK_RE = re.compile(
    r"<\s*invoke\s+name\s*=\s*[\"'][^\"'>]+[\"'][^>]*>[\s\S]*?<\s*/\s*invoke\s*>",
    re.DOTALL | re.IGNORECASE,
)
_RAW_INVOKE_SELF_CLOSE_RE = re.compile(
    r"<\s*invoke\s+name\s*=\s*[\"'][^\"'>]+[\"'][^>]*/\s*>",
    re.IGNORECASE,
)
_BARE_TOOL_CALLS_TAG_RE = re.compile(
    r"<\s*/?\s*tool_calls\s*>",
    re.IGNORECASE,
)
_BARE_INVOKE_TAG_RE = re.compile(
    r"<\s*/?\s*invoke\b[^>]*>",
    re.IGNORECASE,
)
_PARAMETER_TAG_RE = re.compile(
    r"<\s*/?\s*parameter\b[^>]*>",
    re.IGNORECASE,
)
_DUP_CJK_RE = re.compile(r"([\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af])\1+")

# DSML without angle brackets (DeepSeek variant leaks)
_DSML_TOOL_CALL_NO_BRACKET_RE = re.compile(
    r"\n?[|｜]{2}DSML[|｜]{2}tool_calls>[\s\S]*?</[|｜]{2}DSML[|｜]{2}tool_calls>",
    re.DOTALL,
)
_DSML_INVOKE_NO_BRACKET_TAG_RE = re.compile(
    r"</?[|｜]{2}DSML[|｜]{2}invoke[^>]*>",
    re.DOTALL,
)
_TOOL_CALL_REMNANT_RE = re.compile(
    r"(?:^|\n)\s*_call\b[\s\S]*?(?=\n(?:[^\s{]|$)|\Z)",
    re.MULTILINE,
)
_TOOL_CALL_JSON_LEAK_RE = re.compile(
    r'(?:^|\n)\s*"name"\s*:\s*"(?:create_artifact|write_file|read_file|list_files|web_search|run_shell)"[\s\S]*?'
    r'(?:}\s*\n```|\n```|$)',
    re.MULTILINE,
)


def _dedup_stream_delta(text: str) -> str:
    if not text:
        return text
    return _DUP_CJK_RE.sub(r"\1", text)


def clean_visible_model_text(text: str) -> str:
    """Remove raw tool-call protocols that should never be shown to users."""
    if not text:
        return text
    # DSML pipe-delimited format (DeepSeek)
    text = DSML_TOOL_CALL_RE.sub("", text)
    text = DSML_INVOKE_RE.sub("", text)
    # Markdown-fenced tool_call blocks
    text = TOOL_CALL_BLOCK_RE.sub("", text)
    text = TOOL_CALL_LEAK_RE.sub("", text)
    # Raw XML tool-call tags (Anthropic SDK / Claude Code style)
    text = _RAW_TOOL_CALLS_BLOCK_RE.sub("", text)
    text = _RAW_INVOKE_BLOCK_RE.sub("", text)
    text = _RAW_INVOKE_SELF_CLOSE_RE.sub("", text)
    # Bare leftover tags after block removal
    text = _BARE_TOOL_CALLS_TAG_RE.sub("", text)
    text = _BARE_INVOKE_TAG_RE.sub("", text)
    text = _PARAMETER_TAG_RE.sub("", text)
    text = _DSML_TOOL_CALL_NO_BRACKET_RE.sub("", text)
    text = _DSML_INVOKE_NO_BRACKET_TAG_RE.sub("", text)
    text = _TOOL_CALL_REMNANT_RE.sub("", text)
    text = _TOOL_CALL_JSON_LEAK_RE.sub("", text)
    text = _dedup_stream_delta(text)
    return text

AGENT_CREATE_TOOLS = {
    "code_editor",
    "artifact_read",
    "artifact_write",
    "web_preview",
    "deploy",
}
AGENT_CREATE_REQUIRED = ("name", "system_prompt")
_agent_create_drafts: dict[str, dict[str, Any]] = {}


def _visible_generation_error(code: str, message: str) -> str:
    if code == "output_truncated":
        return (
            "\n\n---\n"
            "[提示] 输出达到模型长度上限，当前内容可能不完整。"
            "请发送“继续生成”，或提高该 Agent 的 max_tokens 后重新生成。"
        )
    clean = message.strip() or code
    return f"\n\n---\n[提示] 生成中断：{clean}"


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

    # Auto-route only when conversation is empty (first message)
    Session = get_sessionmaker()
    async with Session() as s:
        last_msg = await s.scalar(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(desc(Message.created_at))
            .limit(1)
        )

    if last_msg is None:
        # Empty conversation — auto-route to Orchestrator for complex tasks
        if ORCHESTRATOR_AGENT_ID in agent_member_ids and _looks_complex_task(user_text):
            return [ORCHESTRATOR_AGENT_ID], None
    else:
        # Conversation has history — route to last active domain agent if available
        last_agent_id = last_msg.sender_id if last_msg.sender_type == "agent" else None
        if last_agent_id and last_agent_id != ORCHESTRATOR_AGENT_ID and last_agent_id in agent_member_ids:
            return [last_agent_id], None

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
    user_text = expand_spell(user_text)
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

    # Start router health check in parallel with DB work
    router = get_router_client()
    router_health_task = asyncio.create_task(router.health())

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
        agent_rows: dict[str, Agent] = {}
        for aid in target_agent_ids:
            agent_row = await s.get(Agent, aid)
            if agent_row is not None:
                agent_rows[aid] = agent_row
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

    # ── Send message_created & start agent replies BEFORE router dispatch ──
    # Router health-check / HTTP dispatch can take 1-10 s; the frontend
    # should see bubbles and the LLM call should already be in flight by then.

    await conn.send(event("message_created", message=user_msg_dict))
    for _aid, _mid, mdict in agent_msgs:
        await conn.send(event("message_created", message=mdict))
        row = agent_rows.get(_aid)
        animation_bus.agent_created(
            conversation_id=conversation_id,
            agent_id=_aid,
            role=row.adapter_type if row is not None else "agent",
            parent_id=ORCHESTRATOR_AGENT_ID,
            agent_name=row.name if row is not None else _aid,
        )
        animation_bus.beam(
            conversation_id=conversation_id,
            from_id=ORCHESTRATOR_AGENT_ID,
            to_id=_aid,
            kind="message",
            label="message",
        )
        animation_bus.viz_event(
            conversation_id=conversation_id,
            kind="message",
            label=f"message: {row.name if row is not None else _aid}",
        )

    has_orchestrator = ORCHESTRATOR_AGENT_ID in target_agent_ids
    non_orch_agents = [a for a in target_agent_ids if a != ORCHESTRATOR_AGENT_ID]

    # Single-chat with orchestrator only: reply directly instead of decomposing
    is_single_orch = False
    if has_orchestrator and not non_orch_agents:
        Session = get_sessionmaker()
        async with Session() as s:
            conv = await s.get(Conversation, conversation_id)
            is_single_orch = conv is not None and conv.type == "single"
            del conv

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
        if aid == ORCHESTRATOR_AGENT_ID and not is_single_orch:
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

    # ── Router dispatch (runs concurrently with agent-reply tasks above) ──
    router_ok = await router_health_task

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
        return {
            "name": "",
            "adapter_type": "mock",
            "model": "",
            "system_prompt": "",
            "capabilities": [],
            "tools": [],
        }

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
    tools_raw = fields.get("tools") or fields.get("toolset") or fields.get("工具") or ""
    tools = _normalize_agent_tools(tools_raw)

    return {
        "name": name[:80] or "Custom Agent",
        "adapter_type": adapter_type,
        "model": model,
        "system_prompt": system_prompt,
        "capabilities": capabilities or ["code"],
        "tools": tools,
    }


def _is_agent_create_start(user_text: str) -> bool:
    lower = user_text.strip().lower()
    return (
        lower.startswith("/agent create")
        or lower.startswith("create agent")
        or lower.startswith("创建agent")
        or lower.startswith("新建agent")
    )


def _normalize_agent_tools(raw: str | list[Any] | None) -> list[str]:
    if isinstance(raw, list):
        parts = [str(x).strip() for x in raw]
    else:
        parts = [x.strip() for x in re.split(r"[,，/、\\s]+", str(raw or ""))]
    aliases = {
        "code": "code_editor",
        "editor": "code_editor",
        "read": "artifact_read",
        "write": "artifact_write",
        "preview": "web_preview",
        "web": "web_preview",
        "deploy": "deploy",
        "代码编辑": "code_editor",
        "读产物": "artifact_read",
        "写产物": "artifact_write",
        "网页预览": "web_preview",
        "部署": "deploy",
    }
    tools: list[str] = []
    for part in parts:
        if not part:
            continue
        tool = aliases.get(part.lower(), aliases.get(part, part))
        if tool in AGENT_CREATE_TOOLS and tool not in tools:
            tools.append(tool)
    return tools


def _parse_agent_wizard_fields(user_text: str) -> dict[str, Any]:
    text = user_text.strip()
    fields: dict[str, Any] = {}
    for part in re.split(r"\n+|\s+[|;]\s+", text):
        if ":" not in part and "：" not in part:
            continue
        key, value = re.split(r"[:：]", part, maxsplit=1)
        key = key.strip().lower()
        value = value.strip()
        if key in {"name", "名称", "名字"}:
            fields["name"] = value[:80]
        elif key in {"adapter", "adapter_type", "平台"}:
            fields["adapter_type"] = value or "mock"
        elif key in {"model", "模型"}:
            fields["model"] = value
        elif key in {"prompt", "system_prompt", "提示词", "角色"}:
            fields["system_prompt"] = value
        elif key in {"capabilities", "tags", "能力", "标签"}:
            fields["capabilities"] = [x.strip() for x in re.split(r"[,，/、]", value) if x.strip()]
        elif key in {"tools", "toolset", "工具", "工具集"}:
            fields["tools"] = _normalize_agent_tools(value)
    if not fields:
        for key in ("name", "system_prompt", "tools", "capabilities", "adapter_type", "model"):
            if text.lower().startswith(f"{key} "):
                fields[key] = text.split(" ", 1)[1].strip()
                break
    if isinstance(fields.get("tools"), str):
        fields["tools"] = _normalize_agent_tools(fields["tools"])
    if isinstance(fields.get("capabilities"), str):
        fields["capabilities"] = [x.strip() for x in re.split(r"[,，/、]", fields["capabilities"]) if x.strip()]
    return fields


def _agent_create_missing_fields(draft: dict[str, Any]) -> list[str]:
    return [key for key in AGENT_CREATE_REQUIRED if not str(draft.get(key) or "").strip()]


def _agent_create_prompt_text(draft: dict[str, Any]) -> str:
    missing = _agent_create_missing_fields(draft)
    if missing:
        labels = {
            "name": "Agent 名称",
            "system_prompt": "System Prompt",
        }
        return (
            "正在创建自定义 Agent。请补充："
            + "、".join(labels[x] for x in missing)
            + "\n\n你可以这样回复：\n"
            "name: Frontend Expert\n"
            "system_prompt: 你是前端工程 Agent，负责 React 组件实现和代码审查。\n"
            "tools: code_editor, artifact_read, artifact_write, web_preview\n"
            "capabilities: frontend, react, code\n\n"
            "可用工具：code_editor, artifact_read, artifact_write, web_preview, deploy。\n"
            "发送“取消”放弃创建。"
        )
    return (
        "请确认创建这个 Agent：\n\n"
        f"- name: {draft.get('name')}\n"
        f"- adapter: {draft.get('adapter_type') or 'mock'}\n"
        f"- model: {draft.get('model') or '(empty)'}\n"
        f"- tools: {', '.join(draft.get('tools') or []) or '(none)'}\n"
        f"- capabilities: {', '.join(draft.get('capabilities') or ['code'])}\n"
        f"- system_prompt: {str(draft.get('system_prompt') or '')[:240]}\n\n"
        "回复“确认”或 `confirm` 创建，回复“取消”放弃。"
    )


async def _send_agent_wizard_reply(
    conn: Connection,
    conversation_id: str,
    user_text: str,
    reply_text: str,
) -> None:
    Session = get_sessionmaker()
    async with Session() as s:
        user_msg = await create_message(
            s,
            conversation_id=conversation_id,
            sender_id=DEFAULT_USER_ID,
            sender_type="user",
            content={"type": "text", "text": user_text},
        )
        reply = await create_message(
            s,
            conversation_id=conversation_id,
            sender_id=ORCHESTRATOR_AGENT_ID,
            sender_type="agent",
            content={"type": "text", "text": reply_text},
        )
    await conn.send(event("message_created", message=message_to_dict(user_msg)))
    await conn.send(event("message_created", message=message_to_dict(reply)))
    await conn.send(event(
        "message_done",
        message_id=reply.id,
        sender_id=ORCHESTRATOR_AGENT_ID,
        conversation_id=conversation_id,
        final_content=json.loads(reply.content),
    ))


async def _maybe_create_agent_from_chat(
    conn: Connection,
    conversation_id: str,
    user_text: str,
) -> bool:
    draft = _agent_create_drafts.get(conversation_id)
    text_norm = user_text.strip().lower()
    if draft is not None and text_norm in {"取消", "cancel", "退出", "stop"}:
        _agent_create_drafts.pop(conversation_id, None)
        await _send_agent_wizard_reply(conn, conversation_id, user_text, "已取消自定义 Agent 创建。")
        return True

    if draft is not None and text_norm in {"确认", "confirm", "ok", "创建", "create"}:
        missing = _agent_create_missing_fields(draft)
        if missing:
            await _send_agent_wizard_reply(conn, conversation_id, user_text, _agent_create_prompt_text(draft))
            return True
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
                key: draft[key]
                for key in ("model", "system_prompt", "tools")
                if draft.get(key)
            }
            agent = await create_agent(
                s,
                name=draft["name"],
                adapter_type=draft.get("adapter_type") or "mock",
                config=config,
                capabilities=draft.get("capabilities") or ["code"],
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
                        f"Created Agent `{agent['name']}` with tools: "
                        f"{', '.join(agent.get('tools') or []) or '(none)'}."
                    ),
                },
            )
            agents = await list_agents(s)
        _agent_create_drafts.pop(conversation_id, None)
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

    if draft is not None:
        draft.update({k: v for k, v in _parse_agent_wizard_fields(user_text).items() if v not in (None, "", [])})
        _agent_create_drafts[conversation_id] = draft
        await _send_agent_wizard_reply(conn, conversation_id, user_text, _agent_create_prompt_text(draft))
        return True

    parsed = _parse_agent_create_request(user_text)
    if parsed is None:
        return False

    if _is_agent_create_start(user_text) and _agent_create_missing_fields(parsed):
        parsed.setdefault("adapter_type", "mock")
        parsed.setdefault("capabilities", ["code"])
        parsed.setdefault("tools", [])
        _agent_create_drafts[conversation_id] = parsed
        await _send_agent_wizard_reply(conn, conversation_id, user_text, _agent_create_prompt_text(parsed))
        return True

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
            for key in ("model", "system_prompt", "tools")
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
                    f"and tools: {', '.join(agent.get('tools') or []) or '(none)'}."
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


async def load_adapter_for(agent_id: str) -> tuple[Any, str, dict[str, Any]] | None:
    """Load ``(adapter_instance, agent_display_name, agent_meta)`` from DB row.

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
        agent_meta = {
            "name": row.name or "",
            "capabilities": row.capabilities or "",
        }

    try:
        adapter = build_adapter(adapter_type, config)
    except ValueError:
        return None
    return adapter, name, agent_meta


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
    # Send typing indicator immediately, before any blocking adapter load
    await conn.send(
        event("agent_typing", agent_id=agent_id, conversation_id=conversation_id)
    )

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
    adapter, _agent_name, agent_meta = loaded

    # Inject runtime context for stateful adapters (SDK client pool needs conv + agent id)
    if hasattr(adapter, 'set_runtime_context'):
        adapter.set_runtime_context(conversation_id, agent_id, conn)

    animation_bus.agent_status(
        conversation_id=conversation_id,
        agent_id=agent_id,
        status="BUSY",
    )
    animation_bus.viz_event(
        conversation_id=conversation_id,
        kind="llm",
        label=f"{_agent_name}: 开始生成",
    )

    # Fire-and-forget: record execution start in background (observability only,
    # must not delay the first LLM byte).
    Session = get_sessionmaker()
    asyncio.create_task(
        _record_execution_start(Session, conversation_id, ai_msg_id, agent_id, user_text),
        name=f"exec-start-{ai_msg_id}",
    )

    # SDK-backed adapters have built-in agent loop + context management;
    # skip ContextManager (4-layer history build) and ReAct (custom tool loop).
    builtin_loop = getattr(adapter, 'has_builtin_loop', False)
    registry = None  # track for post-loop artifact detection
    if builtin_loop:
        messages = [{"role": "user", "content": user_text}]
        chunk_source = adapter.send(messages=messages)
    else:
        model_name = getattr(adapter, "model", "gpt-4o")
        system_prompt = getattr(adapter, "system_prompt", "")

        # Resolve workspace root early so ContextManager can inject file tree
        # Wrapped in try/except: workspace_path column may not exist in older DBs,
        # and we must not let an unhandled exception bypass message_done.
        try:
            from api.workspace import _resolve_workspace_root
            workspace_root = _resolve_workspace_root(conversation_id, None)
            async with Session() as _ws_s:
                _conv = await _ws_s.scalar(select(Conversation).where(Conversation.id == conversation_id))
                if _conv is not None and getattr(_conv, "workspace_path", None):
                    workspace_root = _resolve_workspace_root(conversation_id, _conv.workspace_path)
        except Exception:
            import traceback
            logger.warning("Workspace resolution failed, using default:\n%s", traceback.format_exc())
            from pathlib import Path as _Path
            workspace_root = _Path(__file__).resolve().parents[2] / "workspaces" / conversation_id
            workspace_root.mkdir(parents=True, exist_ok=True)

        cm = ContextManager(conversation_id, model=model_name)
        async with Session() as s:
            await cm.load(
                s,
                system_prompt=system_prompt,
                current_user_text=user_text,
            )
        cm.inject_workspace_context(str(workspace_root))
        messages = cm.build()

        ctx = cm.summary()
        await conn.send(
            event(
                "context_info",
                conversation_id=conversation_id,
                total_messages=ctx["total_loaded"],
                pinned_messages=ctx["pinned_count"],
                history_count=ctx["history_count"],
                estimated_tokens=ctx["estimated_tokens"],
                strategy=ctx["strategy"],
            )
        )

        # Wrap adapter with ReActEngine when tools are available
        registry = get_tool_registry(project_root=str(workspace_root))
        tool_artifacts_list: list[dict[str, Any]] = []
        registry.set_runtime_context(
            conversation_id=conversation_id,
            current_agent_id=agent_id,
            domain=" ".join([
                str(agent_meta.get("name", "") or ""),
                str(agent_meta.get("capabilities", "") or ""),
            ]),
            conn=conn,
            _artifacts=tool_artifacts_list,
            disable_workspace_writes=True,
        )
        has_tools = bool(registry.list_tools())
        if has_tools and ReActEngine.should_use_react(adapter, user_text):
            engine = ReActEngine(registry=registry)
            tool_schemas = registry.get_openai_schemas()
            chunk_source = engine.run(adapter, messages, tools=tool_schemas)
        else:
            chunk_source = adapter.send(messages=messages)

    final_parts: list[str] = []
    artifact_messages: list[dict[str, Any]] = []
    seq = 0

    try:
        async for chunk in chunk_source:
            ctype = chunk.get("type")
            if ctype == "text":
                seq += 1
                delta = clean_visible_model_text(str(chunk.get("delta", "")))
                if not delta:
                    continue
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
                        total_cost_usd=chunk.get("total_cost_usd"),
                    )
                )
            elif ctype == "tool_call":
                tool_name = str(chunk.get("name") or chunk.get("tool_name") or "tool")
                tool_args = chunk.get("args") or chunk.get("tool_arguments") or {}
                await conn.send(
                    event(
                        "tool_call",
                        message_id=ai_msg_id,
                        sender_id=agent_id,
                        conversation_id=conversation_id,
                        tool_name=tool_name,
                        tool_arguments=tool_args if isinstance(tool_args, dict) else {},
                        status="running",
                    )
                )
                animation_bus.viz_event(
                    conversation_id=conversation_id,
                    kind="tool",
                    label=f"{_agent_name}: 调用工具 {tool_name}",
                )
            elif ctype == "observation":
                tool_name = str(
                    chunk.get("tool_name")
                    or chunk.get("tool")
                    or chunk.get("name")
                    or "tool"
                )
                observation = chunk.get("observation")
                if observation is None:
                    observation = chunk.get("content", chunk.get("result", ""))
                observation_text = (
                    observation
                    if isinstance(observation, str)
                    else json.dumps(observation, ensure_ascii=False)
                )
                await conn.send(
                    event(
                        "tool_call",
                        message_id=ai_msg_id,
                        sender_id=agent_id,
                        conversation_id=conversation_id,
                        tool_name=tool_name,
                        status="done",
                        result_summary=observation_text[:240],
                    )
                )
                animation_bus.viz_event(
                    conversation_id=conversation_id,
                    kind="tool",
                    label=f"{_agent_name}: 工具返回 {tool_name}",
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
            elif ctype == "warning":
                # Warnings (e.g. max_steps reached) — informational, not failures
                warn_msg = str(chunk.get("message", ""))
                logger.warning("Agent warning: %s — %s", chunk.get("code"), warn_msg)
                final_parts.append(f"\n[Notice] {warn_msg}")
            elif ctype == "error":
                error_code = str(chunk.get("code", "adapter_error"))
                error_message = str(chunk.get("message", ""))
                final_text = clean_visible_model_text("".join(final_parts)) + _visible_generation_error(
                    error_code,
                    error_message,
                )
                await persist_final(Session, ai_msg_id, final_text)
                async with Session() as s:
                    await record_agent_execution_finish(
                        s,
                        message_id=ai_msg_id,
                        status="failed",
                        output_summary=final_text,
                        error=error_message,
                    )
                await conn.send(
                    event(
                        "message_done",
                        message_id=ai_msg_id,
                        sender_id=agent_id,
                        conversation_id=conversation_id,
                        final_content={"type": "text", "text": final_text},
                    )
                )
                await conn.send(
                    event(
                        "error",
                        message_id=ai_msg_id,
                        sender_id=agent_id,
                        conversation_id=conversation_id,
                        code=error_code,
                        message=error_message,
                    )
                )
                animation_bus.agent_status(
                    conversation_id=conversation_id,
                    agent_id=agent_id,
                    status="IDLE",
                )
                animation_bus.viz_event(
                    conversation_id=conversation_id,
                    kind="llm",
                    label=f"{_agent_name}: 生成失败",
                )
                return
            elif ctype == "done":
                break

        final_text = clean_visible_model_text("".join(final_parts))
        if not builtin_loop and _should_auto_continue_generation(user_text, final_text):
            final_text = await _auto_continue_generation(
                adapter=adapter,
                base_messages=messages,
                current_text=final_text,
                final_parts=final_parts,
                conn=conn,
                ai_msg_id=ai_msg_id,
                agent_id=agent_id,
                conversation_id=conversation_id,
                seq_start=seq,
            )
            final_text = clean_visible_model_text(final_text)
        if artifact_messages:
            final_content = artifact_messages[-1]["content"]
        else:
            # Check for artifacts created via tool calls (e.g. create_artifact)
            tool_artifacts = registry.pop_pending_artifacts() if registry else []
            if tool_artifacts:
                last = tool_artifacts[-1]
                final_content = _artifact_message_content(last)
                async with Session() as s:
                    await update_message_content(s, ai_msg_id, final_content)
                    m = await s.scalar(select(Message).where(Message.id == ai_msg_id))
                    if m:
                        m.artifact_id = last["id"]
                        await s.commit()
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
        animation_bus.agent_status(
            conversation_id=conversation_id,
            agent_id=agent_id,
            status="IDLE",
        )
        animation_bus.viz_event(
            conversation_id=conversation_id,
            kind="llm",
            label=f"{_agent_name}: 生成完成",
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
        final_text = clean_visible_model_text("".join(final_parts))
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
        animation_bus.agent_status(
            conversation_id=conversation_id,
            agent_id=agent_id,
            status="IDLE",
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
        final_text = clean_visible_model_text("".join(final_parts))
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
        animation_bus.agent_status(
            conversation_id=conversation_id,
            agent_id=agent_id,
            status="IDLE",
        )
        animation_bus.viz_event(
            conversation_id=conversation_id,
            kind="llm",
            label=f"{_agent_name}: 生成异常",
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
        async with Session() as s:
            row = await s.get(Message, ai_msg_id)
            final_content = json.loads(row.content) if row and row.content else {"type": "text", "text": "✅ Orchestrator completed coordination."}
        await conn.send(
            event(
                "message_done",
                message_id=ai_msg_id,
                sender_id=ORCHESTRATOR_AGENT_ID,
                conversation_id=conversation_id,
                final_content=final_content,
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


def _should_auto_continue_generation(user_text: str, final_text: str) -> bool:
    text = (final_text or "").strip()
    if len(text) >= 1400:
        return False
    lower = (user_text or "").lower()
    long_request_terms = (
        "详细", "完整", "合集", "几个", "常用", "示例", "教程", "文档", "介绍",
        "注释", "清单", "手册", "指南",
        "detailed", "complete", "examples", "guide", "document", "tutorial",
    )
    if not any(term in lower for term in long_request_terms):
        return False
    if any(term in lower for term in ("sql", "数据库", "java", "内存", "架构", "api", "前端", "后端")):
        return True
    return len(text) < 900


async def _auto_continue_generation(
    *,
    adapter,
    base_messages: list[dict[str, Any]],
    current_text: str,
    final_parts: list[str],
    conn: Connection,
    ai_msg_id: str,
    agent_id: str,
    conversation_id: str,
    seq_start: int,
) -> str:
    seq = seq_start
    continuation_prompt = (
        "你的上一段回答明显未完成。请从中断处继续补全，"
        "不要重复已经写过的内容，直到形成完整可用的长答案。"
        "如果是在写 SQL 示例合集，请继续补充建表、插入、查询、JOIN、聚合、更新、删除、索引等示例，"
        "每段 SQL 都要包含详细中文注释。"
    )
    messages = list(base_messages) + [
        {"role": "assistant", "content": current_text},
        {"role": "user", "content": continuation_prompt},
    ]
    try:
        async for chunk in adapter.send(messages=messages, stream=True):
            ctype = chunk.get("type")
            if ctype == "text":
                delta = clean_visible_model_text(str(chunk.get("delta", "")))
                if not delta:
                    continue
                seq += 1
                final_parts.append(delta)
                await conn.send(event(
                    "stream_chunk",
                    message_id=ai_msg_id,
                    sender_id=agent_id,
                    conversation_id=conversation_id,
                    seq=seq,
                    delta=delta,
                ))
            elif ctype == "error":
                logger.warning("auto-continue failed: %s", chunk)
                break
            elif ctype == "done":
                break
    except Exception:
        logger.exception("auto-continue crashed for %s", ai_msg_id)
    return "".join(final_parts)


CODE_BLOCK_RE = re.compile(r"```(\S+)?\n([\s\S]*?)```", re.MULTILINE)


TOOL_CALL_STRIP_RE = re.compile(r"```(?:tool_call|tool)\s*\n[\s\S]*?```\n?", re.MULTILINE)


def _clean_tool_call_blocks(text: str) -> str:
    """Strip ```tool_call blocks from text so they don't surface as code artifacts."""
    return TOOL_CALL_STRIP_RE.sub("", text).strip()


def _looks_like_markdown_document(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return (
        stripped.startswith("#") or
        (stripped.startswith("**") and len(stripped) > 200) or
        ("## " in stripped and len(stripped) > 300)
    )


def _looks_like_composite_code_document(text: str, matches: list[re.Match]) -> bool:
    if len(matches) >= 2:
        return True
    if not matches:
        return False
    stripped = text.strip()
    only_block = matches[0].start() == 0 and matches[0].end() == len(stripped)
    if only_block:
        return False
    outside = CODE_BLOCK_RE.sub("", text).strip()
    return len(outside) >= 160 or any(marker in outside for marker in ("##", "###", "- ", "1.", "说明", "示例"))


async def _create_markdown_document_artifact(
    Session,
    conn: Connection,
    *,
    message_id: str,
    conversation_id: str,
    agent_id: str,
    text: str,
) -> dict[str, Any]:
    stripped = text.strip()
    heading_match = re.match(r"^#+\s*(.+)", stripped)
    title = heading_match.group(1).strip() if heading_match else "Document"
    async with Session() as s:
        artifact = await create_service_artifact(
            s,
            conversation_id=conversation_id,
            kind="file",
            title=title,
            mime_type="text/markdown",
            file_name="document.md",
            content=stripped,
            source_message_id=message_id,
            created_by=agent_id,
            meta={"language": "markdown"},
        )
        content_payload = _artifact_message_content(artifact)
        await update_message_content(s, message_id, content_payload)
        m = await s.scalar(select(Message).where(Message.id == message_id))
        if m:
            m.artifact_id = artifact["id"]
            await s.commit()
    await conn.send(event(
        "artifact_ready",
        conversation_id=conversation_id,
        artifact=artifact,
        message_id=message_id,
    ))
    return _artifact_message_content(artifact)


async def _try_create_artifact(
    Session, conn: Connection, message_id: str, conversation_id: str, agent_id: str, text: str
) -> dict[str, Any] | None:
    """Parse final text for code blocks and create artifacts for each found.

    Only creates artifacts for ``code`` / ``html`` / ``javascript`` / ``typescript`` / ``python``
    and similar programming language blocks. Sends ``artifact_ready`` WS event.
    """
    # Strip ```tool_call blocks — ReAct engine internals, not user artifacts
    text = _clean_tool_call_blocks(text)
    if not text:
        return None

    # Markdown documents may contain fenced code examples. Treat the whole
    # response as one document before looking for individual code blocks.
    if _looks_like_markdown_document(text):
        return await _create_markdown_document_artifact(
            Session,
            conn,
            message_id=message_id,
            conversation_id=conversation_id,
            agent_id=agent_id,
            text=text,
        )

    matches = list(CODE_BLOCK_RE.finditer(text))

    if _looks_like_composite_code_document(text, matches):
        return await _create_markdown_document_artifact(
            Session,
            conn,
            message_id=message_id,
            conversation_id=conversation_id,
            agent_id=agent_id,
            text=text,
        )

    # Fallback: if no code blocks found but the text looks like a standalone
    # document (starts with markdown heading), wrap the entire text as a file artifact.
    if not matches and text.strip():
        if _looks_like_markdown_document(text):
            # Always treat heading-starting documents as markdown.
            # Internal code blocks (yaml, json, python) are just examples
            # embedded within the document, not the document format itself.
            return await _create_markdown_document_artifact(
                Session,
                conn,
                message_id=message_id,
                conversation_id=conversation_id,
                agent_id=agent_id,
                text=text,
            )

        return None

    first_artifact_id: str | None = None
    first_content_payload: dict[str, Any] | None = None

    # Languages that produce "file" kind (documents / configs, not source code)
    FILE_LANGS = frozenset({"markdown", "md", "text", "txt", "yaml", "yml",
                             "json", "csv", "toml", "ini", "xml", "file"})
    ext_map = {
        "python": ("text/x-python", ".py", "code"),
        "javascript": ("text/javascript", ".js", "code"),
        "typescript": ("text/typescript", ".ts", "code"),
        "jsx": ("text/jsx", ".jsx", "code"),
        "tsx": ("text/tsx", ".tsx", "code"),
        "html": ("text/html", ".html", "code"),
        "css": ("text/css", ".css", "code"),
        "json": ("application/json", ".json", "file"),
        "yaml": ("text/yaml", ".yaml", "file"),
        "yml": ("text/yaml", ".yml", "file"),
        "markdown": ("text/markdown", ".md", "file"),
        "md": ("text/markdown", ".md", "file"),
        "text": ("text/plain", ".txt", "file"),
        "txt": ("text/plain", ".txt", "file"),
        "csv": ("text/csv", ".csv", "file"),
        "toml": ("application/toml", ".toml", "file"),
        "ini": ("text/plain", ".ini", "file"),
        "xml": ("application/xml", ".xml", "file"),
        "bash": ("text/x-shellscript", ".sh", "code"),
        "sh": ("text/x-shellscript", ".sh", "code"),
        "sql": ("text/x-sql", ".sql", "code"),
        "file": ("text/plain", ".txt", "file"),
    }

    for idx, m in enumerate(matches):
        lang_raw = (m.group(1) or "text").strip().lower()
        code = m.group(2).strip()
        if not code:
            continue

        # Parse optional filename: "markdown:report.md"
        user_file_name: str | None = None
        if ":" in lang_raw:
            lang, user_file_name = lang_raw.split(":", 1)
            lang = lang.strip()
            user_file_name = user_file_name.strip() or None
        else:
            lang = lang_raw

        if lang in ext_map:
            mime_type, ext, kind = ext_map[lang]
            file_name = user_file_name or f"code{ext}"
        else:
            kind = "file" if lang in FILE_LANGS else "code"
            mime_type = "text/plain"
            file_name = user_file_name or "code.txt"

        if kind == "file":
            title = user_file_name or file_name or "File"
        elif kind == "preview":
            title = f"Preview ({lang})"
        elif idx == 0:
            title = f"Code ({lang})"
        else:
            title = f"Code Block {idx + 1} ({lang})"

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
                m = await s.scalar(select(Message).where(Message.id == message_id))
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
            "base_artifact_id": artifact.get("parent_id"),
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
        m = await s.scalar(select(Message).where(Message.id == message_id))
        if m:
            m.artifact_id = artifact["id"]
            await s.commit()
    return {"artifact": artifact, "content": content_payload}


async def _record_execution_start(
    Session, conversation_id: str, message_id: str, agent_id: str, input_summary: str
) -> None:
    """Background task: persist agent execution start for observability."""
    try:
        async with Session() as s:
            await record_agent_execution_start(
                s,
                conversation_id=conversation_id,
                message_id=message_id,
                agent_id=agent_id,
                input_summary=input_summary,
            )
    except Exception:
        logger.exception("record_agent_execution_start failed for %s", message_id)


async def persist_final(Session, message_id: str, text: str) -> None:
    async with Session() as s:
        await update_message_content(s, message_id, {"type": "text", "text": text})
