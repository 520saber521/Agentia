"""Trace REST endpoint — F-W3-1: Router 接入与 trace 链路。

| Method | Path | Description |
|--------|------|-------------|
| GET | ``/api/trace/{message_id}`` | Return ordered trace entries for a message |
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from db.engine import get_sessionmaker
from services.trace import get_trace_for_message

router = APIRouter(prefix="/api", tags=["trace"])


@router.get("/trace/{message_id}")
async def api_trace(message_id: str) -> dict:
    """Return the full trace for a message, ordered by seq ASC."""
    Session = get_sessionmaker()
    async with Session() as s:
        entries = await get_trace_for_message(s, message_id)

    return {
        "message_id": message_id,
        "trace": entries,
        "count": len(entries),
    }
