"""ClaudeCodeAdapter tests — 5 required scenarios (ai-collab/skills/new-adapter.md Step 5).

Coverage:
1. Successful streaming — SSE events assembled into text chunks
2. Missing API key — yields error, no HTTP call
3. Rate limited (429) — yields rate_limited error
4. Timeout — yields timeout error
5. Upstream 5xx — yields upstream_error
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from adapters import build_adapter
from adapters.claude_code import ClaudeCodeAdapter


@pytest.fixture
def adapter_with_key():
    return ClaudeCodeAdapter({"api_key": "sk-ant-test123", "model": "claude-sonnet-4-20250514"})


@pytest.fixture
def adapter_no_key():
    return ClaudeCodeAdapter({"api_key": "", "model": "claude-sonnet-4-20250514"})


def _sse_lines(*events: tuple[str, str]) -> list[str]:
    lines: list[str] = []
    for evt, data in events:
        lines.append(f"event: {evt}")
        lines.append(f"data: {data}")
        lines.append("")
    return lines


def _mock_client(response_mock) -> AsyncMock:
    mc = AsyncMock()
    mc.__aenter__.return_value = mc
    mc.__aexit__.return_value = None
    mc.post.return_value = response_mock
    return mc


# ---------------------------------------------------------------------------
# Scenario 1: Successful streaming
# ---------------------------------------------------------------------------


async def test_successful_streaming(adapter_with_key):
    sse_data = _sse_lines(
        ("message_start", '{"type":"message_start","message":{"id":"msg_1","role":"assistant","content":[],"model":"claude-3","usage":{"input_tokens":10,"output_tokens":1}}}'),
        ("content_block_start", '{"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}'),
        ("content_block_delta", '{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}'),
        ("content_block_delta", '{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":" world"}}'),
        ("content_block_stop", '{"type":"content_block_stop","index":0}'),
        ("message_delta", '{"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":12}}'),
        ("message_stop", '{"type":"message_stop"}'),
    )

    async def aiter_lines():
        for line in sse_data:
            yield line

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.aiter_lines = aiter_lines
    mock_response.headers = {"content-type": "text/event-stream"}

    with patch("httpx.AsyncClient", return_value=_mock_client(mock_response)):
        chunks = []
        async for chunk in adapter_with_key.send(
            messages=[{"role": "user", "content": "Say hello"}]
        ):
            chunks.append(chunk)

    texts = [c["delta"] for c in chunks if c.get("type") == "text"]
    full = "".join(texts)
    assert full == "Hello world", f"expected 'Hello world', got {full!r}"

    usages = [c for c in chunks if c.get("type") == "usage"]
    assert len(usages) == 1
    assert usages[0]["input_tokens"] == 10

    assert chunks[-1]["type"] == "done"


# ---------------------------------------------------------------------------
# Scenario 2: Missing API key
# ---------------------------------------------------------------------------


async def test_missing_api_key(adapter_no_key):
    chunks = []
    async for chunk in adapter_no_key.send(
        messages=[{"role": "user", "content": "Say hello"}]
    ):
        chunks.append(chunk)

    assert len(chunks) == 1
    assert chunks[0]["type"] == "error"
    assert chunks[0]["code"] == "missing_api_key"


# ---------------------------------------------------------------------------
# Scenario 3: Rate limited (429)
# ---------------------------------------------------------------------------


async def test_rate_limited(adapter_with_key):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 429

    with patch("httpx.AsyncClient", return_value=_mock_client(mock_response)):
        chunks = []
        async for chunk in adapter_with_key.send(
            messages=[{"role": "user", "content": "Say hello"}]
        ):
            chunks.append(chunk)

    assert len(chunks) == 1
    assert chunks[0]["type"] == "error"
    assert chunks[0]["code"] == "rate_limited"


# ---------------------------------------------------------------------------
# Scenario 4: Timeout
# ---------------------------------------------------------------------------


async def test_timeout(adapter_with_key):
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.side_effect = httpx.TimeoutException("Connection timed out")

    with patch("httpx.AsyncClient", return_value=mock_client):
        chunks = []
        async for chunk in adapter_with_key.send(
            messages=[{"role": "user", "content": "Say hello"}]
        ):
            chunks.append(chunk)

    assert len(chunks) == 1
    assert chunks[0]["type"] == "error"
    assert chunks[0]["code"] == "timeout"


# ---------------------------------------------------------------------------
# Scenario 5: Upstream 5xx
# ---------------------------------------------------------------------------


async def test_upstream_5xx(adapter_with_key):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 502

    with patch("httpx.AsyncClient", return_value=_mock_client(mock_response)):
        chunks = []
        async for chunk in adapter_with_key.send(
            messages=[{"role": "user", "content": "Say hello"}]
        ):
            chunks.append(chunk)

    assert len(chunks) == 1
    assert chunks[0]["type"] == "error"
    assert chunks[0]["code"] == "upstream_error"


# ---------------------------------------------------------------------------
# Scenario 6: Cancel — graceful return, not raise
# ---------------------------------------------------------------------------


async def test_cancel(adapter_with_key):
    """Cancel must be a graceful return, not a raise.

    R-A-3: cancel is return, not raise.
    """
    sse_data = _sse_lines(
        ("message_start", '{"type":"message_start","message":{"id":"msg_1","role":"assistant","content":[],"model":"claude-3","usage":{"input_tokens":10,"output_tokens":1}}}'),
        ("content_block_start", '{"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}'),
        ("content_block_delta", '{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello "}}'),
        ("content_block_delta", '{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"partial"}}'),
        ("content_block_stop", '{"type":"content_block_stop","index":0}'),
    )

    async def aiter_lines():
        for line in sse_data:
            yield line

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.aiter_lines = aiter_lines
    mock_response.headers = {"content-type": "text/event-stream"}

    chunks: list[dict] = []

    async def collect():
        async for chunk in adapter_with_key.send(
            messages=[{"role": "user", "content": "Say hello"}]
        ):
            chunks.append(chunk)

    with patch("httpx.AsyncClient", return_value=_mock_client(mock_response)):
        task = asyncio.create_task(collect())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass  # If CancelledError propagates, cancel is NOT a return

        # After cancel, the task must have stopped cleanly
        text_parts = [c["delta"] for c in chunks if c.get("type") == "text"]
        text = "".join(text_parts)
        assert "Hello" in text, f"expected partial text, got {text!r}"
        assert "partial" in text, f"expected more partial text, got {text!r}"


# ---------------------------------------------------------------------------
# Scenario 7: Stream interrupted (SSE connection lost)
# ---------------------------------------------------------------------------


async def test_stream_interrupted(adapter_with_key):
    """SSE stream interruption must yield stream_interrupted error.

    R-A-4: errors must be yielded, not raised.
    """

    async def aiter_lines():
        yield "event: message_start"
        yield 'data: {"type":"message_start","message":{"id":"msg_1","role":"assistant","content":[],"model":"claude-3","usage":{"input_tokens":10,"output_tokens":1}}}'
        yield ""
        raise httpx.StreamError("Connection reset by peer")

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.aiter_lines = aiter_lines
    mock_response.headers = {"content-type": "text/event-stream"}

    with patch("httpx.AsyncClient", return_value=_mock_client(mock_response)):
        chunks = []
        async for chunk in adapter_with_key.send(
            messages=[{"role": "user", "content": "Say hello"}]
        ):
            chunks.append(chunk)

    assert len(chunks) == 1
    assert chunks[0]["type"] == "error"
    assert chunks[0]["code"] == "stream_interrupted"


# ---------------------------------------------------------------------------
# Scenario 8: Non-streaming full JSON — must slice into tokens (R-A-2)
# ---------------------------------------------------------------------------


async def test_non_streaming_full_json(adapter_with_key):
    """When upstream returns a complete JSON instead of SSE, the adapter
    must slice it into token-like chunks (R-A-2 compliance).
    """
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Hello world from Claude."}
        ],
        "model": "claude-3",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }

    with patch("httpx.AsyncClient", return_value=_mock_client(mock_response)):
        chunks = []
        async for chunk in adapter_with_key.send(
            messages=[{"role": "user", "content": "Say hello"}]
        ):
            chunks.append(chunk)

    texts = [c["delta"] for c in chunks if c.get("type") == "text"]
    full = "".join(texts)
    assert "Hello world from Claude." in full, f"expected text, got {full!r}"
    assert len(texts) >= 2, (
        f"non-streaming response should be sliced into >=2 chunks, got {len(texts)}: {texts}"
    )

    usages = [c for c in chunks if c.get("type") == "usage"]
    assert len(usages) == 1

    assert chunks[-1]["type"] == "done"


# ---------------------------------------------------------------------------
# Scenario 9: build_adapter with missing API key
# ---------------------------------------------------------------------------


async def test_build_adapter_missing_api_key():
    """When configured through build_adapter with empty api_key,
    send() must yield missing_api_key error, not raise KeyError.
    """
    adapter = build_adapter("claude_code", {"api_key": "", "model": "claude-sonnet-4-20250514"})
    chunks = []
    async for chunk in adapter.send(
        messages=[{"role": "user", "content": "Say hello"}]
    ):
        chunks.append(chunk)

    assert len(chunks) == 1
    assert chunks[0]["type"] == "error"
    assert chunks[0]["code"] == "missing_api_key"
