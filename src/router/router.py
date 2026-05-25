import json
import os
import random
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Callable, Deque, Dict, List, Optional

from protocol.utils import normalize_to_list
from state import advance_seq, apply_message_to_tasks, recover_state, save_router_state, save_tasks
from storage import (
    StorageLayout,
    append_ack_event,
    append_inbox_event,
    append_message_event,
    init_or_load_session,
    iter_ack_events,
    iter_message_events,
)
from validation import ValidationError, validate_message

from .config import RouterConfig
from .presence import PresenceRegistry


def _now_ms() -> int:
    return int(time.time() * 1000)


def _delivery_key(message_id: str, agent: str) -> str:
    return f"{message_id}:{agent}"


def _infer_agent(from_field: Optional[str]) -> Optional[str]:
    if not from_field:
        return None
    return from_field.split("-")[0]


def _coerce_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


@dataclass
class DeliveryState:
    message_id: str
    agent: str
    status: str
    retry_count: int
    first_ts: int
    last_ts: int
    next_retry_at: Optional[int]
    expires_at: Optional[int]
    failure_reason: Optional[str] = None


class Router:
    def __init__(
        self,
        workspace_dir: str,
        config: Optional[RouterConfig] = None,
        validator: Optional[Callable[[Dict[str, Any]], Any]] = None,
        now_ms: Optional[Callable[[], int]] = None,
        on_failure: Optional[Callable[[Dict[str, Any]], None]] = None,
        layout: Optional[StorageLayout] = None,
    ) -> None:
        self.config = config or RouterConfig()
        self._now_ms = now_ms or _now_ms
        self._validator = validator
        self._on_failure = on_failure or self._default_failure_handler
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._retry_thread: Optional[threading.Thread] = None

        self.layout = layout or StorageLayout.for_workspace(workspace_dir)
        self.layout.ensure()
        session = init_or_load_session(self.layout, workspace_dir)
        self.session_id = session.get("session_id", "")

        recovery = recover_state(self.layout)
        self.router_state = recovery.router_state
        save_router_state(self.layout, self.router_state)

        self.messages: Dict[str, Dict[str, Any]] = {}
        self.inbox: Dict[str, Deque[str]] = {
            agent: deque(ids) for agent, ids in recovery.inbox_by_agent.items()
        }
        self.delivery: Dict[str, DeliveryState] = {}
        self.tasks: Dict[str, Dict[str, Any]] = recovery.tasks

        self.presence = PresenceRegistry(
            interval_ms=self.config.presence_interval_ms,
            timeout_multiplier=self.config.presence_timeout_multiplier,
        )

        self._load_history(recovery.inbox_by_agent)

    def start(self) -> None:
        if self._retry_thread and self._retry_thread.is_alive():
            return
        self._stop_event.clear()
        self._retry_thread = threading.Thread(target=self._retry_loop, daemon=True)
        self._retry_thread.start()

    def stop(self, timeout: Optional[float] = None) -> None:
        self._stop_event.set()
        if self._retry_thread:
            self._retry_thread.join(timeout=timeout)

    def receive_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(message, dict):
            raise ValueError("message must be a dict")
        msg_type = message.get("type")
        if msg_type in ("ack", "nack") or "ack_stage" in message:
            return self.receive_ack(message)

        incoming = dict(message)
        incoming.setdefault("v", "1")
        incoming.setdefault("session", self.session_id)
        incoming.setdefault("epoch", self.router_state.epoch)
        self._validate_message(incoming)

        with self._lock:
            prepared = self._prepare_message(incoming)
            self._record_message(prepared)
            acks = []
            now = self._now_ms()
            deliver_to = self._resolve_recipients(prepared["to"], now)
            if not deliver_to:
                deliver_to = prepared["to"]
            for agent in deliver_to:
                self._deliver_to_inbox(prepared, agent, now)
                ack = {
                    "id": prepared["id"],
                    "ack": "delivered",
                    "agent": agent,
                    "ts": now,
                }
                append_ack_event(self.layout, self.router_state.epoch, ack)
                acks.append(ack)
            self._update_task(prepared)
            return {
                "status": "delivered",
                "id": prepared["id"],
                "seq": prepared["seq"],
                "ts": prepared["ts"],
                "acks": acks,
            }

    def receive_ack(self, ack: Dict[str, Any]) -> Dict[str, Any]:
        ack_stage = ack.get("ack") or ack.get("ack_stage")
        corr_id = ack.get("corr") or ack.get("id")
        agent = ack.get("agent") or _infer_agent(ack.get("from"))
        ts = _coerce_int(ack.get("ts")) or self._now_ms()

        if not ack_stage and ack.get("type") == "nack":
            ack_stage = "nack"
        if not ack_stage or not corr_id or not agent:
            raise ValueError("ack must include ack_stage, corr/id, and agent")
        if ack_stage not in ("delivered", "accepted", "nack"):
            raise ValueError("ack_stage invalid")

        with self._lock:
            key = _delivery_key(corr_id, agent)
            state = self.delivery.get(key)
            if not state:
                state = DeliveryState(
                    message_id=corr_id,
                    agent=agent,
                    status="delivered",
                    retry_count=0,
                    first_ts=ts,
                    last_ts=ts,
                    next_retry_at=None,
                    expires_at=None,
                )
                self.delivery[key] = state

            if ack_stage == "accepted":
                state.status = "accepted"
                state.last_ts = ts
                state.next_retry_at = None
                self._remove_from_inbox(agent, corr_id)
                append_inbox_event(self.layout, agent, "accepted", corr_id, ts)
            elif ack_stage == "nack":
                state.status = "failed"
                state.last_ts = ts
                state.next_retry_at = None
                state.failure_reason = ack.get("reason") or "nack"
                self._on_failure(
                    {
                        "message_id": corr_id,
                        "agent": agent,
                        "reason": state.failure_reason,
                        "retry_count": state.retry_count,
                    }
                )
            else:
                state.status = "delivered"
                state.last_ts = ts

            append_ack_event(
                self.layout,
                self.router_state.epoch,
                {"id": corr_id, "ack": ack_stage, "agent": agent, "ts": ts},
            )
            return {"status": "ok", "id": corr_id, "ack": ack_stage, "agent": agent}

    def pop_inbox(self, agent: str, limit: int = 1) -> List[Dict[str, Any]]:
        with self._lock:
            queue = self.inbox.setdefault(agent, deque())
            results = []
            while queue and len(results) < limit:
                message_id = queue.popleft()
                message = self.messages.get(message_id)
                if message:
                    results.append(message)
            return results

    def status(self, include_tasks: bool = False, filter_task: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            pending = {agent: len(queue) for agent, queue in self.inbox.items()}
            deliveries = [asdict(state) for state in self.delivery.values()]
            result = {
                "session": self.session_id,
                "epoch": self.router_state.epoch,
                "last_seq": self.router_state.last_seq,
                "pending_inbox": pending,
                "deliveries": deliveries,
            }
            if include_tasks:
                if filter_task:
                    task = self.tasks.get(filter_task)
                    result["tasks"] = {filter_task: task} if task else {}
                else:
                    result["tasks"] = dict(self.tasks)
            return result

    def trace(self, task_id: Optional[str] = None, message_id: Optional[str] = None) -> Dict[str, Any]:
        if task_id and message_id:
            raise ValueError("trace supports either task_id or message_id")
        if message_id:
            message_event = None
            for event in iter_message_events(self.layout):
                if event.get("id") == message_id:
                    message_event = event
                    break
            acks = [ack for ack in iter_ack_events(self.layout) if ack.get("id") == message_id]
            return {"id": message_id, "message": message_event, "acks": acks}
        if task_id:
            messages = [
                msg for msg in iter_message_events(self.layout) if msg.get("task_id") == task_id
            ]
            message_ids = {msg.get("id") for msg in messages if msg.get("id")}
            acks = [ack for ack in iter_ack_events(self.layout) if ack.get("id") in message_ids]
            return {"task_id": task_id, "messages": messages, "acks": acks}
        raise ValueError("task_id or message_id required")

    def register_presence(self, agent: str, meta: Optional[dict] = None) -> Dict[str, Any]:
        if not agent or not isinstance(agent, str):
            raise ValueError("agent required")
        now = self._now_ms()
        entry = self.presence.register(agent, meta=meta, now=now)
        return self._presence_payload(entry, now)

    def heartbeat(self, agent: str) -> Dict[str, Any]:
        if not agent or not isinstance(agent, str):
            raise ValueError("agent required")
        now = self._now_ms()
        entry = self.presence.heartbeat(agent, now=now)
        return self._presence_payload(entry, now)

    def presence_status(self, agent: Optional[str] = None) -> Dict[str, Any]:
        now = self._now_ms()
        if agent:
            entry = self.presence.get(agent, now=now)
            return {
                "agent": agent,
                "status": entry.status if entry else "unknown",
                "last_seen": entry.last_seen if entry else None,
                "last_change": entry.last_change if entry else None,
                "timeout_ms": self.presence.timeout_ms,
                "now": now,
            }
        entries = {
            name: {
                "status": entry.status,
                "last_seen": entry.last_seen,
                "last_change": entry.last_change,
                "meta": entry.meta,
            }
            for name, entry in self.presence.snapshot(now=now).items()
        }
        return {"now": now, "timeout_ms": self.presence.timeout_ms, "agents": entries}

    def _presence_payload(self, entry: Any, now: int) -> Dict[str, Any]:
        return {
            "agent": entry.agent,
            "status": entry.status,
            "last_seen": entry.last_seen,
            "last_change": entry.last_change,
            "timeout_ms": self.presence.timeout_ms,
            "now": now,
            "meta": entry.meta,
        }

    def _default_failure_handler(self, info: Dict[str, Any]) -> None:
        log_path = os.path.join(self.layout.logs_dir(), "failures.log")
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(info, ensure_ascii=False))
            handle.write("\n")

    def _validate_message(self, message: Dict[str, Any]) -> None:
        if self._validator:
            try:
                result = self._validator(message)
            except ValidationError as exc:
                raise ValueError(str(exc)) from exc
            except ValueError as exc:
                raise ValueError(str(exc)) from exc
            if isinstance(result, list) and result:
                raise ValueError("; ".join(result))
            if isinstance(result, str) and result:
                raise ValueError(result)
            return

        errors = validate_message(message, allow_missing_generated=True)
        if errors:
            raise ValueError("; ".join(errors))

    def _prepare_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        now = self._now_ms()
        prepared = dict(message)
        prepared.setdefault("v", "1")
        prepared["session"] = self.session_id
        prepared["epoch"] = self.router_state.epoch
        self.router_state = advance_seq(self.router_state, now)
        save_router_state(self.layout, self.router_state)
        prepared["seq"] = self.router_state.last_seq
        prepared["id"] = f"{self.session_id}-{self.router_state.epoch}-{prepared['seq']}"
        prepared["ts"] = now
        prepared["to"] = normalize_to_list(prepared.get("to"))
        prepared.setdefault("ttl_ms", self.config.default_ttl_ms)
        return prepared

    def _resolve_recipients(self, targets: List[str], now: Optional[int] = None) -> List[str]:
        if not targets:
            return []
        now = now or self._now_ms()
        snapshot = self.presence.snapshot(now=now)
        resolved: List[str] = []
        for target in targets:
            if target in snapshot:
                resolved.append(target)
                continue
            matched = False
            for entry in snapshot.values():
                meta = entry.meta or {}
                if meta.get("role") == target:
                    resolved.append(entry.agent)
                    matched = True
            if not matched:
                resolved.append(target)
        return list(dict.fromkeys(resolved))

    def _record_message(self, message: Dict[str, Any]) -> None:
        self.messages[message["id"]] = message
        append_message_event(self.layout, self.router_state.epoch, message)

    def _deliver_to_inbox(self, message: Dict[str, Any], agent: str, now: int) -> None:
        append_inbox_event(self.layout, agent, "deliver", message["id"], now)
        self.inbox.setdefault(agent, deque()).append(message["id"])

        key = _delivery_key(message["id"], agent)
        state = self.delivery.get(key)
        if not state:
            expires_at = self._compute_expires_at(message)
            state = DeliveryState(
                message_id=message["id"],
                agent=agent,
                status="delivered",
                retry_count=0,
                first_ts=now,
                last_ts=now,
                next_retry_at=now + self.config.ack_timeout_ms,
                expires_at=expires_at,
            )
            self.delivery[key] = state
        else:
            state.last_ts = now
            state.status = "delivered"

    def _remove_from_inbox(self, agent: str, message_id: str) -> None:
        queue = self.inbox.get(agent)
        if not queue:
            return
        remaining = deque([item for item in queue if item != message_id])
        self.inbox[agent] = remaining

    def _compute_expires_at(self, message: Optional[Dict[str, Any]]) -> Optional[int]:
        if not message:
            return None
        now = _coerce_int(message.get("ts")) or self._now_ms()
        ttl_ms = _coerce_int(message.get("ttl_ms"))
        deadline = _coerce_int(message.get("deadline"))
        expiry = None
        if ttl_ms is not None:
            expiry = now + ttl_ms
        if deadline is not None:
            expiry = min(expiry, deadline) if expiry else deadline
        return expiry

    def _update_task(self, message: Dict[str, Any]) -> None:
        if not message.get("task_id"):
            return
        task_message = dict(message)
        if not task_message.get("action") and task_message.get("type") in ("done", "fail"):
            task_message["action"] = task_message.get("type")
        apply_message_to_tasks(self.tasks, task_message)
        save_tasks(self.layout, self.tasks)

    def _load_history(self, inbox_by_agent: Dict[str, List[str]]) -> None:
        for event in iter_message_events(self.layout):
            if event.get("event") == "message" and event.get("id"):
                message = dict(event)
                message.pop("event", None)
                self.messages[message["id"]] = message

        now = self._now_ms()
        for ack in iter_ack_events(self.layout):
            if ack.get("event") == "ack":
                ack = dict(ack)
                ack.pop("event", None)
            message_id = ack.get("id")
            agent = ack.get("agent")
            ack_stage = ack.get("ack") or ack.get("ack_stage")
            if not message_id or not agent or not ack_stage:
                continue
            ts = _coerce_int(ack.get("ts")) or now
            key = _delivery_key(message_id, agent)
            state = self.delivery.get(key)
            if not state:
                state = DeliveryState(
                    message_id=message_id,
                    agent=agent,
                    status=ack_stage,
                    retry_count=0,
                    first_ts=ts,
                    last_ts=ts,
                    next_retry_at=None,
                    expires_at=None,
                )
                self.delivery[key] = state
            else:
                state.status = ack_stage
                state.last_ts = ts

        for agent, ids in inbox_by_agent.items():
            queue = self.inbox.setdefault(agent, deque(ids))
            for message_id in queue:
                key = _delivery_key(message_id, agent)
                message = self.messages.get(message_id)
                expires_at = self._compute_expires_at(message)
                state = self.delivery.get(key)
                if not state:
                    self.delivery[key] = DeliveryState(
                        message_id=message_id,
                        agent=agent,
                        status="delivered",
                        retry_count=0,
                        first_ts=now,
                        last_ts=now,
                        next_retry_at=now + self.config.ack_timeout_ms,
                        expires_at=expires_at,
                    )
                else:
                    state.status = "delivered"
                    state.last_ts = now
                    state.next_retry_at = now + self.config.ack_timeout_ms
                    if state.expires_at is None:
                        state.expires_at = expires_at

    def _retry_loop(self) -> None:
        interval = self.config.retry_poll_interval_ms / 1000.0
        while not self._stop_event.is_set():
            now = self._now_ms()
            with self._lock:
                for state in list(self.delivery.values()):
                    if state.status in ("accepted", "failed"):
                        continue
                    if state.expires_at and now >= state.expires_at:
                        self._mark_failed(state, "deadline_exceeded")
                        continue
                    if state.next_retry_at and now < state.next_retry_at:
                        continue
                    if state.retry_count >= self.config.max_retries:
                        self._mark_failed(state, "max_retries")
                        continue
                    message = self.messages.get(state.message_id)
                    if not message:
                        continue
                    delay = max(self.config.ack_timeout_ms, self._retry_delay(state.retry_count))
                    state.retry_count += 1
                    state.last_ts = now
                    state.next_retry_at = now + delay
                    self._deliver_to_inbox(message, state.agent, now)
                self.presence.expire(now=now)
            time.sleep(interval)

    def _retry_delay(self, retry_count: int) -> int:
        backoff = self.config.retry_backoff_ms
        base_delay = backoff[min(retry_count, len(backoff) - 1)]
        jitter = base_delay * self.config.jitter_ratio
        return max(0, int(base_delay + random.uniform(-jitter, jitter)))

    def _mark_failed(self, state: DeliveryState, reason: str) -> None:
        state.status = "failed"
        state.failure_reason = reason
        state.next_retry_at = None
        self._on_failure(
            {
                "message_id": state.message_id,
                "agent": state.agent,
                "reason": reason,
                "retry_count": state.retry_count,
            }
        )
