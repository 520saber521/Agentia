from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class AnimationEvent:
    id: str
    at: float
    type: str
    data: dict[str, Any]


class AnimationEventBus:
    def __init__(self, max_buffer: int = 2000) -> None:
        self._next_id = 0
        self._buffer: list[AnimationEvent] = []
        self._listeners: list[Callable[[AnimationEvent], None]] = []
        self._max_buffer = max_buffer

    def _next_event_id(self) -> str:
        self._next_id += 1
        return f"anim_evt_{self._next_id}"

    def emit(self, event_type: str, data: dict[str, Any]) -> AnimationEvent:
        evt = AnimationEvent(
            id=self._next_event_id(),
            at=time.time() * 1000,
            type=event_type,
            data=data,
        )
        self._buffer.append(evt)
        if len(self._buffer) > self._max_buffer:
            self._buffer = self._buffer[-self._max_buffer:]
        for listener in list(self._listeners):
            try:
                listener(evt)
            except Exception:
                pass
        return evt

    def subscribe(self, listener: Callable[[AnimationEvent], None]) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def unsubscribe(self, listener: Callable[[AnimationEvent], None]) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def get_since(self, after_id: str) -> list[AnimationEvent]:
        if not after_id:
            return list(self._buffer)
        found = False
        result: list[AnimationEvent] = []
        for evt in self._buffer:
            if found:
                result.append(evt)
            elif evt.id == after_id:
                found = True
        return result

    def agent_created(
        self,
        *,
        conversation_id: str,
        agent_id: str,
        role: str,
        parent_id: str | None = None,
        domain: str | None = None,
        agent_name: str | None = None,
    ) -> AnimationEvent:
        return self.emit("anim_agent_created", {
            "conversation_id": conversation_id,
            "agent": {
                "id": agent_id,
                "role": role,
                "parentId": parent_id,
                "domain": domain,
                "agentName": agent_name,
            },
        })

    def agent_status(
        self,
        *,
        conversation_id: str,
        agent_id: str,
        status: str,
    ) -> AnimationEvent:
        return self.emit("anim_agent_status", {
            "conversation_id": conversation_id,
            "agentId": agent_id,
            "status": status,
        })

    def beam(
        self,
        *,
        conversation_id: str,
        from_id: str,
        to_id: str,
        kind: str = "message",
        label: str | None = None,
    ) -> AnimationEvent:
        return self.emit("anim_beam", {
            "conversation_id": conversation_id,
            "beam": {
                "id": f"beam_{uuid.uuid4().hex[:8]}",
                "fromId": from_id,
                "toId": to_id,
                "kind": kind,
                "label": label,
            },
        })

    def viz_event(
        self,
        *,
        conversation_id: str,
        kind: str,
        label: str,
    ) -> AnimationEvent:
        return self.emit("anim_event", {
            "conversation_id": conversation_id,
            "event": {
                "id": f"viz_{uuid.uuid4().hex[:8]}",
                "kind": kind,
                "label": label,
            },
        })


animation_bus = AnimationEventBus()
