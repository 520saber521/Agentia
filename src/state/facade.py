from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Union

from storage.layout import StorageLayout
from storage.session import init_or_load_session
from state.recovery import RecoveryResult, recover_state
from state.router_state import RouterState, load_router_state, save_router_state
from state.tasks import TaskStore


@dataclass(frozen=True)
class RecoveryBundle:
    session: Dict
    router_state: RouterState
    inbox_by_agent: Dict[str, List[str]]
    tasks: Dict[str, dict]
    delivery: Dict[str, dict]
    max_epoch: int
    max_seq: int


def recover_workspace(
    workspace: Union[str, Path],
    agents: Optional[List[str]] = None,
    roles: Optional[List[str]] = None,
    create_if_missing: bool = True,
) -> RecoveryBundle:
    """
    Load session + router_state + inbox/tasks/delivery in one call.

    Raises:
        FileNotFoundError: storage root missing and create_if_missing is False.
    """
    layout = StorageLayout.for_workspace(workspace)
    if not layout.root.exists() and not create_if_missing:
        raise FileNotFoundError(f"storage root missing: {layout.root}")
    layout.ensure()
    session = init_or_load_session(layout, workspace, roles)
    result: RecoveryResult = recover_state(layout, agents=agents)
    return RecoveryBundle(
        session=session,
        router_state=result.router_state,
        inbox_by_agent=result.inbox_by_agent,
        tasks=result.tasks,
        delivery=result.delivery,
        max_epoch=result.max_epoch,
        max_seq=result.max_seq,
    )


def load_state_store(layout: StorageLayout) -> TaskStore:
    return TaskStore.load(layout)


def read_router_state(layout: StorageLayout) -> RouterState:
    return load_router_state(layout)


def write_router_state(layout: StorageLayout, state: RouterState) -> None:
    save_router_state(layout, state)
