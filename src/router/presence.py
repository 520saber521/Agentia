from dataclasses import dataclass
from typing import Dict, Optional


def _now_ms() -> int:
    import time

    return int(time.time() * 1000)


@dataclass
class PresenceEntry:
    agent: str
    status: str
    last_seen: int
    last_change: int
    meta: Optional[dict] = None


class PresenceRegistry:
    def __init__(self, interval_ms: int = 30000, timeout_multiplier: int = 2) -> None:
        self.interval_ms = interval_ms
        self.timeout_ms = interval_ms * timeout_multiplier
        self._entries: Dict[str, PresenceEntry] = {}

    def register(self, agent: str, meta: Optional[dict] = None, now: Optional[int] = None) -> PresenceEntry:
        now = now or _now_ms()
        entry = self._entries.get(agent)
        if entry is None:
            entry = PresenceEntry(
                agent=agent,
                status="online",
                last_seen=now,
                last_change=now,
                meta=meta,
            )
            self._entries[agent] = entry
        else:
            entry.last_seen = now
            if entry.status != "online":
                entry.status = "online"
                entry.last_change = now
            if meta is not None:
                entry.meta = meta
        return entry

    def heartbeat(self, agent: str, now: Optional[int] = None) -> PresenceEntry:
        now = now or _now_ms()
        entry = self._entries.get(agent)
        if entry is None:
            entry = PresenceEntry(
                agent=agent,
                status="online",
                last_seen=now,
                last_change=now,
                meta=None,
            )
            self._entries[agent] = entry
            return entry
        entry.last_seen = now
        if entry.status != "online":
            entry.status = "online"
            entry.last_change = now
        return entry

    def expire(self, now: Optional[int] = None) -> Dict[str, PresenceEntry]:
        now = now or _now_ms()
        expired: Dict[str, PresenceEntry] = {}
        for entry in self._entries.values():
            if entry.status == "online" and now - entry.last_seen > self.timeout_ms:
                entry.status = "offline"
                entry.last_change = now
                expired[entry.agent] = entry
        return expired

    def snapshot(self, now: Optional[int] = None) -> Dict[str, PresenceEntry]:
        self.expire(now=now)
        return dict(self._entries)

    def get(self, agent: str, now: Optional[int] = None) -> Optional[PresenceEntry]:
        self.expire(now=now)
        return self._entries.get(agent)
