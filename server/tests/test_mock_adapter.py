"""MockAdapter 单元测试。

校验三件事（对应 ``docs/ARCHITECTURE.md`` §10.5 的"Adapter 测试要点"）：

1. **流式 chunk 顺序**：text → usage → done，且至少有 1 个 text。
2. **回声内容**：最近一条 ``role=user`` 的 ``content`` 必须出现在最终回复里。
3. **取消行为**：外部 ``Task.cancel()`` 能中断生成，已收到的 chunk 都是合法 text。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from adapters import (
    ADAPTER_REGISTRY,
    AgentAdapter,
    MockAdapter,
    build_adapter,
)


async def _collect(adapter: AgentAdapter, **kwargs: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    async for chunk in adapter.send(**kwargs):
        out.append(dict(chunk))
    return out


async def test_chunk_order_text_then_usage_then_done() -> None:
    a = MockAdapter({"delay_ms": 0})
    chunks = await _collect(a, messages=[{"role": "user", "content": "hi"}])

    assert chunks[-1] == {"type": "done"}, chunks[-1]
    assert chunks[-2]["type"] == "usage"
    text_chunks = [c for c in chunks if c["type"] == "text"]
    assert len(text_chunks) >= 5, "MockAdapter 应至少切出若干 text token"
    types_before_usage = [c["type"] for c in chunks[:-2]]
    assert set(types_before_usage) == {"text"}, types_before_usage


async def test_reply_echoes_last_user_message() -> None:
    a = MockAdapter({"delay_ms": 0})
    user_text = "用 React 写一个登录页"
    chunks = await _collect(
        a,
        messages=[
            {"role": "system", "content": "you are a helpful assistant"},
            {"role": "user", "content": "earlier message"},
            {"role": "assistant", "content": "earlier reply"},
            {"role": "user", "content": user_text},
        ],
    )
    text = "".join(c["delta"] for c in chunks if c["type"] == "text")
    assert user_text in text, f"echo 缺失: {text!r}"


async def test_usage_counts_are_nonnegative() -> None:
    a = MockAdapter({"delay_ms": 0})
    chunks = await _collect(a, messages=[{"role": "user", "content": "abc def"}])
    usage = next(c for c in chunks if c["type"] == "usage")
    assert usage["input_tokens"] >= 1
    assert usage["output_tokens"] >= 1


async def test_capabilities_contains_text() -> None:
    a = MockAdapter()
    caps = a.capabilities()
    assert "text" in caps
    assert "mock" in caps


async def test_cancellation_is_clean() -> None:
    a = MockAdapter({"delay_ms": 50})  # 故意慢一点，给取消留窗口
    collected: list[dict[str, Any]] = []

    async def run() -> None:
        async for chunk in a.send(messages=[{"role": "user", "content": "long reply please"}]):
            collected.append(dict(chunk))

    task = asyncio.create_task(run())
    await asyncio.sleep(0.12)  # 收到几条后再取消
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(collected) >= 1, "取消前应已收到若干 chunk"
    assert all(c["type"] == "text" for c in collected), collected
    assert not any(c.get("type") == "done" for c in collected), "取消时不应已经 yield done"


async def test_build_adapter_returns_mock_instance() -> None:
    a = build_adapter("mock", {"delay_ms": 1})
    assert isinstance(a, MockAdapter)
    assert a.delay_ms == 1


async def test_build_adapter_unknown_type_raises() -> None:
    with pytest.raises(ValueError) as ei:
        build_adapter("does_not_exist")
    assert "does_not_exist" in str(ei.value)


def test_registry_keys_match_class_name() -> None:
    """注册键与类的 ``name`` 字段保持一致，避免日志/配置错配。"""
    for key, cls in ADAPTER_REGISTRY.items():
        assert cls.name == key, f"registry key={key!r} ≠ class.name={cls.name!r}"
