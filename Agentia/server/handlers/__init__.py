"""ClientEvent dispatch: ``dispatch(conn, raw)`` is the single entry point.

Owns the ``HANDLERS`` registry. Ping and echo are inlined (trivial);
join / send_message / cancel live in sibling modules and are registered
explicitly at the bottom of this file to avoid circular imports.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Awaitable, Callable

from ws import Connection, event

logger = logging.getLogger("agenthub.handlers")

HandlerT = Callable[[Connection, dict[str, Any]], Awaitable[None]]

HANDLERS: dict[str, HandlerT] = {}


async def dispatch(conn: Connection, raw: str) -> None:
    try:
        evt = json.loads(raw)
    except json.JSONDecodeError:
        await conn.send(event("error", code="bad_json", message="message must be JSON"))
        return
    if not isinstance(evt, dict):
        await conn.send(event("error", code="bad_shape", message="event must be a JSON object"))
        return

    typ = evt.get("type")
    handler = HANDLERS.get(typ) if isinstance(typ, str) else None
    if handler is None:
        await conn.send(
            event("error", code="unknown_event", message=f"unsupported event type: {typ!r}")
        )
        return
    await handler(conn, evt)


# ---------------------------------------------------------------------------
# Inline trivial handlers
# ---------------------------------------------------------------------------


async def _handle_ping(conn: Connection, evt: dict[str, Any]) -> None:
    await conn.send(event("pong"))


async def _handle_echo(conn: Connection, evt: dict[str, Any]) -> None:
    await conn.send(
        event(
            "echo",
            message_id=evt.get("message_id") or f"msg_{uuid.uuid4().hex[:8]}",
            payload=evt.get("payload"),
        )
    )


HANDLERS["ping"] = _handle_ping
HANDLERS["echo"] = _handle_echo


# ---------------------------------------------------------------------------
# Register from sibling modules
# ---------------------------------------------------------------------------

from . import join, send_message, cancel  # noqa: E402

HANDLERS["join"] = join.handle
HANDLERS["send_message"] = send_message.handle
HANDLERS["cancel"] = cancel.handle
