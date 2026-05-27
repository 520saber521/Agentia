"""Orchestrator main entry point — ``handle_orchestrator_mention``.

This is the top-level orchestrator pipeline: classify → decompose → DAG dispatch → aggregate.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from typing import Any

from sqlalchemy import desc, select

from db.engine import get_sessionmaker
from db.models import Agent, ConversationMember
from db.models import Message as MessageModel
from db.models import new_id
from services import create_message as create_service_message
from services import message_to_dict, update_message_content
from services.artifact import create_artifact as create_service_artifact
from services.task import (
    create_task,
    update_task_status,
    task_to_dict,
)
from ws import Connection, event

_SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
if _SRC_DIR not in sys.path:
    sys.path.append(_SRC_DIR)

from scheduler.complexity import ComplexityJudge, TaskInput
from scheduler.enhanced_decomposer import EnhancedTaskDecomposer

from dag_engine import DAG, DAGNode, DAGExecutor

from orchestrator.classifier import _llm_classify_task
from orchestrator.decomposer import (
    _build_subtask_description,
    _conflict_resolution_note,
    _ensure_preview_collaboration_domains,
    _pick_agent_for_domain,
)
from orchestrator.executor import _dispatch_subtask_with_retry
from orchestrator.preview import (
    _clean_requirement,
    _generate_preview_html_with_model,
    _should_create_w4_preview,
)

logger = logging.getLogger("agenthub.orchestrator")

ORCHESTRATOR_AGENT_ID = "agent_orchestrator"


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
    planning_msg = "正在理解用户意图、分析上下文并准备拆解任务..."
    process_text = (
        "🧭 **Orchestrator 已接管任务**\n\n"
        f"- 用户意图：{_clean_requirement(user_text)[:180]}\n"
        f"- 上下文：已读取最近 {len(conversation_history)} 条消息，包含 {len(pinned_context)} 条 pin 长期上下文\n"
        "- 协调策略：先拆解，再按 Agent 能力并行分派，最后聚合结果并检测冲突"
    )
    await conn.send(event(
        "stream_chunk",
        message_id=originating_message_id,
        sender_id=ORCHESTRATOR_AGENT_ID,
        conversation_id=conversation_id,
        seq=1,
        delta=process_text,
    ))
    async with Session() as s:
        await update_message_content(s, originating_message_id, {"type": "text", "text": process_text})

    await conn.send(event(
        "context_info",
        conversation_id=conversation_id,
        total_messages=len(conversation_history),
        pinned_messages=len(pinned_context),
    ))

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

    # 2. LLM-based task classification (replace keyword ComplexityJudge)
    llm_type = await _llm_classify_task(user_text)

    if llm_type == "non_software":
        complexity_domains = {"code"}
    else:
        judge = ComplexityJudge()
        task_input = TaskInput(description=user_text, context=None)
        complexity = judge.judge(task_input)
        complexity_domains = set(complexity.domains)
        complexity_domains = _ensure_preview_collaboration_domains(user_text, complexity_domains)
        if not complexity_domains:
            complexity_domains = {"code"}

    # 3. Build prompt context for subtask description
    context_str = ""
    if pinned_context:
        context_str = "Pinned context:\n" + "\n---\n".join(pinned_context[:5]) + "\n"

    # 4. Create subtasks
    if llm_type == "non_software":
        decompose_subtasks = [
            type("_", (), {
                "id": "task_code",
                "description": _clean_requirement(user_text),
                "domain": "code",
                "dependencies": [],
            })()
        ]
        decompose_result = None
    else:
        decomposer = EnhancedTaskDecomposer()
        task_input = TaskInput(description=user_text, context=context_str or None)
        decompose_result = decomposer.decompose_with_contract(
            task=task_input,
            domains=complexity_domains,
        )
        decompose_subtasks = decompose_result.subtasks
        if not decompose_subtasks:
            decompose_subtasks = [
                type("_", (), {
                    "id": "fallback_1",
                    "description": _clean_requirement(user_text),
                    "domain": next(iter(complexity_domains)),
                    "dependencies": [],
                })()
            ]

    # 5. Create parent & subtask records in DB
    async with Session() as s:
        parent = await create_task(
            s,
            conversation_id=conversation_id,
            title=user_text[:80],
            description=user_text,
            domain=",".join(sorted(complexity_domains)),
            originating_message_id=originating_message_id,
        )
        parent_id = parent.id

        subtask_records = []
        subtask_id_map = {}
        for i, subtask in enumerate(decompose_subtasks):
            agent_id, agent_name = await _pick_agent_for_domain(
                s,
                domain=subtask.domain,
                conversation_id=conversation_id,
            )

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
                agent_name=agent_name,
                originating_message_id=originating_message_id,
                parent_task_id=parent_id,
            )
            subtask_id_map[subtask.id] = st.id
            subtask_records.append((st, agent_name, agent_id, input_summary, list(depends_on_list)))

        subtask_records = [
            (
                st,
                agent_name,
                agent_id,
                input_summary,
                [subtask_id_map[d] for d in depends_on_list if d in subtask_id_map],
            )
            for st, agent_name, agent_id, input_summary, depends_on_list in subtask_records
        ]

    # 6. Update planning to running
    async with Session() as s:
        parent = await update_task_status(s, parent_id, "running",
            result_summary=f"Decomposed into {len(subtask_records)} subtasks")

    await conn.send(event(
        "task_update",
        conversation_id=conversation_id,
        task=task_to_dict(parent),
        action="status_changed",
    ))

    dispatch_plan = "\n".join(
        f"- {st.title[:60]} → {agent_name} ({st.domain or 'general'})"
        for st, agent_name, _aid, _is, _dep in subtask_records
    )
    await conn.send(event(
        "stream_chunk",
        message_id=originating_message_id,
        sender_id=ORCHESTRATOR_AGENT_ID,
        conversation_id=conversation_id,
        seq=2,
        delta=f"\n\n📌 **任务拆解完成，共 {len(subtask_records)} 个子任务：**\n{dispatch_plan}",
    ))

    for st, _agent_name, _aid, _is, _dep in subtask_records:
        task_dict = task_to_dict(st)
        task_dict["depends_on"] = _dep
        await conn.send(event(
            "task_update",
            conversation_id=conversation_id,
            task=task_dict,
            action="created",
        ))

    # 7. Build DAG and execute via event-driven DAG engine
    dag = DAG()
    for st, _agent_name, _agent_id, _input_summary, deps in subtask_records:
        dag.add_node(DAGNode(
            id=st.id,
            domain=st.domain or "",
            description=st.description or "",
            title=st.title or "",
            dependencies=list(deps),
            assigned_agent_id=_agent_id,
            assigned_agent_name=_agent_name,
            input_summary=_input_summary,
            metadata={"task_record": st},
        ))

    async def _dispatch_node(node: DAGNode) -> str:
        st = node.metadata["task_record"]
        async with Session() as s:
            updated = await update_task_status(s, st.id, "running")
        if updated is not None:
            await conn.send(event(
                "task_update",
                conversation_id=conversation_id,
                task=task_to_dict(updated),
                task_id=updated.parent_task_id or updated.id,
                subtask_id=updated.id if updated.parent_task_id else None,
                status=updated.status,
                progress=updated.progress_pct,
                message_id=None,
                action="status_changed",
            ))
        return await _dispatch_subtask_with_retry(
            conn, st,
            agent_id=node.assigned_agent_id,
            conversation_id=conversation_id,
            user_text=(
                f"[Orchestrator] Subtask: {node.title}\nInput: {node.input_summary}"
            ),
            pinned_context=pinned_context,
        )

    executor = DAGExecutor(dag, _dispatch_node, max_concurrency=len(subtask_records))
    dag_result = await executor.execute()

    completed_ids: set[str] = dag_result["completed"]
    failed_ids: set[str] = dag_result["failed"]
    subtask_messages: dict[str, str] = dag_result["subtask_messages"]

    # 8. Mark parent as done or failed
    all_done = len(completed_ids) == len(subtask_records)
    some_failed = len(failed_ids) > 0

    w4_artifact: dict[str, Any] | None = None

    if all_done:
        summary_text = (
            f"✅ **Task Complete**\n\n"
            f"All {len(subtask_records)} subtasks completed successfully.\n\n"
            f"**Summary:**\n"
        )

        if _should_create_w4_preview(user_text):
            try:
                html_content, preview_title, preview_source = await _generate_preview_html_with_model(
                    conversation_id=conversation_id,
                    user_text=user_text,
                    conversation_history=conversation_history,
                    subtask_records=subtask_records,
                    subtask_messages=subtask_messages,
                )
                async with Session() as s:
                    artifact = await create_service_artifact(
                        s,
                        conversation_id=conversation_id,
                        kind="preview",
                        title=preview_title,
                        mime_type="text/html",
                        file_name="orchestrator-preview.html",
                        content=html_content,
                        source_message_id=originating_message_id,
                        created_by=ORCHESTRATOR_AGENT_ID,
                        meta={
                            "source": "orchestrator",
                            "preview_source": preview_source,
                            "parent_task_id": parent_id,
                            "language": "html",
                        },
                    )
                    w4_artifact = artifact
                summary_text += f"\n📄 已生成模型 HTML 预览产物：`{artifact['id']}` ({preview_source})\n"
            except Exception as exc:
                logger.warning("Failed to create W4 preview artifact: %s", exc)
        for st, agent_name, aid, is_, deps in subtask_records:
            msg_id = subtask_messages.get(st.id, "?")
            summary_text += f"- ✅ {st.title[:60]} (by {agent_name})\n"
        summary_text += f"\n{_conflict_resolution_note(subtask_records)}\n"

        async with Session() as s:
            parent = await update_task_status(s, parent_id, "done",
                result_summary=f"All {len(subtask_records)} subtasks completed")
    elif some_failed:
        success_count = len(completed_ids)
        fail_count = len(failed_ids)
        summary_text = (
            f"⚠️ **Task Partially Complete**\n\n"
            f"{success_count}/{len(subtask_records)} subtasks completed, "
            f"{fail_count} failed.\n\n"
        )
        for st, agent_name, aid, is_, deps in subtask_records:
            if st.id in completed_ids:
                summary_text += f"- ✅ {st.title[:60]}\n"
            else:
                summary_text += f"- ❌ {st.title[:60]}\n"
        summary_text += f"\nFailure degradation: completed outputs were preserved and failed subtasks were isolated.\n{_conflict_resolution_note(subtask_records)}\n"

        async with Session() as s:
            parent = await update_task_status(s, parent_id, "failed",
                result_summary=f"{success_count}/{len(subtask_records)} completed, {fail_count} failed")
    else:
        blocked_count = len(subtask_records) - len(completed_ids) - len(failed_ids)
        summary_text = (
            f"⚠️ **Task Blocked**\n\n"
            f"{len(completed_ids)}/{len(subtask_records)} subtasks completed, "
            f"{blocked_count} blocked by unresolved dependencies.\n\n"
        )
        for st, agent_name, aid, is_, deps in subtask_records:
            if st.id in completed_ids:
                summary_text += f"- ✅ {st.title[:60]}\n"
            else:
                summary_text += f"- ⏸️ {st.title[:60]}\n"
                async with Session() as s:
                    updated = await update_task_status(s, st.id, "failed",
                        result_summary="Blocked by unresolved dependencies")
                if updated is not None:
                    await conn.send(event(
                        "task_update",
                        conversation_id=conversation_id,
                        task=task_to_dict(updated),
                        task_id=updated.parent_task_id or updated.id,
                        subtask_id=updated.id if updated.parent_task_id else None,
                        status=updated.status,
                        progress=updated.progress_pct,
                        message_id=None,
                        action="status_changed",
                    ))
        summary_text += f"\nFailure degradation: blocked subtasks were reported without discarding completed work.\n{_conflict_resolution_note(subtask_records)}\n"

        async with Session() as s:
            parent = await update_task_status(s, parent_id, "failed",
                result_summary="Some subtasks were blocked by unresolved dependencies")

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
        "message_done",
        message_id=originating_message_id,
        sender_id=ORCHESTRATOR_AGENT_ID,
        conversation_id=conversation_id,
        final_content={"type": "text", "text": process_text + "\n\n" + summary_text},
    ))

    if w4_artifact is not None:
        preview_msg_id = new_id("msg")
        preview_content = {
            "type": "preview",
            "artifact_id": w4_artifact["id"],
            "title": w4_artifact["title"],
            "mimeType": w4_artifact["mime_type"],
            "fileSize": w4_artifact["file_size"],
            "url": w4_artifact.get("url"),
            "previewUrl": w4_artifact.get("preview_url"),
            "version": w4_artifact.get("version", 1),
        }
        async with Session() as s:
            preview_msg = await create_service_message(
                s,
                conversation_id=conversation_id,
                sender_id=ORCHESTRATOR_AGENT_ID,
                sender_type="agent",
                content=preview_content,
                message_id=preview_msg_id,
                artifact_id=w4_artifact["id"],
            )
            preview_msg_dict = message_to_dict(preview_msg)
        await conn.send(event("message_created", message=preview_msg_dict))
        await conn.send(event(
            "artifact_ready",
            conversation_id=conversation_id,
            artifact=w4_artifact,
            message_id=preview_msg_id,
        ))
        await conn.send(event(
            "message_done",
            message_id=preview_msg_id,
            sender_id=ORCHESTRATOR_AGENT_ID,
            conversation_id=conversation_id,
            final_content=preview_content,
        ))

    await conn.send(event(
        "task_update",
        conversation_id=conversation_id,
        task=task_to_dict(parent),
        action="completed",
    ))

    logger.info("Orchestrator completed parent=%s (%d subtasks, %d ok, %d failed)",
                parent_id, len(subtask_records), len(completed_ids), len(failed_ids))
