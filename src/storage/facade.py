import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Union

from .blobs import write_blob
from .inbox import append_inbox_event, load_pending_ids
from .layout import StorageLayout
from .logs import append_ack_event, append_message_event
from .session import init_or_load_session


def _now_ms() -> int:
    return int(time.time() * 1000)


def _validate_epoch(epoch: int) -> None:
    if not isinstance(epoch, int) or epoch < 1:
        raise ValueError(f"epoch must be a positive int, got {epoch!r}")


def _validate_message_id(message_id: str) -> None:
    if not message_id or not isinstance(message_id, str):
        raise ValueError("message_id must be a non-empty string")


@dataclass(frozen=True)
class StorageFacade:
    """
    High-level storage facade for Router.

    Raises:
        FileNotFoundError: storage root missing and create_if_missing is False.
    """

    layout: StorageLayout
    session: Dict

    @staticmethod
    def open(
        workspace: Union[str, Path],
        roles: Optional[List[str]] = None,
        create_if_missing: bool = True,
    ) -> "StorageFacade":
        layout = StorageLayout.for_workspace(workspace)
        if not layout.root.exists() and not create_if_missing:
            raise FileNotFoundError(f"storage root missing: {layout.root}")
        layout.ensure()
        session = init_or_load_session(layout, workspace, roles)
        return StorageFacade(layout=layout, session=session)

    def append_message(
        self, epoch: int, message: Dict, body_payload: Optional[Dict] = None
    ) -> Dict:
        """
        Append a message event to messages-<epoch>.jsonl.

        Raises:
            ValueError: invalid epoch or message missing id.
            OSError: write failure.
        """
        _validate_epoch(epoch)
        message_id = message.get("id")
        _validate_message_id(message_id)
        record = dict(message)
        if body_payload is not None:
            record["body_ref"] = write_blob(self.layout, message_id, body_payload)
        append_message_event(self.layout, epoch, record)
        return record

    def append_ack(
        self,
        epoch: int,
        message_id: str,
        ack: str,
        agent: str,
        ts: Optional[int] = None,
    ) -> Dict:
        """
        Append an ack event to acks-<epoch>.jsonl.

        Raises:
            ValueError: invalid epoch/ack/message_id/agent.
            OSError: write failure.
        """
        _validate_epoch(epoch)
        _validate_message_id(message_id)
        if not agent or not isinstance(agent, str):
            raise ValueError("agent must be a non-empty string")
        if ack not in ("delivered", "accepted"):
            raise ValueError(f"ack must be delivered|accepted, got {ack!r}")
        event = {"id": message_id, "ack": ack, "agent": agent, "ts": ts or _now_ms()}
        append_ack_event(self.layout, epoch, event)
        return event

    def record_inbox_delivery(self, agent: str, message_id: str, ts: Optional[int] = None) -> Dict:
        """
        Append a deliver event to inbox/<agent>.jsonl.

        Raises:
            ValueError: invalid agent/message_id.
            OSError: write failure.
        """
        _validate_message_id(message_id)
        if not agent or not isinstance(agent, str):
            raise ValueError("agent must be a non-empty string")
        event_ts = ts or _now_ms()
        append_inbox_event(self.layout, agent, "deliver", message_id, event_ts)
        return {"event": "deliver", "id": message_id, "ts": event_ts}

    def record_inbox_accepted(self, agent: str, message_id: str, ts: Optional[int] = None) -> Dict:
        """
        Append an accepted event to inbox/<agent>.jsonl.

        Raises:
            ValueError: invalid agent/message_id.
            OSError: write failure.
        """
        _validate_message_id(message_id)
        if not agent or not isinstance(agent, str):
            raise ValueError("agent must be a non-empty string")
        event_ts = ts or _now_ms()
        append_inbox_event(self.layout, agent, "accepted", message_id, event_ts)
        return {"event": "accepted", "id": message_id, "ts": event_ts}

    def load_pending_inbox(self, agent: str) -> list:
        """
        Return pending message ids for an agent.

        Raises:
            ValueError: invalid agent.
        """
        if not agent or not isinstance(agent, str):
            raise ValueError("agent must be a non-empty string")
        return load_pending_ids(self.layout, agent)
