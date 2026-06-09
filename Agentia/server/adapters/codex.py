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
DEFAULT_MAX_TOKENS = 60000
REQUEST_TIMEOUT_S = 60.0
REASONING_CONTENT_ERROR = "reasoning_content"


def _sanitize_message_for_chat_completion(message: dict[str, Any]) -> dict[str, Any]:
    """Drop provider-specific thinking fields before sending chat completions."""
    clean = dict(message)
    clean.pop("reasoning_content", None)
    content = clean.get("content")
    if isinstance(content, list):
        clean["content"] = [
            {k: v for k, v in part.items() if k != "reasoning_content"}
            if isinstance(part, dict)
            else part
            for part in content
        ]
    return clean


def _sanitize_messages_for_chat_completion(messages: List[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_sanitize_message_for_chat_completion(m) for m in messages]


class CodexAdapter(AgentAdapter):
    """Adapter for OpenAI-compatible Chat Completions API.

    Config keys:
    - ``api_key`` (required) — OpenAI API key
    - ``model`` (optional, default ``gpt-4o-2024-11-20``)
    - ``base_url`` (optional, default ``https://api.openai.com/v1``)
    - ``max_tokens`` (optional, default 12000)
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

        openai_messages = _sanitize_messages_for_chat_completion(list(messages))
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

        client = httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT_S))
        try:
            try:
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

            if response.status_code == 400:
                body_text = await response.aread()
                detail = body_text.decode(errors="replace")
                if REASONING_CONTENT_ERROR in detail:
                    retry_body = dict(body)
                    retry_body["messages"] = [
                        m for m in openai_messages if m.get("role") != "assistant"
                    ]
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        json=retry_body,
                        headers=headers,
                    )
                else:
                    yield {"type": "error", "code": "bad_request", "message": detail}
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
            pending_tool_calls: dict[int, dict[str, Any]] = {}
            stream_finished = False
            finish_reason_seen = ""

            try:
                async for line in response.aiter_lines():
                    if stream_finished:
                        break

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
                        if not content and delta.get("reasoning_content"):
                            continue

                        if content:
                            yield {"type": "text", "delta": content}

                        # Stream tool_calls from delta
                        tool_calls = delta.get("tool_calls")
                        if tool_calls:
                            for tc in tool_calls:
                                tc_idx = tc.get("index", 0)
                                if tc_idx not in pending_tool_calls:
                                    pending_tool_calls[tc_idx] = {
                                        "name": "", "arguments": "", "call_id": "",
                                    }
                                entry = pending_tool_calls[tc_idx]
                                if tc.get("id"):
                                    entry["call_id"] = tc["id"]
                                func = tc.get("function") or {}
                                if func.get("name"):
                                    entry["name"] = func["name"]
                                if func.get("arguments"):
                                    entry["arguments"] += func["arguments"]

                        if finish_reason == "tool_calls":
                            for tc_idx in sorted(pending_tool_calls.keys()):
                                tc = pending_tool_calls[tc_idx]
                                if tc.get("name"):
                                    try:
                                        args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                                    except (json.JSONDecodeError, TypeError):
                                        args = {"raw": tc["arguments"]}
                                    yield {"type": "tool_call", "name": tc["name"], "args": args, "call_id": tc["call_id"]}
                            pending_tool_calls.clear()

                        if finish_reason:
                            finish_reason_seen = str(finish_reason)
                            stream_finished = True
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
            if finish_reason_seen == "length":
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
        finally:
            await client.aclose()

    def capabilities(self) -> List[str]:
        return ["text", "code", "tool_use", "web_search"]


class OpenCodeAdapter(CodexAdapter):
    """OpenCode-compatible adapter.

    OpenCode-compatible gateways generally expose an OpenAI-style chat
    completions API, so this adapter intentionally reuses the Codex adapter
    transport while allowing agents to be configured with ``adapter_type`` set
    to ``opencode``.
    """

    name = "opencode"
