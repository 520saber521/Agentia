from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from storage.inbox import iter_inbox_events, pending_ids_from_events
from storage.layout import StorageLayout
from storage.logs import iter_ack_events, iter_message_events
from state.router_state import RouterState, increment_epoch, load_router_state
from state.tasks import apply_message_to_tasks, load_tasks


@dataclass
class RecoveryResult:
    router_state: RouterState
    inbox_by_agent: Dict[str, List[str]]
    tasks: Dict[str, dict]
    delivery: Dict[str, dict]
    max_epoch: int
    max_seq: int


def recover_state(layout: StorageLayout, agents: Optional[List[str]] = None) -> RecoveryResult:
    layout.ensure()
    agents = agents or discover_agents(layout)

    router_state, max_epoch, max_seq = recover_router_state(layout)
    tasks = recover_tasks(layout)
    delivery = build_delivery_state(layout)
    inbox_by_agent = recover_inbox(layout, agents)
    return RecoveryResult(
        router_state=router_state,
        inbox_by_agent=inbox_by_agent,
        tasks=tasks,
        delivery=delivery,
        max_epoch=max_epoch,
        max_seq=max_seq,
    )


def discover_agents(layout: StorageLayout) -> List[str]:
    agents = set()
    for path in layout.inbox_dir().glob("*.jsonl"):
        agents.add(path.stem)
    for event in iter_message_events(layout):
        for agent in _normalize_agents(event.get("to")):
            agents.add(agent)
    return sorted(agents)


def recover_router_state(layout: StorageLayout) -> Tuple[RouterState, int, int]:
    state_path = layout.router_state_path()
    if state_path.exists():
        state = load_router_state(layout)
        state = increment_epoch(state)
        return state, state.epoch - 1, state.last_seq

    max_epoch, max_seq = scan_logs_for_max(layout)
    next_epoch = max_epoch + 1 if max_epoch > 0 else 1
    return RouterState(epoch=next_epoch, last_seq=max_seq, last_ts=None), max_epoch, max_seq


def scan_logs_for_max(layout: StorageLayout) -> Tuple[int, int]:
    max_epoch = 0
    max_seq = 0
    for event in iter_message_events(layout):
        epoch = _safe_int(event.get("epoch"))
        seq = _safe_int(event.get("seq"))
        if epoch > max_epoch:
            max_epoch = epoch
        if seq > max_seq:
            max_seq = seq
    return max_epoch, max_seq


def recover_inbox(layout: StorageLayout, agents: List[str]) -> Dict[str, List[str]]:
    inbox_by_agent: Dict[str, List[str]] = {}
    missing = [agent for agent in agents if not layout.inbox_path(agent).exists()]
    fallback = rebuild_inbox_from_logs(layout, agents) if missing else {}

    for agent in agents:
        inbox_path = layout.inbox_path(agent)
        if inbox_path.exists():
            inbox_by_agent[agent] = pending_ids_from_events(iter_inbox_events(layout, agent))
        else:
            inbox_by_agent[agent] = fallback.get(agent, [])
    return inbox_by_agent


def rebuild_inbox_from_logs(layout: StorageLayout, agents: List[str]) -> Dict[str, List[str]]:
    delivered = set()
    accepted = set()
    message_order = {}

    for msg in iter_message_events(layout):
        msg_id = msg.get("id")
        if not msg_id:
            continue
        message_order[msg_id] = _safe_int(msg.get("seq"))

    for ack in iter_ack_events(layout):
        msg_id = ack.get("id")
        agent = ack.get("agent")
        if not msg_id or not agent:
            continue
        ack_type = ack.get("ack")
        if ack_type == "delivered":
            delivered.add((agent, msg_id))
        elif ack_type == "accepted":
            accepted.add((agent, msg_id))

    if not delivered:
        for msg in iter_message_events(layout):
            msg_id = msg.get("id")
            for agent in _normalize_agents(msg.get("to")):
                delivered.add((agent, msg_id))

    pending = delivered - accepted
    inbox_by_agent: Dict[str, List[str]] = {agent: [] for agent in agents}
    for agent, msg_id in pending:
        inbox_by_agent.setdefault(agent, []).append(msg_id)

    for agent, pending_ids in inbox_by_agent.items():
        pending_ids.sort(key=lambda mid: message_order.get(mid, 0))
    return inbox_by_agent


def recover_tasks(layout: StorageLayout) -> Dict[str, dict]:
    if layout.tasks_path().exists():
        return load_tasks(layout)

    tasks: Dict[str, dict] = {}
    events = list(iter_message_events(layout))
    events.sort(key=lambda event: (_safe_int(event.get("epoch")), _safe_int(event.get("seq"))))
    for event in events:
        apply_message_to_tasks(tasks, event)
    return tasks


def build_delivery_state(layout: StorageLayout) -> Dict[str, dict]:
    delivery: Dict[str, dict] = {}
    for ack in iter_ack_events(layout):
        msg_id = ack.get("id")
        if not msg_id:
            continue
        entry = delivery.setdefault(msg_id, {"status": None, "retry_count": 0, "last_ts": None})
        entry["status"] = ack.get("ack") or entry["status"]
        if "ts" in ack:
            entry["last_ts"] = ack.get("ts")
    return delivery


def _normalize_agents(value: object) -> List[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    if isinstance(value, str):
        return [value]
    return []


def _safe_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
