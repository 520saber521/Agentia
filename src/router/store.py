import json
import os
import time
import uuid
from typing import Dict, Iterable, List, Optional


def _read_json(path: str) -> Optional[Dict]:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _atomic_write_json(path: str, data: Dict) -> None:
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)
    os.replace(tmp_path, path)


def _append_jsonl(path: str, data: Dict) -> None:
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False))
        handle.write("\n")


def _now_ms() -> int:
    return int(time.time() * 1000)


class LocalStore:
    def __init__(self, workspace_dir: str) -> None:
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.root_dir = os.path.join(self.workspace_dir, ".codex_team")
        self.meta_dir = os.path.join(self.root_dir, "meta")
        self.state_dir = os.path.join(self.root_dir, "state")
        self.inbox_dir = os.path.join(self.root_dir, "inbox")
        self.logs_dir = os.path.join(self.root_dir, "logs")
        self.blobs_dir = os.path.join(self.root_dir, "blobs")
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        for path in [
            self.root_dir,
            self.meta_dir,
            self.state_dir,
            self.inbox_dir,
            self.logs_dir,
            self.blobs_dir,
        ]:
            os.makedirs(path, exist_ok=True)

    def load_session(self) -> str:
        path = os.path.join(self.meta_dir, "session.json")
        data = _read_json(path)
        if data and data.get("session_id"):
            return data["session_id"]
        session_id = f"sess-{uuid.uuid4()}"
        payload = {
            "session_id": session_id,
            "created_at": _now_ms(),
            "workspace": self.workspace_dir,
        }
        _atomic_write_json(path, payload)
        return session_id

    def load_router_state(self) -> Dict:
        path = os.path.join(self.state_dir, "router.json")
        return _read_json(path) or {}

    def save_router_state(self, state: Dict) -> None:
        path = os.path.join(self.state_dir, "router.json")
        _atomic_write_json(path, state)

    def load_tasks(self) -> Dict:
        path = os.path.join(self.state_dir, "tasks.json")
        return _read_json(path) or {}

    def save_tasks(self, tasks: Dict) -> None:
        path = os.path.join(self.state_dir, "tasks.json")
        _atomic_write_json(path, tasks)

    def load_delivery(self) -> Dict:
        path = os.path.join(self.state_dir, "delivery.json")
        return _read_json(path) or {}

    def save_delivery(self, delivery: Dict) -> None:
        path = os.path.join(self.state_dir, "delivery.json")
        _atomic_write_json(path, delivery)

    def append_message(self, epoch: int, message: Dict) -> None:
        path = os.path.join(self.logs_dir, f"messages-{epoch}.jsonl")
        event = {"event": "message"}
        event.update(message)
        _append_jsonl(path, event)

    def append_ack(self, epoch: int, ack: Dict) -> None:
        path = os.path.join(self.logs_dir, f"acks-{epoch}.jsonl")
        event = {"event": "ack"}
        event.update(ack)
        _append_jsonl(path, event)

    def append_inbox_event(self, agent: str, event: Dict) -> None:
        path = os.path.join(self.inbox_dir, f"{agent}.jsonl")
        _append_jsonl(path, event)

    def list_inbox_agents(self) -> List[str]:
        if not os.path.isdir(self.inbox_dir):
            return []
        agents = []
        for name in os.listdir(self.inbox_dir):
            if not name.endswith(".jsonl"):
                continue
            agents.append(os.path.splitext(name)[0])
        return agents

    def read_inbox_events(self, agent: str) -> Iterable[Dict]:
        path = os.path.join(self.inbox_dir, f"{agent}.jsonl")
        if not os.path.exists(path):
            return []
        events = []
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                events.append(json.loads(line))
        return events

    def _list_logs(self, prefix: str) -> List[str]:
        if not os.path.isdir(self.logs_dir):
            return []
        files = []
        for name in os.listdir(self.logs_dir):
            if name.startswith(prefix) and name.endswith(".jsonl"):
                files.append(name)
        return sorted(files)

    def read_messages(self) -> Iterable[Dict]:
        for name in self._list_logs("messages-"):
            path = os.path.join(self.logs_dir, name)
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("event") == "message":
                        yield data

    def read_acks(self) -> Iterable[Dict]:
        for name in self._list_logs("acks-"):
            path = os.path.join(self.logs_dir, name)
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("event") == "ack":
                        yield data

    def scan_max_seq(self) -> int:
        max_seq = 0
        for event in self.read_messages():
            seq = event.get("seq")
            if isinstance(seq, int) and seq > max_seq:
                max_seq = seq
        return max_seq
