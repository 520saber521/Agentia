from dataclasses import dataclass
from typing import Optional

from storage.jsonio import read_json, write_json_atomic
from storage.layout import StorageLayout


@dataclass(frozen=True)
class RouterState:
    epoch: int
    last_seq: int
    last_ts: Optional[int]


def load_router_state(layout: StorageLayout) -> RouterState:
    data = read_json(layout.router_state_path())
    if not data:
        return RouterState(epoch=0, last_seq=0, last_ts=None)
    return RouterState(
        epoch=int(data.get("epoch", 0)),
        last_seq=int(data.get("last_seq", 0)),
        last_ts=data.get("last_ts"),
    )


def save_router_state(layout: StorageLayout, state: RouterState) -> None:
    write_json_atomic(
        layout.router_state_path(),
        {"epoch": state.epoch, "last_seq": state.last_seq, "last_ts": state.last_ts},
    )


def increment_epoch(state: RouterState) -> RouterState:
    return RouterState(epoch=state.epoch + 1, last_seq=state.last_seq, last_ts=state.last_ts)


def advance_seq(state: RouterState, ts_ms: int) -> RouterState:
    return RouterState(epoch=state.epoch, last_seq=state.last_seq + 1, last_ts=ts_ms)
