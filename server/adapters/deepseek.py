"""DeepSeekAdapter — DeepSeek Chat Completions API via SSE streaming.

DeepSeek API is OpenAI-compatible, following the same SSE streaming pattern.

Config keys:
- ``api_key`` (required) — DeepSeek API key
- ``model`` (optional, default ``deepseek-chat``)
- ``base_url`` (optional, default ``https://api.deepseek.com/v1``)
- ``max_tokens`` (optional, default 4096)
- ``system_prompt`` (optional) — system message prepended to conversation

Adapter contract compliance:
1. Stateless — no instance state beyond ``config``
2. Streaming — yields text tokens as they arrive via SSE
3. Cancel = return — ``asyncio.CancelledError`` propagates to caller
4. Errors yielded, never raised — 429 / 5xx / timeout yield ``error`` chunk
5. Registered in ``ADAPTER_REGISTRY``
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, List, Optional

import httpx

from .base import AgentAdapter, Chunk

DEEPSEEK_API_BASE = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_MAX_TOKENS = 4096
REQUEST_TIMEOUT_S = 120.0


async def _parse_sse(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    """Parse OpenAI-style SSE stream, yielding parsed JSON chunks."""
    buf = ""
    async for raw in response.aiter_lines():
        if not raw:
            if buf:
                yield {"data": buf}
            buf = ""
            continue
        if raw.startswith("data: "):
            line = raw[6:]
            if line.strip() == "[DONE]":
                return
            buf = line
    if buf:
        yield {"data": buf}


class DeepSeekAdapter(AgentAdapter):
    """Adapter for DeepSeek via OpenAI-compatible Chat Completions API."""

    name = "deepseek"

    def __init__(self, config: Optional[dict[str, Any]] = None) -> None:
        super().__init__(config)
        self.api_key: str = str(self.config.get("api_key") or "")
        self.model: str = str(self.config.get("model", DEFAULT_MODEL))
        self.base_url: str = str(self.config.get("base_url", DEEPSEEK_API_BASE)).rstrip("/")
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
            yield {"type": "error", "code": "missing_api_key", "message": "DeepSeek API key not configured"}
            return

        openai_messages: list[dict[str, Any]] = []
        if self.system_prompt:
            openai_messages.append({"role": "system", "content": self.system_prompt})

        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system" and not self.system_prompt:
                openai_messages.append({"role": "system", "content": content})
            elif role in ("user", "assistant"):
                openai_messages.append({"role": role, "content": content})

        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": openai_messages,
        }
        if stream:
            body["stream"] = True

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT_S)) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=body,
                    headers=headers,
                )
        except httpx.TimeoutException:
            yield {"type": "error", "code": "timeout", "message": f"DeepSeek API timeout after {REQUEST_TIMEOUT_S}s"}
            return
        except httpx.TransportError as exc:
            yield {"type": "error", "code": "upstream_error", "message": f"Transport error: {exc}"}
            return

        if response.status_code == 429:
            yield {"type": "error", "code": "rate_limited", "message": "DeepSeek API rate limited (429)"}
            return
        if response.status_code == 400:
            body_text = await response.aread()
            yield {"type": "error", "code": "bad_request", "message": body_text.decode(errors="replace")}
            return
        if response.status_code == 401:
            yield {"type": "error", "code": "auth_error", "message": "DeepSeek API authentication failed (401)"}
            return
        if response.status_code >= 500:
            yield {"type": "error", "code": "upstream_error", "message": f"DeepSeek API {response.status_code}"}
            return
        if response.status_code != 200:
            body_text = await response.aread()
            yield {"type": "error", "code": "upstream_error", "message": f"DeepSeek API {response.status_code}: {body_text.decode(errors='replace')}"}
            return

        # Non-streaming response
        if not stream:
            data = response.json()
            choices = data.get("choices") or []
            text = ""
            if choices:
                msg = choices[0].get("message") or {}
                text = msg.get("content") or ""
            if text:
                yield {"type": "text", "delta": text}
            usage = data.get("usage") or {}
            yield {
                "type": "usage",
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
            }
            yield {"type": "done"}
            return

        # Streaming response
        input_tokens = 0
        output_tokens = 0

        cancel_event = asyncio.Event()

        def _on_cancel(_task=None):
            cancel_event.set()

        loop = asyncio.get_running_loop()
        current_task = asyncio.current_task(loop=loop)
        if current_task is not None:
            current_task.add_done_callback(_on_cancel)

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT_S)) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    json=body,
                    headers=headers,
                ) as response:
                    if response.status_code != 200:
                        body_text = await response.aread()
                        yield {"type": "error", "code": "upstream_error", "message": f"DeepSeek API {response.status_code}: {body_text.decode(errors='replace')}"}
                        return

                    async for parsed in _parse_sse(response):
                        if cancel_event.is_set():
                            return

                        raw_data = parsed.get("data", "")
                        if not raw_data:
                            continue

                        try:
                            chunk_data = json.loads(raw_data)
                        except (ValueError, TypeError):
                            continue

                        choices = chunk_data.get("choices") or []
                        if choices:
                            delta = choices[0].get("delta") or {}
                            content = delta.get("content") or ""
                            if content:
                                yield {"type": "text", "delta": content}

                        usage = chunk_data.get("usage")
                        if usage:
                            input_tokens = usage.get("prompt_tokens", 0)
                            output_tokens = usage.get("completion_tokens", 0)

        except asyncio.CancelledError:
            cancel_event.set()
            return
        except httpx.TimeoutException:
            yield {"type": "error", "code": "timeout", "message": "DeepSeek API stream timeout"}
            return
        except httpx.TransportError as exc:
            yield {"type": "error", "code": "upstream_error", "message": f"Stream transport error: {exc}"}

        yield {
            "type": "usage",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        yield {"type": "done"}

    def capabilities(self) -> List[str]:
        return ["text", "code", "tool_use"]
