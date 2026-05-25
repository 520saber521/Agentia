"""Task 业务封装 — W3 F-W3-3 task 表 + 状态机。

状态机:
  pending → running → done
                  ↘ failed
                  ↘ cancelled

每个状态转换都会触发 ``task_update`` WS 事件（由调用方在 handle 中发送）。
"""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import asc, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Task, new_id, now_ms

VALID_STATUSES = frozenset({"planning", "pending", "running", "done", "failed", "blocked", "conflict"})

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "planning": frozenset({"pending", "running", "blocked", "failed"}),
    "pending": frozenset({"running", "blocked", "failed", "conflict"}),
    "running": frozenset({"done", "failed", "blocked", "conflict"}),
    "done": frozenset(),
    "failed": frozenset(),
    "blocked": frozenset({"running", "failed"}),
    "conflict": frozenset({"running", "failed", "blocked"}),
}


def task_to_dict(t: Task) -> dict[str, Any]:
    return {
        "id": t.id,
        "conversation_id": t.conversation_id,
        "parent_task_id": t.parent_task_id,
        "title": t.title,
        "description": t.description,
        "status": t.status,
        "domain": t.domain,
        "assigned_agent_id": t.assigned_agent_id,
        "agent_name": t.agent_name,
        "originating_message_id": t.originating_message_id,
        "result_summary": t.result_summary,
        "progress_pct": t.progress_pct,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }


def _validate_transition(current: str, next_status: str) -> None:
    allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
    if next_status not in allowed:
        raise ValueError(
            f"invalid task status transition: {current} -> {next_status}; "
            f"allowed from {current}: {sorted(allowed)}"
        )


async def create_task(
    s: AsyncSession,
    *,
    conversation_id: str,
    title: str,
    description: str,
    domain: Optional[str] = None,
    assigned_agent_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    originating_message_id: Optional[str] = None,
    parent_task_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> Task:
    ts = now_ms()
    t = Task(
        id=task_id or new_id("task"),
        conversation_id=conversation_id,
        parent_task_id=parent_task_id,
        title=title,
        description=description,
        domain=domain,
        assigned_agent_id=assigned_agent_id,
        agent_name=agent_name,
        originating_message_id=originating_message_id,
        status="pending",
        created_at=ts,
        updated_at=ts,
    )
    s.add(t)
    await s.commit()
    return t


async def update_task_status(
    s: AsyncSession,
    task_id: str,
    status: str,
    *,
    result_summary: Optional[str] = None,
    progress_pct: Optional[int] = None,
) -> Optional[Task]:
    t = await s.get(Task, task_id)
    if t is None:
        return None
    _validate_transition(t.status, status)
    t.status = status
    t.updated_at = now_ms()
    if result_summary is not None:
        t.result_summary = result_summary
    if progress_pct is not None:
        t.progress_pct = max(0, min(100, int(progress_pct)))
    await s.commit()
    return t


async def get_task(s: AsyncSession, task_id: str) -> Optional[dict[str, Any]]:
    t = await s.get(Task, task_id)
    return task_to_dict(t) if t else None


async def list_tasks(
    s: AsyncSession,
    conversation_id: str,
    *,
    status_filter: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    stmt = (
        select(Task)
        .where(Task.conversation_id == conversation_id)
        .order_by(desc(Task.created_at))
        .limit(limit)
    )
    if status_filter and status_filter in VALID_STATUSES:
        stmt = stmt.where(Task.status == status_filter)
    rows = (await s.scalars(stmt)).all()
    return [task_to_dict(t) for t in rows]


async def list_subtasks(
    s: AsyncSession, parent_task_id: str
) -> list[dict[str, Any]]:
    rows = (
        await s.scalars(
            select(Task)
            .where(Task.parent_task_id == parent_task_id)
            .order_by(asc(Task.created_at))
        )
    ).all()
    return [task_to_dict(t) for t in rows]
