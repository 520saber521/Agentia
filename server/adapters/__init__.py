"""Agent Adapter 注册中心。

新增一个 Agent 等于：

1. 在本目录新建 ``<name>.py``，继承 :class:`AgentAdapter` 实现 ``send()``。
2. 在 :data:`ADAPTER_REGISTRY` 注册到一个简短 key。
3. 写 ``server/tests/test_adapter_<name>.py``。

详见 ``docs/ARCHITECTURE.md`` §5.6 与 ``ai-collab/skills/new-adapter.md``（W2 沉淀）。
"""

from __future__ import annotations

from typing import Any, Type

from .base import (
    AgentAdapter,
    Chunk,
    ChunkArtifact,
    ChunkDone,
    ChunkError,
    ChunkText,
    ChunkToolCall,
    ChunkUsage,
)
from .claude_code import ClaudeCodeAdapter
from .codex import CodexAdapter, OpenCodeAdapter
from .mock import MockAdapter

ADAPTER_REGISTRY: dict[str, Type[AgentAdapter]] = {
    "mock": MockAdapter,
    "claude_code": ClaudeCodeAdapter,
    "codex": CodexAdapter,
    "opencode": OpenCodeAdapter,
}


def build_adapter(adapter_type: str, config: dict[str, Any] | None = None) -> AgentAdapter:
    """按 ``adapter_type`` 构造一个 Adapter 实例。未知类型直接抛 ``ValueError``。"""
    cls = ADAPTER_REGISTRY.get(adapter_type)
    if cls is None:
        known = ", ".join(sorted(ADAPTER_REGISTRY))
        raise ValueError(f"unknown adapter_type: {adapter_type!r}; known: [{known}]")
    return cls(config or {})


__all__ = [
    "ADAPTER_REGISTRY",
    "AgentAdapter",
    "Chunk",
    "ChunkArtifact",
    "ChunkDone",
    "ChunkError",
    "ChunkText",
    "ChunkToolCall",
    "ChunkUsage",
    "ClaudeCodeAdapter",
    "CodexAdapter",
    "OpenCodeAdapter",
    "MockAdapter",
    "build_adapter",
]
