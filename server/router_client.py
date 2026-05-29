"""Async HTTP client for the AgentHub Router (port 8765 by default).

W3 F-W3-1: BFF connects to Router for group chat fan-out and trace.

The Router is the machine-to-machine message bus (from ``src/router/router.py``).
It handles ACK-based delivery, retries, and message tracing.
BFF uses it when:
- A group chat message has @mentions that should be routed to external agents
- Orchestrator needs to fan-out subtasks to multiple agents
- User wants to view a trace for a message

Single-chat (1v1) still goes directly BFF → Adapter → BFF (per P-2).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger("agenthub.router_client")

DEFAULT_ROUTER_BASE = "http://127.0.0.1:8765"


class RouterClient:
    """Async HTTP client for the Router REST API.

    Thread-safe: each call creates its own httpx client.
    """

    def __init__(self, base_url: str = DEFAULT_ROUTER_BASE) -> None:
        self.base_url = base_url.rstrip("/")

    async def health(self) -> bool:
        """Check if Router is reachable."""
        try:
            async with httpx.AsyncClient(timeout=1) as client:
                resp = await client.get(f"{self.base_url}/health")
                return resp.status_code == 200
        except httpx.TransportError:
            return False

    async def send_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """POST /messages — send a message through the Router."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.base_url}/messages",
                json=message,
            )
            resp.raise_for_status()
            return resp.json()

    async def send_ack(self, ack: dict[str, Any]) -> dict[str, Any]:
        """POST /acks — acknowledge a message delivery."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.base_url}/acks",
                json=ack,
            )
            resp.raise_for_status()
            return resp.json()

    async def status(self, include_tasks: bool = False, filter_task: Optional[str] = None) -> dict[str, Any]:
        """GET /status — Router status overview."""
        params: dict[str, str] = {}
        if include_tasks:
            params["tasks"] = "1"
        if filter_task:
            params["filter_task"] = filter_task
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self.base_url}/status", params=params)
            resp.raise_for_status()
            return resp.json()

    async def trace(self, task_id: Optional[str] = None, message_id: Optional[str] = None) -> dict[str, Any]:
        """GET /trace — retrieve delivery trace for a task or message."""
        params: dict[str, str] = {}
        if task_id:
            params["task"] = task_id
        if message_id:
            params["id"] = message_id
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self.base_url}/trace", params=params)
            resp.raise_for_status()
            return resp.json()

    async def inbox(self, agent: str, limit: int = 1) -> dict[str, Any]:
        """GET /inbox — fetch pending messages for an agent."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.base_url}/inbox",
                params={"agent": agent, "limit": str(limit)},
            )
            resp.raise_for_status()
            return resp.json()

    async def register_node(self, node_id: str, role: str = "bff", capabilities: Optional[list[str]] = None) -> bool:
        """POST /nodes/register — register this BFF node with the Router.

        Returns ``True`` if registration succeeded, ``False`` if Router is unavailable.
        """
        payload: dict[str, Any] = {
            "node_id": node_id,
            "role": role,
            "capabilities": capabilities or ["chat", "stream"],
        }
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.post(
                    f"{self.base_url}/nodes/register",
                    json=payload,
                )
                return resp.status_code == 200
        except httpx.TransportError:
            logger.warning("Router not available at %s — skipping node registration", self.base_url)
            return False

    async def register_presence(self, agent: str, meta: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """POST /presence/register — register an agent's presence."""
        payload: dict[str, Any] = {"agent": agent}
        if meta:
            payload["meta"] = meta
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.base_url}/presence/register",
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    async def heartbeat(self, agent: str) -> dict[str, Any]:
        """POST /presence/heartbeat — send heartbeat for an agent."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.base_url}/presence/heartbeat",
                json={"agent": agent},
            )
            resp.raise_for_status()
            return resp.json()


_router_client: Optional[RouterClient] = None


def get_router_client(base_url: str = DEFAULT_ROUTER_BASE) -> RouterClient:
    global _router_client
    if _router_client is None:
        _router_client = RouterClient(base_url)
    return _router_client
