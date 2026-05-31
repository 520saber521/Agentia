"""WS Hub: Connection management, event helpers.

Extracted from ``main.py`` during W2-D1 split.

Owns:
- :class:`Connection` — single WebSocket runtime state
- :class:`WSHub` — connection set with thread-safe add/remove
- :func:`event` — server event builder
- :func:`now_ms` — monotonic millisecond timestamp
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from services.animation_bus import AnimationEvent, animation_bus

logger = logging.getLogger("agenthub.ws")


def now_ms() -> int:
    return int(time.time() * 1000)


def event(type_: str, **payload: Any) -> dict[str, Any]:
    """Build a ServerEvent dict with stable fields."""
    return {"type": type_, "ts": now_ms(), **payload}


class Connection:
    """Single WebSocket runtime state.

    - ``outbound`` — single-writer queue for all outbound events.
    - ``in_flight`` — tracks each ``message_id`` -> asyncio.Task.
    - ``joined_conversations`` — set of conversation_ids the client has joined.
    """

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.conn_id = uuid.uuid4().hex[:8]
        self.outbound: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=1024)
        self.in_flight: dict[str, asyncio.Task[Any]] = {}
        self.joined_conversations: set[str] = set()
        self._closed = False

    async def send(self, evt: dict[str, Any]) -> None:
        if self._closed:
            return
        try:
            self.outbound.put_nowait(evt)
        except asyncio.QueueFull:
            # Queue is full — drop low-priority events to avoid blocking producers
            evt_type = evt.get("type", "")
            if evt_type in ("stream_chunk", "usage"):
                return  # Final content arrives via message_done
            # Critical events (message_done, error, etc.): block until space
            await self.outbound.put(evt)

    async def writer(self) -> None:
        try:
            while True:
                evt = await self.outbound.get()
                if evt is None:
                    return
                await self.ws.send_json(evt)
        except WebSocketDisconnect:
            return
        except Exception:
            logger.exception("ws[%s] writer crashed", self.conn_id)

    async def close(self) -> None:
        self._closed = True
        for mid, task in list(self.in_flight.items()):
            task.cancel()
            self.in_flight.pop(mid, None)
        await self.outbound.put(None)


class WSHub:
    """Thread-safe set of active connections."""

    def __init__(self) -> None:
        self._conns: set[Connection] = set()
        self._lock = asyncio.Lock()

    async def add(self, c: Connection) -> None:
        async with self._lock:
            self._conns.add(c)

    async def remove(self, c: Connection) -> None:
        async with self._lock:
            self._conns.discard(c)

    async def broadcast_conversation(
        self, conversation_id: str, evt: dict[str, Any]
    ) -> None:
        """Send an event to every open socket that joined the conversation."""
        async with self._lock:
            conns = list(self._conns)
        for conn in conns:
            if conversation_id in conn.joined_conversations:
                await conn.send(evt)

    @property
    def size(self) -> int:
        return len(self._conns)


hub = WSHub()


def _forward_animation_event(evt: AnimationEvent) -> None:
    conversation_id = str(evt.data.get("conversation_id") or "")
    if not conversation_id:
        return
    ws_event = {
        "type": evt.type,
        "ts": int(evt.at),
        "event_id": evt.id,
        **evt.data,
    }
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(hub.broadcast_conversation(conversation_id, ws_event))


animation_bus.subscribe(_forward_animation_event)
