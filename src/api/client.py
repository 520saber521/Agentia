import json
import os
import sys
from typing import Any, Dict, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _ensure_src_on_path() -> None:
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if base not in sys.path:
        sys.path.insert(0, base)


class RouterClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8765") -> None:
        self.base_url = base_url.rstrip("/")

    def send_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        return self._post("/messages", message)

    def send_ack(self, ack: Dict[str, Any]) -> Dict[str, Any]:
        return self._post("/acks", ack)

    def status(self, include_tasks: bool = False, filter_task: Optional[str] = None) -> Dict[str, Any]:
        params = {}
        if include_tasks:
            params["tasks"] = "1"
        if filter_task:
            params["filter_task"] = filter_task
        return self._get("/status", params)

    def trace(self, task_id: Optional[str] = None, message_id: Optional[str] = None) -> Dict[str, Any]:
        params = {}
        if task_id:
            params["task"] = task_id
        if message_id:
            params["id"] = message_id
        return self._get("/trace", params)

    def inbox(self, agent: str, limit: int = 1) -> Dict[str, Any]:
        return self._get("/inbox", {"agent": agent, "limit": str(limit)})

    def register_presence(self, agent: str, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"agent": agent}
        if meta is not None:
            payload["meta"] = meta
        return self._post("/presence/register", payload)

    def heartbeat(self, agent: str) -> Dict[str, Any]:
        return self._post("/presence/heartbeat", {"agent": agent})

    def presence(self, agent: Optional[str] = None) -> Dict[str, Any]:
        params = {}
        if agent:
            params["agent"] = agent
        return self._get("/presence", params)

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    def _get(self, path: str, params: Dict[str, str]) -> Dict[str, Any]:
        query = f"?{urlencode(params)}" if params else ""
        request = Request(f"{self.base_url}{path}{query}", method="GET")
        with urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))


_ensure_src_on_path()
