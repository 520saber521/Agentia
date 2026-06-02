"""Agent Adapter 抽象基类与 Chunk 类型。

设计来源：``docs/ARCHITECTURE.md`` §5.6 / §7.5。

设计要点：

- ``send()`` 返回 **AsyncIterator[Chunk]**，统一支持流式。
- ``Chunk`` 是若干 ``TypedDict`` 的联合，凡涉及向调用方暴露的产物
  （文本 token、工具调用、产物、用量、错误、结束）都收敛在这里。
- 取消由外部 ``asyncio.Task.cancel()`` 触发；具体 Adapter 实现里
  务必对 ``asyncio.CancelledError`` 透传或做现场清理后再抛出。
"""

from __future__ import annotations

import abc
from typing import Any, AsyncIterator, List, Literal, Optional, Required, TypedDict, Union


class ChunkText(TypedDict):
    """流式文本片段。多个片段按到达顺序拼接即得最终回复。"""

    type: Literal["text"]
    delta: str


class ChunkToolCall(TypedDict, total=False):
    """工具调用片段（Day2 暂未使用，留接口）。"""

    type: Literal["tool_call"]
    name: str
    args: dict[str, Any]
    call_id: str


class ChunkArtifact(TypedDict, total=False):
    """产物落盘后回写的片段（Day3+ 使用）。"""

    type: Literal["artifact"]
    artifact: dict[str, Any]


class ChunkUsage(TypedDict, total=False):
    """Token / 费用统计。"""

    type: Literal["usage"]
    input_tokens: int
    output_tokens: int


class ChunkError(TypedDict, total=False):
    """Adapter 内部可恢复错误。致命错误请直接 raise。"""

    type: Literal["error"]
    code: str
    message: str


class ChunkDone(TypedDict, total=False):
    """终止标志，Adapter 必须在最后一次 yield 它。"""

    type: Required[Literal["done"]]
    finish_reason: str


Chunk = Union[ChunkText, ChunkToolCall, ChunkArtifact, ChunkUsage, ChunkError, ChunkDone]


class AgentAdapter(abc.ABC):
    """统一 Agent 后端访问接口。

    每种外部 AI 平台（Claude Code / Codex / OpenCode / 自建）对应一个实现。
    """

    #: 子类用作注册键的短名；与 ``ADAPTER_REGISTRY`` 的 key 一致。
    name: str = "unknown"

    def __init__(self, config: Optional[dict[str, Any]] = None) -> None:
        self.config: dict[str, Any] = dict(config or {})

    @abc.abstractmethod
    def send(
        self,
        messages: List[dict[str, Any]],
        *,
        tools: Optional[List[dict[str, Any]]] = None,
        artifacts_context: Optional[dict[str, Any]] = None,
        stream: bool = True,
    ) -> AsyncIterator[Chunk]:
        """异步生成器：按到达顺序 yield 出 :class:`Chunk`。

        ``messages`` 采用 OpenAI 风格 ``[{"role": "user"|"assistant"|"system", "content": str}, ...]``。
        实现者必须在结束时 ``yield {"type": "done"}``。
        """

    @abc.abstractmethod
    def capabilities(self) -> List[str]:
        """能力声明，例如 ``["code", "web", "tool_use"]``。"""

    async def cancel(self, message_id: str) -> None:  # noqa: ARG002 — 子类可选实现
        """供子类按 ``message_id`` 主动中断外部请求。默认空实现：依赖外部 Task.cancel()。"""
        return None
