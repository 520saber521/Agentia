"""Trace entry creation and querying — F-W3-1.

Each message routing hop (user → Router → Adapter → done) is recorded
as a ``TraceEntry`` in the database, allowing end-to-end traceability.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import TraceEntry, new_id, now_ms

TRACE_ID_PREFIX = "trace"


def trace_entry_to_dict(t: TraceEntry) -> dict[str, Any]:
    return {
        "id": t.id,
        "message_id": t.message_id,
        "conversation_id": t.conversation_id,
        "trace_id": t.trace_id,
        "node_id": t.node_id,
        "node_role": t.node_role,
        "event": t.event,
        "status": t.status,
        "detail": t.detail,
        "seq": t.seq,
        "created_at": t.created_at,
    }


async def create_trace_entry(
    s: AsyncSession,
    *,
    message_id: str,
    conversation_id: str,
    trace_id: str,
    node_id: str,
    node_role: str,
    event: str,
    status: str = "ok",
    detail: Optional[str] = None,
    seq: int = 0,
) -> dict[str, Any]:
    ts = now_ms()
    entry = TraceEntry(
        id=new_id("trc"),
        message_id=message_id,
        conversation_id=conversation_id,
        trace_id=trace_id,
        node_id=node_id,
        node_role=node_role,
        event=event,
        status=status,
        detail=detail,
        seq=seq,
        created_at=ts,
    )
    s.add(entry)
    await s.commit()
    return trace_entry_to_dict(entry)


async def get_trace_for_message(
    s: AsyncSession,
    message_id: str,
    *,
    include_related: bool = True,
) -> list[dict[str, Any]]:
    """Get all trace entries for a given message, ordered by seq ASC.

    If ``include_related`` is True, also fetches entries with the same ``trace_id``
    so that the full fan-out trace can be reconstructed.
    """
    entry = await s.scalar(
        select(TraceEntry).where(TraceEntry.message_id == message_id).limit(1)
    )
    if entry is None:
        return []

    if include_related and entry.trace_id:
        rows = (
            await s.scalars(
                select(TraceEntry)
                .where(TraceEntry.trace_id == entry.trace_id)
                .order_by(TraceEntry.seq, TraceEntry.created_at)
            )
        ).all()
        return [trace_entry_to_dict(r) for r in rows]

    rows = (
        await s.scalars(
            select(TraceEntry)
            .where(TraceEntry.message_id == message_id)
            .order_by(TraceEntry.seq, TraceEntry.created_at)
        )
    ).all()
    return [trace_entry_to_dict(r) for r in rows]
