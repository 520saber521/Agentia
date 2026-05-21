"""``cancel`` handler — cancel an in-flight agent reply.

Extracted from ``main.py`` during W2-D1 split.
"""

from __future__ import annotations

from typing import Any

from ws import Connection, event


async def handle(conn: Connection, evt: dict[str, Any]) -> None:
    mid = evt.get("message_id")
    if not isinstance(mid, str) or not mid:
        await conn.send(event("error", code="bad_cancel", message="cancel.message_id required"))
        return
    task = conn.in_flight.get(mid)
    if task is None:
        await conn.send(
            event("error", code="not_found", message=f"no in-flight message {mid!r}")
        )
        return
    task.cancel()
