"""ClaudeCodeAdapter — Anthropic Messages API via SSE streaming.

Adapter contract compliance (``ai-collab/rules/adapter.mdc``):
1. Stateless — no instance state beyond ``config``
2. Streaming — yields text tokens as they arrive via SSE
3. Cancel = return — ``asyncio.CancelledError`` propagates to caller
4. Errors yielded, never raised — 429 / 5xx / timeout yield ``error`` chunk
5. Registered in ``ADAPTER_REGISTRY``
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, List, Optional

import httpx

from .base import AgentAdapter, Chunk

ANTHROPIC_API_BASE = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-4-20250514"
DEFAULT_MAX_TOKENS = 4096
REQUEST_TIMEOUT_S = 60.0


def _role(role: str) -> str:
    """Map internal role to Anthropic role."""
    if role == "system":
        return "user"
    return role


async def _parse_sse(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    """Parse Anthropic SSE stream, yielding parsed JSON events.

    Anthropic SSE format:
        event: message_start
        data: {...}

        event: content_block_delta
        data: {...}
    """
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
    - ``max_tokens`` (optional, default 4096)
    """

    name = "claude_code"

    def __init__(self, config: Optional[dict[str, Any]] = None) -> None:
        super().__init__(config)
        self.api_key: str = str(self.config.get("api_key") or "")
        self.model: str = str(self.config.get("model", DEFAULT_MODEL))
        self.base_url: str = str(self.config.get("base_url", ANTHROPIC_API_BASE)).rstrip("/")
        self.max_tokens: int = int(self.config.get("max_tokens", DEFAULT_MAX_TOKENS))

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
        for m in messages:
            role = _role(m.get("role", "user"))
            content = m.get("content", "")
            if isinstance(content, str):
                anthropic_messages.append({"role": role, "content": content})
            elif isinstance(content, list):
                anthropic_messages.append({"role": role, "content": content})

        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": anthropic_messages,
        }
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

        try:
            async for parsed in _parse_sse(response):
                event = parsed["event"]
                data = parsed["data"]
                try:
                    payload = json.loads(data) if data else {}
                except (ValueError, TypeError):
                    continue

                if event == "message_start":
                    msg = payload.get("message") or {}
                    usage = msg.get("usage") or {}
                    input_tokens = usage.get("input_tokens", 0)

                elif event == "content_block_delta":
                    delta = payload.get("delta") or {}
                    if delta.get("type") == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            current_text += text
                            yield {"type": "text", "delta": text}

                elif event == "message_delta":
                    delta = payload.get("delta") or {}
                    usage = payload.get("usage") or {}
                    output_tokens = usage.get("output_tokens", 0) or len(current_text)

                elif event == "message_stop":
                    break

        except httpx.StreamError as exc:
            yield {"type": "error", "code": "stream_interrupted", "message": str(exc)}
            return

        yield {
            "type": "usage",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        yield {"type": "done"}

    def capabilities(self) -> List[str]:
        return ["text", "code", "tool_use", "vision"]
