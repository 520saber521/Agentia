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


async def test_strips_reasoning_content_and_retries_bad_history(adapter_with_key):
    first_response = MagicMock(spec=httpx.Response)
    first_response.status_code = 400
    first_response.aread = AsyncMock(
        return_value=b"The reasoning_content in the thinking mode must be passed back to the API."
    )

    async def aiter_lines():
        yield 'data: {"choices":[{"delta":{"content":"Recovered"},"index":0,"finish_reason":"stop"}],"usage":{"prompt_tokens":3,"completion_tokens":1}}'
        yield "data: [DONE]"

    second_response = MagicMock(spec=httpx.Response)
    second_response.status_code = 200
    second_response.aiter_lines = aiter_lines

    mock_client = _mock_client(first_response)
    mock_client.post.side_effect = [first_response, second_response]

    with patch("httpx.AsyncClient", return_value=mock_client):
        chunks = []
        async for chunk in adapter_with_key.send(
            messages=[
                {"role": "user", "content": "start"},
                {"role": "assistant", "content": "thinking", "reasoning_content": "secret"},
                {"role": "user", "content": [{"type": "text", "text": "continue", "reasoning_content": "x"}]},
            ]
        ):
            chunks.append(chunk)

    assert mock_client.post.call_count == 2
    first_payload = mock_client.post.call_args_list[0].kwargs["json"]
    assert "reasoning_content" not in str(first_payload)
    retry_payload = mock_client.post.call_args_list[1].kwargs["json"]
    assert all(m["role"] != "assistant" for m in retry_payload["messages"])
    assert [c["delta"] for c in chunks if c.get("type") == "text"] == ["Recovered"]


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
