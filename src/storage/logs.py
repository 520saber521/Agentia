import re
from pathlib import Path
from typing import Iterator, List, Optional

from .jsonio import append_jsonl, iter_jsonl
from .layout import StorageLayout


_MESSAGE_RE = re.compile(r"^messages-(\d+)\.jsonl$")
_ACK_RE = re.compile(r"^acks-(\d+)\.jsonl$")


def append_message_event(layout: StorageLayout, epoch: int, event: dict) -> None:
    record = dict(event)
    record.setdefault("event", "message")
    append_jsonl(layout.messages_log_path(epoch), record)


def append_ack_event(layout: StorageLayout, epoch: int, event: dict) -> None:
    record = dict(event)
    record.setdefault("event", "ack")
    append_jsonl(layout.acks_log_path(epoch), record)


def list_message_logs(layout: StorageLayout) -> List[Path]:
    items = []
    for path in layout.logs_dir().glob("messages-*.jsonl"):
        match = _MESSAGE_RE.match(path.name)
        if match:
            items.append((int(match.group(1)), path))
    return [path for _, path in sorted(items, key=lambda item: item[0])]


def list_ack_logs(layout: StorageLayout) -> List[Path]:
    items = []
    for path in layout.logs_dir().glob("acks-*.jsonl"):
        match = _ACK_RE.match(path.name)
        if match:
            items.append((int(match.group(1)), path))
    return [path for _, path in sorted(items, key=lambda item: item[0])]


def iter_message_events(layout: StorageLayout, epoch: Optional[int] = None) -> Iterator[dict]:
    if epoch is not None:
        return iter_jsonl(layout.messages_log_path(epoch))
    def _iter() -> Iterator[dict]:
        for path in list_message_logs(layout):
            for record in iter_jsonl(path):
                yield record
    return _iter()


def iter_ack_events(layout: StorageLayout, epoch: Optional[int] = None) -> Iterator[dict]:
    if epoch is not None:
        return iter_jsonl(layout.acks_log_path(epoch))
    def _iter() -> Iterator[dict]:
        for path in list_ack_logs(layout):
            for record in iter_jsonl(path):
                yield record
    return _iter()
