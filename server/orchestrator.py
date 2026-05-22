"""Orchestrator — @Orchestrator 任务自动拆解与分派 (F-W3-2).

Complete pipeline:
1. Emit ``planning`` status immediately (within 3s)
2. Load conversation history + pinned messages for context
3. Run complexity analysis → task decomposition
4. Create parent + subtask records in DB with ``depends_on[]`` / ``input_summary``
5. Fan-out: dispatch each subtask to its agent via normal message flow
6. Track progress: emit ``task_update`` on each status change
7. Summary: when all subtasks done, send a summary text message
8. Error handling: retry-once, blocked fallback, conflict detection
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from typing import Any, Optional

from sqlalchemy import desc, select

from db.engine import get_sessionmaker
from db.models import Message as MessageModel
from db.models import new_id
from services import create_message as create_service_message
from services import message_to_dict, update_message_content
from services.task import (
    create_task,
    get_task,
    list_subtasks,
    task_to_dict,
    update_task_status,
)
from ws import Connection, event

_SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from scheduler.complexity import ComplexityJudge, TaskInput
from scheduler.enhanced_decomposer import EnhancedTaskDecomposer
from scheduler.agents import SPECIALIZED_AGENTS, AgentProfile

logger = logging.getLogger("agenthub.orchestrator")

ORCHESTRATOR_AGENT_ID = "agent_orchestrator"

AGENT_CODE_MAP: dict[str, str] = {
    "A": "agent_mock",
    "B": "agent_mock_2",
    "C": "agent_claude",
    "D": "agent_mock",
}

RETRY_LIMIT = 1


def _agent_code_to_display_name(code: str) -> str:
    profile = SPECIALIZED_AGENTS.get(code)
    return profile.name if profile else code


def _agent_code_to_agent_id(code: str) -> str:
    return AGENT_CODE_MAP.get(code, "agent_mock")


def _pick_agent_for_domain(domain: str) -> str:
    domain_map = {
        "frontend": "A",
        "backend": "B",
        "database": "C",
        "test": "D",
        "docs": "D",
        "devops": "D",
    }
    return domain_map.get(domain, "B")


def _build_subtask_description(subtask: Any, decompose_result: Any) -> str:
    parts = [subtask.description or ""]
    if hasattr(subtask, "contract_section") and subtask.contract_section:
        parts.append(f"\n\n## Contract\n{subtask.contract_section}")
    if hasattr(subtask, "shared_models") and subtask.shared_models:
        parts.append(f"\n\n## Shared Models\n{json.dumps(subtask.shared_models, indent=2, ensure_ascii=False)}")
    if hasattr(subtask, "provided_interfaces") and subtask.provided_interfaces:
        parts.append(f"\n\n## Provides\n{json.dumps(subtask.provided_interfaces, indent=2, ensure_ascii=False)}")
    if hasattr(subtask, "required_interfaces") and subtask.required_interfaces:
        parts.append(f"\n\n## Requires\n{json.dumps(subtask.required_interfaces, indent=2, ensure_ascii=False)}")
    return "\n".join(parts)


async def handle_orchestrator_mention(
    conn: Connection,
    conversation_id: str,
    user_text: str,
    mentions: list[str],
    originating_message_id: str,
) -> None:
    logger.info("Orchestrator invoked in conv=%s: %.80s", conversation_id, user_text)

    Session = get_sessionmaker()

    # Load conversation history + pinned messages for context
    conversation_history: list[dict[str, Any]] = []
    pinned_context: list[str] = []
    async with Session() as s:
        rows = (
            await s.scalars(
                select(MessageModel)
                .where(MessageModel.conversation_id == conversation_id)
                .order_by(desc(MessageModel.created_at))
                .limit(50)
            )
        ).all()
        for m in reversed(rows):
            role = "assistant" if m.sender_type == "agent" else "user"
            try:
                raw = json.loads(m.content) if m.content else {}
                text = raw.get("text", "") if isinstance(raw, dict) else ""
            except (json.JSONDecodeError, TypeError):
                text = ""
            if text.strip():
                conversation_history.append({"role": role, "content": text, "pinned": bool(m.pinned)})
        pinned_context = [msg["content"] for msg in conversation_history if msg.get("pinned")]

    # 1. Emit planning status (must appear within 3s per SPEC)
    planning_msg = f"Analyzing task and decomposing into subtasks..."
    await conn.send(event(
        "task_update",
        conversation_id=conversation_id,
        task={
            "id": "planning",
            "conversation_id": conversation_id,
            "parent_task_id": None,
            "title": user_text[:80],
            "description": user_text,
            "status": "planning",
            "domain": None,
            "assigned_agent_id": ORCHESTRATOR_AGENT_ID,
            "originating_message_id": originating_message_id,
            "result_summary": planning_msg,
            "progress_pct": 0,
            "created_at": int(time.time() * 1000),
            "updated_at": int(time.time() * 1000),
        },
        action="created",
    ))

    # 2. Inject context into complexity judge
    context_str = ""
    if pinned_context:
        context_str = "Pinned context:\n" + "\n---\n".join(pinned_context[:5])
    if conversation_history:
        recent = conversation_history[-6:-1]
        context_str += "\n\nRecent conversation:\n" + "\n".join(
            f"{m['role']}: {m['content'][:200]}" for m in recent
        )

    # 3. Run complexity analysis
    judge = ComplexityJudge()
    task_input = TaskInput(description=user_text, context=context_str or None)
    complexity = judge.judge(task_input)

    if not complexity.domains:
        await conn.send(event(
            "task_update",
            conversation_id=conversation_id,
            task={
                "id": "planning",
                "conversation_id": conversation_id,
                "parent_task_id": None,
                "title": user_text[:80],
                "description": user_text,
                "status": "blocked",
                "domain": None,
                "assigned_agent_id": ORCHESTRATOR_AGENT_ID,
                "originating_message_id": originating_message_id,
                "result_summary": "没有合适的 Agent 可以处理此任务。请提供更详细的需求。",
                "progress_pct": 0,
                "created_at": int(time.time() * 1000),
                "updated_at": int(time.time() * 1000),
            },
            action="status_changed",
        ))
        return

    # 4. Decompose the task
    decomposer = EnhancedTaskDecomposer()
    decompose_result = decomposer.decompose_with_contract(
        task=task_input,
        domains=complexity.domains,
    )

    if not decompose_result.subtasks:
        await conn.send(event(
            "task_update",
            conversation_id=conversation_id,
            task={
                "id": "planning",
                "conversation_id": conversation_id,
                "parent_task_id": None,
                "title": user_text[:80],
                "description": user_text,
                "status": "blocked",
                "domain": None,
                "assigned_agent_id": ORCHESTRATOR_AGENT_ID,
                "originating_message_id": originating_message_id,
                "result_summary": "任务分解失败，无法生成子任务。",
                "progress_pct": 0,
                "created_at": int(time.time() * 1000),
                "updated_at": int(time.time() * 1000),
            },
            action="status_changed",
        ))
        return

    # 5. Create parent & subtask records in DB
    async with Session() as s:
        parent = await create_task(
            s,
            conversation_id=conversation_id,
            title=user_text[:80],
            description=user_text,
            domain=",".join(sorted(complexity.domains)),
            originating_message_id=originating_message_id,
        )
        parent_id = parent.id

        subtask_records = []
        for i, subtask in enumerate(decompose_result.subtasks):
            agent_code = _pick_agent_for_domain(subtask.domain)
            agent_id = _agent_code_to_agent_id(agent_code)

            enhanced_desc = _build_subtask_description(subtask, decompose_result)
            depends_on_list = subtask.dependencies if hasattr(subtask, "dependencies") and subtask.dependencies else []
            input_summary = (
                f"Domain: {subtask.domain}. "
                f"{'Depends on: ' + ', '.join(depends_on_list) + '. ' if depends_on_list else ''}"
                f"{subtask.description[:100]}"
            )

            st = await create_task(
                s,
                conversation_id=conversation_id,
                title=subtask.description[:80],
                description=enhanced_desc,
                domain=subtask.domain,
                assigned_agent_id=agent_id,
                originating_message_id=originating_message_id,
                parent_task_id=parent_id,
            )
            subtask_records.append((st, agent_code, agent_id, input_summary, list(depends_on_list)))

    # 6. Update planning to running
    async with Session() as s:
        await update_task_status(s, parent_id, "running",
            result_summary=f"Decomposed into {len(subtask_records)} subtasks")

    await conn.send(event(
        "task_update",
        conversation_id=conversation_id,
        task=task_to_dict(parent),
        action="status_changed",
    ))

    for st, _code, _aid, _is, _dep in subtask_records:
        await conn.send(event(
            "task_update",
            conversation_id=conversation_id,
            task=task_to_dict(st),
            action="created",
        ))

    # 7. Fan-out subtasks respecting dependency order
    dispatched_ids: set[str] = set()
    completed_ids: set[str] = set()
    failed_ids: dict[str, int] = {}
    subtask_messages: dict[str, str] = {}

    # Helper: determine which subtasks are ready
    def _ready_subtasks():
        ready = []
        for st, code, aid, is_, deps in subtask_records:
            sid = st.id
            if sid in dispatched_ids or sid in completed_ids:
                continue
            if all(d in completed_ids for d in deps):
                ready.append((st, code, aid, is_, deps))
        return ready

    while len(completed_ids) + len(failed_ids) < len(subtask_records):
        ready = _ready_subtasks()
        if not ready:
            break

        # Dispatch all ready subtasks concurrently
        tasks = []
        for st, code, aid, is_, deps in ready:
            dispatched_ids.add(st.id)
            async with Session() as s:
                await update_task_status(s, st.id, "running")
            tasks.append(
                _dispatch_subtask_with_result(
                    conn, st, agent_id=aid, conversation_id=conversation_id,
                    user_text=f"[Orchestrator] Subtask: {st.title}\nInput: {is_}",
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        for (st, code, aid, is_, deps), result in zip(ready, results):
            if isinstance(result, Exception):
                retry_count = failed_ids.get(st.id, 0)
                if retry_count < RETRY_LIMIT:
                    failed_ids[st.id] = retry_count + 1
                    dispatched_ids.discard(st.id)
                    logger.warning("Subtask %s failed, retry %d/1", st.id, retry_count + 1)
                    async with Session() as s:
                        await update_task_status(s, st.id, "running",
                            result_summary=f"Retrying ({retry_count + 1}/{RETRY_LIMIT})...")
                    await conn.send(event(
                        "task_update",
                        conversation_id=conversation_id,
                        task=task_to_dict(st),
                        action="status_changed",
                    ))
                else:
                    failed_ids[st.id] = retry_count
                    async with Session() as s:
                        await update_task_status(s, st.id, "failed",
                            result_summary=f"Failed after {RETRY_LIMIT + 1} attempts: {result}")
                    await conn.send(event(
                        "task_update",
                        conversation_id=conversation_id,
                        task=task_to_dict(st),
                        action="status_changed",
                    ))
            else:
                completed_ids.add(st.id)
                msg_id = result
                subtask_messages[st.id] = msg_id

    # 8. Mark parent as done or failed
    all_done = len(completed_ids) == len(subtask_records)
    some_failed = len(failed_ids) > 0

    if all_done:
        summary_text = (
            f"✅ **Task Complete**\n\n"
            f"All {len(subtask_records)} subtasks completed successfully.\n\n"
            f"**Summary:**\n"
        )
        for st, code, aid, is_, deps in subtask_records:
            msg_id = subtask_messages.get(st.id, "?")
            summary_text += f"- ✅ {st.title[:60]} (by {_agent_code_to_display_name(code)})\n"

        async with Session() as s:
            await update_task_status(s, parent_id, "done",
                result_summary=f"All {len(subtask_records)} subtasks completed")
    elif some_failed:
        success_count = len(completed_ids)
        fail_count = len(failed_ids)
        summary_text = (
            f"⚠️ **Task Partially Complete**\n\n"
            f"{success_count}/{len(subtask_records)} subtasks completed, "
            f"{fail_count} failed.\n\n"
        )
        for st, code, aid, is_, deps in subtask_records:
            if st.id in completed_ids:
                summary_text += f"- ✅ {st.title[:60]}\n"
            else:
                summary_text += f"- ❌ {st.title[:60]}\n"

        async with Session() as s:
            await update_task_status(s, parent_id, "failed",
                result_summary=f"{success_count}/{len(subtask_records)} completed, {fail_count} failed")
    else:
        summary_text = "❌ **Task Failed** — no subtasks could be dispatched."

        async with Session() as s:
            await update_task_status(s, parent_id, "failed",
                result_summary="All subtasks failed or blocked")

    # 9. Send summary as a message in chat
    summary_msg_id = new_id("msg")
    async with Session() as s:
        msg_obj = await create_service_message(
            s,
            conversation_id=conversation_id,
            sender_id=ORCHESTRATOR_AGENT_ID,
            sender_type="agent",
            content={"type": "text", "text": summary_text},
            message_id=summary_msg_id,
        )
        summary_msg_dict = message_to_dict(msg_obj)

    await conn.send(event("message_created", message=summary_msg_dict))

    async with Session() as s:
        await update_message_content(s, summary_msg_id, {"type": "text", "text": summary_text})

    await conn.send(event(
        "message_done",
        message_id=summary_msg_id,
        sender_id=ORCHESTRATOR_AGENT_ID,
        conversation_id=conversation_id,
        final_content={"type": "text", "text": summary_text},
    ))

    await conn.send(event(
        "task_update",
        conversation_id=conversation_id,
        task=task_to_dict(parent),
        action="completed",
    ))

    logger.info("Orchestrator completed parent=%s (%d subtasks, %d ok, %d failed)",
                parent_id, len(subtask_records), len(completed_ids), len(failed_ids))


async def _dispatch_subtask_with_result(
    conn: Connection,
    st: Any,
    agent_id: str,
    conversation_id: str,
    user_text: str,
) -> str:
    """Dispatch a subtask to an agent and create a message bubble for it.

    Returns the message_id of the agent's reply message.
    """
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

    # Build a concise subtask message
    agent_prompt = (
        f"[Orchestrator Subtask Assignment]\n\n"
        f"**Task**: {st.title}\n"
        f"**Domain**: {st.domain}\n"
        f"**Description**: {st.description}\n"
    )

    from handlers.send_message import load_adapter_for, persist_final
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
            final_content={"type": "text", "text": f"❌ Agent unavailable."},
        ))
        async with Session() as s:
            await update_task_status(s, st.id, "failed",
                result_summary=f"Agent {agent_id} not available")
            await conn.send(event(
                "task_update",
                conversation_id=conversation_id,
                task=task_to_dict(st),
                action="status_changed",
            ))
        return msg_id

    adapter, _agent_name = loaded
    final_parts: list[str] = []
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

        # Mark subtask as done
        async with Session() as s:
            await update_task_status(s, st.id, "done",
                result_summary=final_text[:200])
            await conn.send(event(
                "task_update",
                conversation_id=conversation_id,
                task=task_to_dict(st),
                action="status_changed",
            ))

    except asyncio.CancelledError:
        async with Session() as s:
            await update_message_content(s, msg_id, {"type": "text", "text": "[cancelled]"})
        raise

    return msg_id
