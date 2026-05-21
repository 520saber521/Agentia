"""MockAdapter —— 离线固定回复，仅用于 W1 链路打通。

特点：

- 不调任何外部 API，完全可在 CI / 离线环境下运行。
- 按"英文词 / 中文字 / 空白 / 标点"切片，模拟真实 LLM 的流式 token。
- ``delay_ms`` 可控每片之间的睡眠时长，便于演示和压测。
- 对外部 ``asyncio.CancelledError`` 透传，配合 BFF 的取消机制。
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, AsyncIterator, List, Optional

from .base import AgentAdapter, Chunk

DEFAULT_REPLY = (
    "Hello! I am the AgentHub MockAdapter.\n"
    "I stream a fixed reply so you can verify the chain end-to-end "
    "before any real LLM API is wired in.\n"
    "你刚才说：{echo}"
)

# 简易 tokenizer：英文 / 数字成串，空白单独，CJK 单字，其它按字符。
_TOKEN_RE = re.compile(r"[A-Za-z]+|[0-9]+|\s+|[\u4e00-\u9fff]|.", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    return [tok for tok in _TOKEN_RE.findall(text or "") if tok]


def _last_user_text(messages: List[dict[str, Any]] | None) -> str:
    """从 ``messages`` 里捞最后一条 user 消息的文本内容。"""
    for m in reversed(messages or []):
        if m.get("role") == "user":
            c = m.get("content")
            return c if isinstance(c, str) else str(c)
    return ""


class MockAdapter(AgentAdapter):
    """W1 用 Mock：固定模板 + 把最近 user 文本回灌进 ``{echo}``。"""

    name = "mock"

    def __init__(self, config: Optional[dict[str, Any]] = None) -> None:
        super().__init__(config)
        self.delay_ms: int = int(self.config.get("delay_ms", 20))
        self.reply_template: str = str(self.config.get("reply", DEFAULT_REPLY))

    async def send(
        self,
        messages: List[dict[str, Any]],
        *,
        tools: Optional[List[dict[str, Any]]] = None,  # noqa: ARG002
        artifacts_context: Optional[dict[str, Any]] = None,  # noqa: ARG002
        stream: bool = True,
    ) -> AsyncIterator[Chunk]:
        echo = _last_user_text(messages) or "<empty>"
        full = self.reply_template.format(echo=echo)

        tokens = _tokenize(full) if stream else [full]
        delay = max(0.0, self.delay_ms / 1000.0)

        input_tokens = sum(
            len(_tokenize(str(m.get("content", "")))) for m in (messages or [])
        )
        output_tokens = 0

        for tok in tokens:
            yield {"type": "text", "delta": tok}
            output_tokens += 1
            if delay:
                # 这里 sleep 是取消窗口；asyncio.CancelledError 透传给上层。
                await asyncio.sleep(delay)

        yield {
            "type": "usage",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        yield {"type": "done"}

    def capabilities(self) -> List[str]:
        return ["text", "mock"]
