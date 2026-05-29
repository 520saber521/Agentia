"""ClaudeCodeAdapter — Anthropic Messages API via SSE streaming.

Adapter contract compliance (``ai-collab/rules/adapter.mdc``):
1. R-A-1: Stateless — no instance state beyond ``config``
2. R-A-2: Streaming — yields text tokens as they arrive via SSE
3. R-A-3: Cancel = return — catches ``CancelledError`` and returns
4. R-A-4: Errors yielded, never raised — 429 / 5xx / timeout yield ``error`` chunk
5. R-A-5: ``capabilities()`` returns only convention enums
6. R-A-6: Registered in ``ADAPTER_REGISTRY``
7. R-A-7: 5 test scenarios covered in ``test_adapter_claude.py``
8. R-A-8: ``__init__`` does not read ``os.environ``
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, AsyncIterator, List, Optional

import httpx

from .base import AgentAdapter, Chunk

ANTHROPIC_API_BASE = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-4-20250514"
DEFAULT_MAX_TOKENS = 12000
REQUEST_TIMEOUT_S = 60.0

# For slicing non-streaming response into token-like chunks
_TOKEN_SPLIT_RE = re.compile(r"(\s+|[.!?،。！？、]+)")


def _split_into_tokens(text: str) -> list[str]:
    """Split text into 'token-like' pieces for streaming illusion.

    Splits on whitespace/punctuation boundaries, yielding pieces
    that resemble natural token boundaries.
    """
    parts = _TOKEN_SPLIT_RE.split(text)
    return [p for p in parts if p]


def _role(role: str) -> str:
    if role == "system":
        return "user"
    return role


async def _parse_sse(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    """Parse Anthropic SSE stream, yielding parsed JSON events."""
    buf = ""
    event_type = ""
    async for raw in response.aiter_lines():
        if not raw:
            if event_type and buf:
                yield {"event": event_type, "data": buf}
            buf = ""
            event_type = ""
            continue
        if raw.startswith("event: "):
            event_type = raw[7:]
        elif raw.startswith("data: "):
            buf = raw[6:]
    if event_type and buf:
        yield {"event": event_type, "data": buf}


async def _sse_or_json(
    response: httpx.Response, stream_requested: bool
) -> AsyncIterator[dict[str, Any]]:
    """Detect if response is SSE or complete JSON; yield parsed events either way.

    If ``stream_requested`` and response is SSE, yield SSE events.
    If non-streaming (complete JSON), yield a synthetic ``message_stop`` event.
    """
    content_type = response.headers.get("content-type", "")
    is_sse = "text/event-stream" in content_type

    if is_sse or stream_requested:
        try:
            async for parsed in _parse_sse(response):
                yield parsed
            return
        except httpx.StreamError as exc:
            yield {"event": "error_stream", "data": json.dumps({"code": "stream_interrupted", "message": str(exc)})}
            return

    body = response.json()
    yield {"event": "message_start", "data": json.dumps(body)}


def _last_user_text(messages: List[dict[str, Any]]) -> str:
    for m in reversed(messages or []):
        if m.get("role") == "user":
            c = m.get("content")
            return c if isinstance(c, str) else str(c)
    return ""


class ClaudeCodeAdapter(AgentAdapter):
    """Adapter for Anthropic's Claude via the Messages API.

    Config keys:
    - ``api_key`` (required) — Anthropic API key
    - ``model`` (optional, default ``claude-sonnet-4-20250514``)
    - ``base_url`` (optional, default ``https://api.anthropic.com/v1``)
    - ``max_tokens`` (optional, default 12000)

    R-A-8 compliance: ``__init__`` does NOT read ``os.environ``.
    """

    name = "claude_code"

    def __init__(self, config: Optional[dict[str, Any]] = None) -> None:
        super().__init__(config)
        self.api_key: str = str(self.config.get("api_key") or "")
        self.model: str = str(self.config.get("model", DEFAULT_MODEL))
        self.base_url: str = str(self.config.get("base_url", ANTHROPIC_API_BASE)).rstrip("/")
        self.max_tokens: int = int(self.config.get("max_tokens", DEFAULT_MAX_TOKENS))
        self.system_prompt: str = str(self.config.get("system_prompt") or "")

    async def send(
        self,
        messages: List[dict[str, Any]],
        *,
        tools: Optional[List[dict[str, Any]]] = None,
        artifacts_context: Optional[dict[str, Any]] = None,
        stream: bool = True,
    ) -> AsyncIterator[Chunk]:
        if not self.api_key:
            yield {"type": "error", "code": "missing_api_key", "message": "Anthropic API key not configured"}
            return

        anthropic_messages: list[dict[str, Any]] = []
        last_role = ""
        for m in messages:
            role = _role(m.get("role", "user"))
            content = m.get("content", "")
            if role not in {"user", "assistant"}:
                role = "user"
            if not content:
                continue
            if anthropic_messages and role == last_role:
                previous = anthropic_messages[-1].get("content", "")
                if isinstance(previous, str) and isinstance(content, str):
                    anthropic_messages[-1]["content"] = f"{previous}\n\n{content}"
                    continue
            if isinstance(content, str):
                anthropic_messages.append({"role": role, "content": content})
                last_role = role
            elif isinstance(content, list):
                anthropic_messages.append({"role": role, "content": content})
                last_role = role

        if anthropic_messages and anthropic_messages[-1]["role"] != "user":
            anthropic_messages.append({"role": "user", "content": "请基于以上对话继续回复用户。"})

        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": anthropic_messages,
        }
        if self.system_prompt:
            body["system"] = self.system_prompt
        if tools:
            body["tools"] = tools
        if stream:
            body["stream"] = True

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT_S)) as client:
                response = await client.post(
                    f"{self.base_url}/messages",
                    json=body,
                    headers=headers,
                )
        except httpx.TimeoutException:
            yield {"type": "error", "code": "timeout", "message": f"Anthropic API timeout after {REQUEST_TIMEOUT_S}s"}
            return
        except httpx.TransportError as exc:
            yield {"type": "error", "code": "upstream_error", "message": f"Transport error: {exc}"}
            return

        if response.status_code == 429:
            yield {"type": "error", "code": "rate_limited", "message": "Anthropic API rate limited (429)"}
            return
        if response.status_code == 400:
            body_text = await response.aread()
            yield {"type": "error", "code": "bad_request", "message": body_text.decode(errors="replace")}
            return
        if response.status_code >= 500:
            yield {"type": "error", "code": "upstream_error", "message": f"Anthropic API {response.status_code}"}
            return
        if response.status_code != 200:
            body_text = await response.aread()
            yield {"type": "error", "code": "upstream_error", "message": f"Anthropic API {response.status_code}: {body_text.decode(errors='replace')}"}
            return

        if not stream:
            body_data = response.json()
            text = ""
            for block in (body_data.get("content") or []):
                if block.get("type") == "text":
                    text += block.get("text", "")
            if text:
                yield {"type": "text", "delta": text}
            usage = body_data.get("usage") or {}
            yield {
                "type": "usage",
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            }
            yield {"type": "done"}
            return

        input_tokens = 0
        output_tokens = 0
        current_text = ""
        is_streaming = False
        is_full_json = False
        finish_reason_seen = ""
        active_tool_calls: dict[int, dict[str, Any]] = {}

        cancel_event = asyncio.Event()

        def _on_cancel(_task=None):
            cancel_event.set()

        loop = asyncio.get_running_loop()
        current_task = asyncio.current_task(loop=loop)
        if current_task is not None:
            current_task.add_done_callback(_on_cancel)

        try:
            async for parsed in _sse_or_json(response, stream_requested=True):
                if cancel_event.is_set():
                    return

                event = parsed["event"]
                data = parsed["data"]

                if event == "error_stream":
                    err = json.loads(data) if data else {}
                    yield {"type": "error", "code": err.get("code", "stream_interrupted"), "message": err.get("message", "stream interrupted")}
                    return

                try:
                    payload = json.loads(data) if data else {}
                except (ValueError, TypeError):
                    continue

                if event == "message_start":
                    is_streaming = True
                    msg = payload.get("message") or {}
                    usage = msg.get("usage") or {}
                    input_tokens = usage.get("input_tokens", 0)

                    # Detect non-streaming response (full JSON in SSE reader)
                    content = msg.get("content") or []
                    if content and not is_streaming:
                        is_full_json = True
                        text = "".join(
                            block.get("text", "") for block in content if block.get("type") == "text"
                        )
                        tokens = _split_into_tokens(text)
                        for tok in tokens:
                            if cancel_event.is_set():
                                return
                            current_text += tok
                            yield {"type": "text", "delta": tok}

                elif event == "content_block_start":
                    block = payload.get("content_block") or {}
                    idx = payload.get("index", 0)
                    if block.get("type") == "tool_use":
                        active_tool_calls[idx] = {
                            "name": str(block.get("name", "")),
                            "call_id": str(block.get("id", "")),
                            "arguments": "",
                        }

                elif event == "content_block_delta":
                    delta = payload.get("delta") or {}
                    idx = payload.get("index", 0)
                    if delta.get("type") == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            current_text += text
                            yield {"type": "text", "delta": text}
                    elif delta.get("type") == "input_json_delta":
                        if idx in active_tool_calls:
                            active_tool_calls[idx]["arguments"] += delta.get("partial_json", "")

                elif event == "content_block_stop":
                    idx = payload.get("index", 0)
                    if idx in active_tool_calls:
                        tc = active_tool_calls.pop(idx)
                        try:
                            args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                        except (json.JSONDecodeError, TypeError):
                            args = {"raw": tc["arguments"]}
                        yield {
                            "type": "tool_call",
                            "name": tc["name"],
                            "args": args,
                            "call_id": tc["call_id"],
                        }

                elif event == "message_delta":
                    delta = payload.get("delta") or {}
                    stop_reason = delta.get("stop_reason")
                    if stop_reason:
                        finish_reason_seen = str(stop_reason)
                    usage = payload.get("usage") or {}
                    output_tokens = usage.get("output_tokens", 0) or len(current_text)

                elif event == "message_stop":
                    break

        except asyncio.CancelledError:
            cancel_event.set()
            return

        if not is_streaming and not current_text:
            body_data = response.json()
            text = ""
            for block in (body_data.get("content") or []):
                if block.get("type") == "text":
                    text += block.get("text", "")
            if text:
                tokens = _split_into_tokens(text)
                for tok in tokens:
                    if cancel_event.is_set():
                        return
                    yield {"type": "text", "delta": tok}

        yield {
            "type": "usage",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        if finish_reason_seen == "max_tokens":
            yield {
                "type": "error",
                "code": "output_truncated",
                "message": (
                    "The model stopped because it reached max_tokens. "
                    "Increase max_tokens or ask it to continue."
                ),
            }
            return

        yield {"type": "done", "finish_reason": finish_reason_seen or "stop"}

    def capabilities(self) -> List[str]:
        return ["text", "code", "tool_use", "vision", "web_search", "file"]
