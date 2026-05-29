from typing import Iterator, List

from .jsonio import append_jsonl, iter_jsonl
from .layout import StorageLayout


def append_inbox_event(
    layout: StorageLayout, agent: str, event_type: str, message_id: str, ts: int
) -> None:
    record = {"event": event_type, "id": message_id, "ts": ts}
    append_jsonl(layout.inbox_path(agent), record)


def iter_inbox_events(layout: StorageLayout, agent: str) -> Iterator[dict]:
    return iter_jsonl(layout.inbox_path(agent))


def load_pending_ids(layout: StorageLayout, agent: str) -> List[str]:
    return pending_ids_from_events(iter_inbox_events(layout, agent))


def pending_ids_from_events(events: Iterator[dict]) -> List[str]:
    pending: List[str] = []
    pending_set = set()
    for event in events:
        event_type = event.get("event")
        message_id = event.get("id")
        if not message_id:
            continue
        if event_type == "deliver":
            if message_id not in pending_set:
                pending.append(message_id)
                pending_set.add(message_id)
        elif event_type == "accepted":
            if message_id in pending_set:
                pending_set.remove(message_id)
                pending = [mid for mid in pending if mid != message_id]
    return pending
