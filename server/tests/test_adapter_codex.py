"""CodexAdapter tests — 5 required scenarios (ai-collab/skills/new-adapter.md Step 5).

Coverage:
1. Successful streaming — SSE events assembled into text chunks
2. Missing API key — yields error, no HTTP call
3. Rate limited (429) — yields rate_limited error
4. Timeout — yields timeout error
5. Upstream 5xx — yields upstream_error
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from adapters.codex import CodexAdapter


@pytest.fixture
def adapter_with_key():
    return CodexAdapter({"api_key": "sk-test123", "model": "gpt-4o-2024-11-20"})


@pytest.fixture
def adapter_no_key():
    return CodexAdapter({"api_key": "", "model": "gpt-4o-2024-11-20"})


def _sse_chunks(*texts: str) -> list[str]:
    lines: list[str] = []
    for i, text in enumerate(texts):
        if i == 0:
            lines.append(f"data: {{{{'choices':[{{'delta':{{'content':'{text}'}},'index':0,'finish_reason':None}}],'usage':None}}}}")
        else:
            lines.append(f"data: {{{{'choices':[{{'delta':{{'content':'{text}'}},'index':0,'finish_reason':None}}],'usage':None}}}}")
    lines.append("data: [DONE]")
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
    async def aiter_lines():
        yield 'data: {"choices":[{"delta":{"content":"Hello"},"index":0,"finish_reason":null}],"usage":null}'
        yield 'data: {"choices":[{"delta":{"content":" world"},"index":0,"finish_reason":null}],"usage":null}'
        yield 'data: {"choices":[{"delta":{"content":""},"index":0,"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":5}}'
        yield "data: [DONE]"

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.aiter_lines = aiter_lines

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
