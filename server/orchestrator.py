"""Orchestrator — wraps src/scheduler for @Orchestrator task decomposition.

W3 F-W3-2: When a user sends a message with ``@Orchestrator`` mention,
the Orchestrator will:

1. Run complexity analysis via ``ComplexityJudge``
2. Decompose the task into subtasks (via ``EnhancedTaskDecomposer``)
3. Create ``Task`` records for each subtask
4. Fan-out each subtask to the appropriate agent
5. Track progress and emit ``task_update`` WS events
6. Aggregate results when all subtasks are done

This module is stateless and async-safe.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any, Optional

from db.engine import get_sessionmaker
from services.task import create_task, list_subtasks, task_to_dict, update_task_status
from ws import Connection, event

# Ensure src/ is on path so we can import from src.scheduler
_SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from scheduler.complexity import ComplexityJudge, TaskInput  # noqa: E402
from scheduler.enhanced_decomposer import EnhancedTaskDecomposer  # noqa: E402
from scheduler.agents import SPECIALIZED_AGENTS, AgentProfile  # noqa: E402

logger = logging.getLogger("agenthub.orchestrator")

ORCHESTRATOR_AGENT_ID = "agent_orchestrator"

# Map scheduler agent codes (A/B/C/D) to actual BFF agent IDs
AGENT_CODE_MAP: dict[str, str] = {
    "A": "agent_mock",
    "B": "agent_mock_2",
    "C": "agent_claude",
    "D": "agent_mock",
}


def _agent_code_to_display_name(code: str) -> str:
    profile = SPECIALIZED_AGENTS.get(code)
    if profile:
        return profile.name
    return code


def _agent_code_to_agent_id(code: str) -> str:
    return AGENT_CODE_MAP.get(code, "agent_mock")


async def handle_orchestrator_mention(
    conn: Connection,
    conversation_id: str,
    user_text: str,
    mentions: list[str],
    originating_message_id: str,
) -> None:
    """Entry point: called when a user message mentions Orchestrator.

    This runs the full schedule → decompose → fan-out pipeline.
    """
    logger.info("Orchestrator invoked in conv=%s: %.80s", conversation_id, user_text)

    # 1. Run complexity analysis
    judge = ComplexityJudge()
    task_input = TaskInput(description=user_text)
    complexity = judge.judge(task_input)

    # 2. Decompose the task
    decomposer = EnhancedTaskDecomposer()
    decompose_result = decomposer.decompose_with_contract(
        task=task_input,
        domains=complexity.domains,
    )

    # 3. Create parent task in DB
    Session = get_sessionmaker()
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

        # 4. Create subtasks in DB
        subtask_records = []
        for subtask in decompose_result.subtasks:
            agent_code = _pick_agent_for_domain(subtask.domain)
            agent_id = _agent_code_to_agent_id(agent_code)

            enhanced_desc = _build_subtask_description(subtask, decompose_result)

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
            subtask_records.append((st, agent_code, agent_id))

    # 5. Emit initial task_status card for parent
    await conn.send(event(
        "task_update",
        conversation_id=conversation_id,
        task=task_to_dict(parent),
        action="created",
    ))

    for st, _code, _aid in subtask_records:
        await conn.send(event(
            "task_update",
            conversation_id=conversation_id,
            task=task_to_dict(st),
            action="created",
        ))

    # 6. Fan-out each subtask concurrently
    logger.info(
        "Orchestrator fanned out %d subtasks (parent=%s)",
        len(subtask_records),
        parent_id,
    )

    # Mark parent as running
    async with Session() as s:
        await update_task_status(s, parent_id, "running")

    subtask_count = len(subtask_records)

    # 7. Send individual agent tasks
    for st, agent_code, agent_id in subtask_records:
        await _dispatch_subtask(
            conn, st, agent_code, agent_id, conversation_id,
        )

    # 8. Emit completion for each subtask (simplified: mark all done immediately)
    # In a full implementation, we'd wait for agent replies; for now,
    # since we're working with mock/claude adapters that stream through BFF,
    # we mark tasks and emit task_update events.
    async with Session() as s:
        await update_task_status(s, parent_id, "done", result_summary=f"All {subtask_count} subtasks dispatched")

    await conn.send(event(
        "task_update",
        conversation_id=conversation_id,
        task=task_to_dict(parent),
        action="completed",
    ))


async def _dispatch_subtask(
    conn: Connection,
    st: Any,
    agent_code: str,
    agent_id: str,
    conversation_id: str,
) -> None:
    """Send a single subtask to the appropriate agent.

    In the full implementation this would send a message through the
    appropriate adapter. For now, we create a placeholder message and
    mark the task as running.
    """
    Session = get_sessionmaker()
    async with Session() as s:
        await update_task_status(s, st.id, "running")
        task_dict = task_to_dict(st)
        await conn.send(event(
            "task_update",
            conversation_id=conversation_id,
            task=task_dict,
            action="status_changed",
        ))

    logger.debug(
        "Dispatched subtask %s to agent %s (%s)",
        st.id,
        agent_code,
        agent_id,
    )


def _pick_agent_for_domain(domain: str) -> str:
    """Map a domain name to an agent code (A/B/C/D)."""
    domain_map = {
        "frontend": "A",
        "backend": "B",
        "database": "C",
        "test": "D",
        "docs": "D",
        "devops": "D",
    }
    return domain_map.get(domain, "B")


def _build_subtask_description(
    subtask: Any,
    decompose_result: Any,
) -> str:
    """Build a rich description for a subtask including contract info."""
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
