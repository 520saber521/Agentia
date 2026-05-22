"""CodexAdapter — OpenAI Chat Completions API via SSE streaming.

Adapter contract compliance (``ai-collab/rules/adapter.mdc``):
1. Stateless — no instance state beyond ``config``
2. Streaming — yields text tokens as they arrive via SSE
3. Cancel = return — ``asyncio.CancelledError`` propagates to caller
4. Errors yielded, never raised — 429 / 5xx / timeout yield ``error`` chunk
5. Registered in ``ADAPTER_REGISTRY``
"""

from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator, List, Optional

import httpx

from .base import AgentAdapter, Chunk

OPENAI_API_BASE = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-2024-11-20"
DEFAULT_MAX_TOKENS = 4096
REQUEST_TIMEOUT_S = 60.0


class CodexAdapter(AgentAdapter):
    """Adapter for OpenAI-compatible Chat Completions API.

    Config keys:
    - ``api_key`` (required) — OpenAI API key
    - ``model`` (optional, default ``gpt-4o-2024-11-20``)
    - ``base_url`` (optional, default ``https://api.openai.com/v1``)
    - ``max_tokens`` (optional, default 4096)
    - ``system_prompt`` (optional, default None)
    """

    name = "codex"

    def __init__(self, config: Optional[dict[str, Any]] = None) -> None:
        super().__init__(config)
        self.api_key: str = str(
            self.config.get("api_key")
            or os.environ.get("OPENAI_API_KEY")
            or ""
        )
        self.model: str = str(self.config.get("model", DEFAULT_MODEL))
        self.base_url: str = str(self.config.get("base_url", OPENAI_API_BASE)).rstrip("/")
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
            yield {"type": "error", "code": "missing_api_key", "message": "OpenAI API key not configured"}
            return

        openai_messages: list[dict[str, Any]] = list(messages)
        if self.system_prompt:
            openai_messages.insert(0, {"role": "system", "content": self.system_prompt})

        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": openai_messages,
            "stream": stream,
        }
        if tools:
            body["tools"] = tools

        headers = {
            "authorization": f"Bearer {self.api_key}",
            "content-type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT_S)) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=body,
                    headers=headers,
                )
        except httpx.TimeoutException:
            yield {"type": "error", "code": "timeout", "message": f"OpenAI API timeout after {REQUEST_TIMEOUT_S}s"}
            return
        except httpx.TransportError as exc:
            yield {"type": "error", "code": "upstream_error", "message": f"Transport error: {exc}"}
            return

        if response.status_code == 429:
            yield {"type": "error", "code": "rate_limited", "message": "OpenAI API rate limited (429)"}
            return
        if response.status_code == 400:
            body_text = await response.aread()
            yield {"type": "error", "code": "bad_request", "message": body_text.decode(errors="replace")}
            return
        if response.status_code >= 500:
            yield {"type": "error", "code": "upstream_error", "message": f"OpenAI API {response.status_code}"}
            return
        if response.status_code != 200:
            body_text = await response.aread()
            yield {"type": "error", "code": "upstream_error", "message": f"OpenAI API {response.status_code}: {body_text.decode(errors='replace')}"}
            return

        if not stream:
            body_data = response.json()
            choice = (body_data.get("choices") or [{}])[0]
            text = (choice.get("message") or {}).get("content", "") or ""
            if text:
                yield {"type": "text", "delta": text}
            usage = body_data.get("usage") or {}
            yield {
                "type": "usage",
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
            }
            yield {"type": "done"}
            return

        input_tokens = 0
        output_tokens = 0

        try:
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    if line.startswith(":") or not line.strip():
                        continue
                    if line.startswith("{"):
                        try:
                            err_data = json.loads(line)
                            if err_data.get("error"):
                                yield {"type": "error", "code": "upstream_error", "message": str(err_data["error"])}
                                return
                        except (ValueError, TypeError):
                            pass
                    continue

                payload_str = line[6:].strip()
                if payload_str == "[DONE]":
                    break

                try:
                    payload = json.loads(payload_str)
                except (ValueError, TypeError):
                    continue

                choices = payload.get("choices") or []
                for choice in choices:
                    delta = choice.get("delta") or {}
                    finish_reason = choice.get("finish_reason")
                    content = delta.get("content")

                    if content:
                        yield {"type": "text", "delta": content}

                    if finish_reason == "stop":
                        break

                usage = payload.get("usage")
                if usage:
                    input_tokens = usage.get("prompt_tokens", input_tokens)
                    output_tokens = usage.get("completion_tokens", output_tokens)

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
        return ["text", "code", "tool_use", "web_search"]
