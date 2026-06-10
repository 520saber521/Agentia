"""DAG Engine — event-driven DAG execution for multi-agent orchestration.

Replaces the barrier-based fan-out loop with a true event-driven DAG executor.
Each task is a DAGNode; the executor dispatches nodes as soon as their
dependencies are satisfied, without waiting for sibling nodes (no barrier).

Key classes:
    - DAGNode: a single task node with dependency tracking
    - DAG: a directed acyclic graph of DAGNodes
    - DAGExecutor: event-driven executor that runs the DAG
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

logger = logging.getLogger("agenthub.dag")


@dataclass
class DAGNode:
    """A single node in the DAG execution graph.

    Each node represents a subtask that an Agent will execute.
    Dependencies refer to other node IDs that must complete first.
    """
    id: str
    domain: str
    description: str = ""
    title: str = ""
    dependencies: list[str] = field(default_factory=list)
    dependents: list[str] = field(default_factory=list)
    status: str = "pending"
    assigned_agent_id: str = ""
    assigned_agent_name: str = ""
    input_summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_pending(self) -> bool:
        return self.status == "pending"

    @property
    def is_terminal(self) -> bool:
        return self.status in ("completed", "failed", "cancelled")


class DAG:
    """A Directed Acyclic Graph of DAGNodes.

    Usage:
        dag = DAG()
        dag.add_node(DAGNode(id="node_a", domain="database", dependencies=[]))
        dag.add_node(DAGNode(id="node_b", domain="backend", dependencies=["node_a"]))
        dag.finalize()  # compute dependents
    """

    def __init__(self):
        self.nodes: dict[str, DAGNode] = {}

    def add_node(self, node: DAGNode) -> DAGNode:
        self.nodes[node.id] = node
        return node

    def finalize(self):
        """Compute reverse dependency edges (dependents)."""
        for node in self.nodes.values():
            node.dependents = []
        for node in self.nodes.values():
            for dep_id in node.dependencies:
                if dep_id in self.nodes:
                    self.nodes[dep_id].dependents.append(node.id)

    def get_ready(self, completed: set[str], failed: set[str]) -> list[DAGNode]:
        """Return all pending nodes whose dependencies are fully satisfied."""
        ready = []
        for node in self.nodes.values():
            if not node.is_pending:
                continue
            if all(d in completed for d in node.dependencies):
                ready.append(node)
        return ready

    @property
    def is_complete(self) -> bool:
        return all(n.is_terminal for n in self.nodes.values())

    @property
    def completed_ids(self) -> set[str]:
        return {n.id for n in self.nodes.values() if n.status == "completed"}

    @property
    def failed_ids(self) -> set[str]:
        return {n.id for n in self.nodes.values() if n.status == "failed"}


class DAGExecutor:
    """Event-driven DAG executor.

    Instead of dispatching all ready nodes and waiting for ALL to finish
    (barrier), this dispatches nodes as soon as their dependencies are met
    and uses ``asyncio.wait(FIRST_COMPLETED)`` to react the moment any node
    finishes — immediately checking for newly unblocked nodes.
    """

    def __init__(
        self,
        dag: DAG,
        dispatch_fn: Callable[[DAGNode], Awaitable[Any]],
        *,
        max_concurrency: int = 10,
    ):
        self.dag = dag
        self.dispatch_fn = dispatch_fn
        self.max_concurrency = max_concurrency
        self._sem = asyncio.Semaphore(max_concurrency)
        self._in_flight: dict[str, asyncio.Task] = {}

    async def execute(self) -> dict[str, Any]:
        """Execute the DAG to completion.

        Returns:
            dict with keys:
                - completed: set[str] — node IDs that succeeded
                - failed: set[str] — node IDs that failed
                - subtask_messages: dict[str, str] — node_id -> message_id
        """
        self.dag.finalize()

        completed: set[str] = set()
        failed: set[str] = set()
        subtask_messages: dict[str, str] = {}

        while not self.dag.is_complete:
            ready = self.dag.get_ready(completed, failed)
            for node in ready:
                if node.id in self._in_flight:
                    continue
                node.status = "running"
                task = asyncio.create_task(
                    self._run_node(node),
                    name=f"dag-{node.id}",
                )
                self._in_flight[node.id] = task

            if not self._in_flight:
                pending = [n.id for n in self.dag.nodes.values() if n.is_pending]
                logger.warning(
                    "DAG deadlock — %d pending nodes with unmet dependencies: %s",
                    len(pending), pending,
                )
                for node in self.dag.nodes.values():
                    if node.is_pending:
                        node.status = "failed"
                        failed.add(node.id)
                break

            done, _ = await asyncio.wait(
                self._in_flight.values(),
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in done:
                node_id = self._resolve_node_id(task)
                if node_id is None:
                    continue
                del self._in_flight[node_id]
                node = self.dag.nodes[node_id]
                try:
                    msg_id = task.result()
                    node.status = "completed"
                    completed.add(node_id)
                    subtask_messages[node_id] = msg_id
                except asyncio.CancelledError:
                    node.status = "cancelled"
                    failed.add(node_id)
                except Exception as exc:
                    logger.error("DAG node %s failed: %s", node_id, exc)
                    node.status = "failed"
                    failed.add(node_id)

        return {
            "completed": completed,
            "failed": failed,
            "subtask_messages": subtask_messages,
        }

    async def _run_node(self, node: DAGNode) -> Any:
        async with self._sem:
            return await self.dispatch_fn(node)

    def _resolve_node_id(self, task: asyncio.Task) -> str | None:
        for nid, t in self._in_flight.items():
            if t == task:
                return nid
        return None

    def cancel_all(self):
        """Cancel all in-flight tasks immediately."""
        for task in self._in_flight.values():
            task.cancel()
        self._in_flight.clear()
