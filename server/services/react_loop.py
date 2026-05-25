"""ReAct 循环引擎 — Thought → Action → Observation 多轮自主推理。

架构
====
``ReActEngine`` 包裹 ``AgentAdapter.send()``，在流式输出的基础上自动管理：

  Thought  →  LLM 输出文本（流式转发给调用方）
  Action   →  检测工具调用（原生 ``ChunkToolCall`` 或结构化代码块）
  Observation → 执行工具并将结果注入 history，驱动下一轮推理

支持两种工具调用模式：

1. **原生 FC** — Claude ``tool_use`` / GPT ``function_call``，adapter 直接 yield ``ChunkToolCall``
2. **结构化提示词** — 非原生 FC 模型（DeepSeek 等）回复 `` ```tool_call `` 代码块，引擎自动解析

用法
====
  engine = ReActEngine(registry)
  async for chunk in engine.run(adapter, messages):
      if chunk["type"] == "text":
          await conn.send(event("stream_chunk", delta=chunk["delta"]))
      elif chunk["type"] == "observation":
          # 工具执行结果
      elif chunk["type"] == "done":
          break
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, AsyncIterator, Optional

from adapters.base import AgentAdapter, Chunk
from services.tool_registry import ToolRegistry

logger = logging.getLogger("agenthub.services.react_loop")

# ---------------------------------------------------------------------------
# 结构化工具调用解析
# ---------------------------------------------------------------------------

_TOOL_CALL_BLOCK_RE = re.compile(
    r"```(?:tool_call|tool)\s*\n(.+?)```", re.DOTALL
)

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_tool_call_blocks(text: str) -> list[dict[str, Any]]:
    """从模型回复中解析 ```tool_call 代码块。

    支持格式：

    ```tool_call
    {
      "name": "read_file",
      "arguments": {"path": "server/main.py"}
    }
    ```

    返回 ``[{"name": ..., "arguments": {...}}, ...]`` 列表。
    """
    calls = []
    for m in _TOOL_CALL_BLOCK_RE.finditer(text):
        block = m.group(1).strip()
        try:
            parsed = json.loads(block)
        except json.JSONDecodeError:
            # 尝试提取 JSON 对象
            obj_m = _JSON_OBJECT_RE.search(block)
            if obj_m:
                try:
                    parsed = json.loads(obj_m.group(0))
                except json.JSONDecodeError:
                    continue
            else:
                continue

        if isinstance(parsed, dict):
            name = parsed.get("name", "")
            args = parsed.get("arguments") or parsed.get("args") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (json.JSONDecodeError, TypeError):
                    args = {"text": args}
            calls.append({"name": name, "arguments": args, "call_id": parsed.get("call_id", "")})
        elif isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict) and item.get("name"):
                    calls.append(item)
    return calls


def _extract_tool_calls(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从已收到的 chunks 中提取工具调用（原生 FC 模式）。"""
    calls = []
    for c in chunks:
        if c.get("type") == "tool_call":
            name = str(c.get("name", ""))
            args = c.get("args") or c.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (json.JSONDecodeError, TypeError):
                    pass
            calls.append({"name": name, "arguments": args, "call_id": str(c.get("call_id", ""))})
    return calls


# ---------------------------------------------------------------------------
# ReActEngine
# ---------------------------------------------------------------------------


class ReActEngine:
    """ReAct 循环引擎。

    参数
    ----------
    registry : ToolRegistry | None
        工具注册中心。为 ``None`` 时跳过 ReAct 循环，直接透传 adapter 输出。
    max_steps : int
        最大推理步数，防止无限循环。
    """

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        max_steps: int = 3,
        llm_timeout: float = 60.0,
    ) -> None:
        self.registry = registry
        self.max_steps = max_steps
        self.llm_timeout = llm_timeout
        # 收集非原生 FC 模型的文本以解析工具调用
        self._collected_text: list[str] = []

    async def run(
        self,
        adapter: AgentAdapter,
        messages: list[dict[str, Any]],
        *,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> AsyncIterator[Chunk]:
        """运行 ReAct 循环，yield 与 ``adapter.send()`` 兼容的 Chunk。

        当没有注册工具或模型不需要工具时，表现与直接调用 ``adapter.send()`` 一致。
        """
        has_tools = self.registry is not None and bool(self.registry.list_tools())

        for step in range(1, self.max_steps + 1):
            logger.debug("ReAct step %d/%d", step, self.max_steps)

            step_chunks: list[dict[str, Any]] = []
            step_text = ""
            step_tool_calls: list[dict[str, Any]] = []
            usage_chunk: dict[str, Any] | None = None

            try:
                async with asyncio.timeout(self.llm_timeout):
                    async for chunk in adapter.send(
                        messages=messages,
                        tools=tools if step == 1 else None,  # 后续轮次不传 tools（已包含在 history 中）
                    ):
                        ctype = chunk.get("type")

                        if ctype == "text":
                            delta = chunk.get("delta", "")
                            step_text += delta
                            step_chunks.append(chunk)
                            yield chunk  # 流式转发给客户端

                        elif ctype == "tool_call":
                            step_chunks.append(chunk)
                            step_tool_calls.append(chunk)
                            yield chunk  # 转发（run_agent_reply 需要处理）

                        elif ctype == "usage":
                            usage_chunk = chunk  # 最后再 yield
                            step_chunks.append(chunk)

                        elif ctype == "done":
                            break  # 当前步结束，检查是否需要继续

                        else:
                            step_chunks.append(chunk)
                            yield chunk  # artifact / error 等

                # ---- 检测工具调用 ----

                # 1. 原生 FC 模式
                if not step_tool_calls and has_tools:
                    step_tool_calls = _extract_tool_calls(step_chunks)

                # 2. 结构化提示词模式（非原生 FC）
                if not step_tool_calls and has_tools and step_text:
                    step_tool_calls = parse_tool_call_blocks(step_text)

                # 没有工具调用 → 结束
                if not step_tool_calls:
                    if usage_chunk:
                        yield usage_chunk
                    yield {"type": "done"}
                    return

                # ---- 执行工具并注入 Observation ----

                for tc in step_tool_calls:
                    name = str(tc.get("name", ""))
                    args = tc.get("arguments", {})
                    call_id = str(tc.get("call_id", ""))

                    if not name:
                        logger.warning("ReAct: empty tool name, skipping")
                        continue

                    logger.info("ReAct: executing tool %s with args %s", name, args)

                    # 执行工具
                    yield {
                        "type": "observation",
                        "name": name,
                        "arguments": args,
                        "status": "running",
                        "step": step,
                    }
                    result = await self.registry.execute(name, args)

                    # Yield observation result
                    yield {
                        "type": "observation",
                        "name": name,
                        "result": result,
                        "status": "done",
                        "step": step,
                    }

                    # 将 Observation 注入 history（驱动下一轮推理）
                    observation_entry = (
                        f"--- 工具调用结果: {name} ---\n{result}\n"
                        f"--- {name} 结束 ---"
                    )
                    messages.append({"role": "user", "content": observation_entry})

            except Exception as exc:
                logger.exception("ReAct step %d failed", step)
                yield {"type": "error", "code": "react_error", "message": str(exc)}
                yield {"type": "done"}
                return

        # 达到最大步数
        logger.warning("ReAct: max steps (%d) reached", self.max_steps)
        yield {"type": "usage", "input_tokens": 0, "output_tokens": 0}
        yield {"type": "done"}

    # ------------------------------------------------------------------
    # 工具函数
    # ------------------------------------------------------------------

    @staticmethod
    def should_use_react(adapter: AgentAdapter, user_text: str) -> bool:
        """判断当前请求是否需要走 ReAct 循环。

        启发式规则：
        - 短消息（<=15 字）视为简单对话，跳过 ReAct
        - adapter 有工具能力（``tool_use`` in capabilities）
        - 用户消息包含明确的文件操作或搜索指令
        """
        # 短消息(<=15字)直接跳过 ReAct：问候、追问、确认等无需调工具
        if len(user_text.strip()) <= 15:
            return False

        caps = getattr(adapter, "capabilities", None)
        if callable(caps):
            cap_list = caps()
        else:
            cap_list = caps or []
        has_tool_cap = "tool_use" in cap_list

        # 精确的关键词列表 — 只有明确涉及文件/代码/搜索操作时才触发
        keywords = [
            "读取文件", "写入文件", "创建文件", "修改文件", "删除文件",
            "搜索", "查找文件", "读文件", "写文件",
            "read file", "write file", "create file", "delete file",
            "search for", "find file",
        ]
        has_keyword = any(k in user_text.lower() for k in keywords)

        return has_tool_cap and has_keyword
