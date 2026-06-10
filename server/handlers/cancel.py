"""``cancel`` handler — cancel an in-flight agent reply.

Extracted from ``main.py`` during W2-D1 split.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from db import get_sessionmaker
from db.models import Message, Task
from ws import Connection, event, in_flight_registry


ORCHESTRATOR_AGENT_ID = "agent_orchestrator"
ACTIVE_TASK_STATUSES = {"planning", "pending", "running"}


async def _orchestrator_has_active_subtasks(message_id: str) -> bool:
    Session = get_sessionmaker()
    async with Session() as s:
        message = await s.get(Message, message_id)
        if message is None or message.sender_id != ORCHESTRATOR_AGENT_ID:
            return False
        active_task_id = await s.scalar(
            select(Task.id)
            .where(
                Task.originating_message_id == message_id,
                Task.parent_task_id.is_not(None),
                Task.status.in_(ACTIVE_TASK_STATUSES),
            )
            .limit(1)
        )
        return active_task_id is not None


async def handle(conn: Connection, evt: dict[str, Any]) -> None:
    mid = evt.get("message_id")
    if not isinstance(mid, str) or not mid:
        await conn.send(event("error", code="bad_cancel", message="cancel.message_id required"))
        return
    task = await in_flight_registry.get(mid)
    if task is None:
        await conn.send(
            event("error", code="not_found", message=f"no in-flight message {mid!r}")
        )
        return
    if await _orchestrator_has_active_subtasks(mid):
        await conn.send(
            event(
                "error",
                code="orchestrator_subtasks_running",
                message="Orchestrator is waiting for active subtasks and cannot be cancelled yet",
            )
        )
        return
    task.cancel()
