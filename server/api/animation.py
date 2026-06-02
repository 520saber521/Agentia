from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from services.animation_bus import AnimationEvent, animation_bus

router = APIRouter(prefix="/api", tags=["animation"])


def _payload(evt: AnimationEvent) -> dict[str, Any]:
    return {
        "type": evt.type,
        "ts": int(evt.at),
        "event_id": evt.id,
        **evt.data,
    }


def _sse(evt: AnimationEvent) -> str:
    return f"id: {evt.id}\nevent: {evt.type}\ndata: {json.dumps(_payload(evt), ensure_ascii=False)}\n\n"


@router.get("/animation-stream")
async def animation_stream(
    conversation_id: str | None = Query(default=None),
    after_id: str = Query(default=""),
) -> StreamingResponse:
    """Stream workspace animation events to the frontend.

    This mirrors the swarm-ide UI bus pattern: a small replay buffer first,
    followed by live events over a long-lived SSE response.
    """

    queue: asyncio.Queue[AnimationEvent] = asyncio.Queue(maxsize=200)

    def accepts(evt: AnimationEvent) -> bool:
        if not conversation_id:
            return True
        return evt.data.get("conversation_id") == conversation_id

    def listener(evt: AnimationEvent) -> None:
        if not accepts(evt):
            return
        try:
            queue.put_nowait(evt)
        except asyncio.QueueFull:
            pass

    async def gen():
        for evt in animation_bus.get_since(after_id):
            if accepts(evt):
                yield _sse(evt)

        animation_bus.subscribe(listener)
        try:
            while True:
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=15)
                    yield _sse(evt)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            animation_bus.unsubscribe(listener)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
