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
from services.sub_agent_gate import SubAgentGate

logger = logging.getLogger("agenthub.services.react_loop")

# ---------------------------------------------------------------------------
# 结构化工具调用解析
# ---------------------------------------------------------------------------

_TOOL_CALL_BLOCK_RE = re.compile(
    r"```(?:tool_call|tool)\s*\n(.+?)```", re.DOTALL
)

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)

_TOOL_CALL_START = re.compile(r"```(?:tool_call|tool)\s*\n")


def _json_dumps_tool_args(args: Any) -> str:
    """Serialize tool arguments for OpenAI-style assistant tool_calls."""
    if isinstance(args, str):
        return args
    try:
        return json.dumps(args if isinstance(args, dict) else {}, ensure_ascii=False)
    except (TypeError, ValueError):
        return "{}"


def _native_tool_history_mode(adapter: AgentAdapter) -> str:
    """Return the native tool-result history format expected by the adapter.

    OpenAI-compatible Chat Completions requires a previous assistant message with
    ``tool_calls`` before any ``role=tool`` messages. Anthropic adapters in this
    project do their own message normalization and should not receive OpenAI
    tool-result history from this generic ReAct loop.
    """
    name = str(getattr(adapter, "name", "") or "").lower()
    if name in {"codex", "opencode"}:
        return "openai"
    return "text"


class _ToolCallFilter:
    """Streaming filter that strips ```tool_call / ```tool blocks from text
    in real-time, so raw JSON never reaches the frontend.

    Handles partial backtick prefixes at chunk boundaries and multiple
    tool_call blocks within a single response.
    """

    def __init__(self) -> None:
        self._buf = ""
        self._in_block = False

    def feed(self, chunk: str) -> str:
        """Feed a text delta, return clean text safe to forward immediately."""
        self._buf += chunk
        clean: list[str] = []

        while self._buf:
            if not self._in_block:
                m = _TOOL_CALL_START.search(self._buf)
                if m:
                    clean.append(self._buf[:m.start()])
                    self._buf = self._buf[m.end():]
                    self._in_block = True
                else:
                    # Hold back partial backtick prefix at buffer end
                    tail = 0
                    for i in range(min(3, len(self._buf)), 0, -1):
                        if self._buf.endswith("`" * i):
                            tail = i
                            break
                    if tail:
                        clean.append(self._buf[:-tail])
                        self._buf = self._buf[-tail:]
                    else:
                        clean.append(self._buf)
                        self._buf = ""
                    break
            else:
                # Inside block — scan for closing ```
                end = self._buf.find("\n```")
                if end >= 0:
                    skip = end + 4
                    if skip < len(self._buf) and self._buf[skip] in "\r\n":
                        skip += 1
                    self._buf = self._buf[skip:]
                    self._in_block = False
                else:
                    self._buf = ""
                    break

        return "".join(clean)

    def flush(self) -> str:
        """Return any remaining clean text after the stream ends."""
        if self._in_block:
            self._buf = ""
            self._in_block = False
            return ""
        tail = self._buf
        self._buf = ""
        return tail


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


def _dedup_prefix(prev_tail: str, chunk: str, min_overlap: int = 3) -> str:
    """Strip leading text from *chunk* that overlaps with the end of *prev_tail*.

    When the model restates context across ReAct steps, the new step's text
    often repeats the tail of what was already sent.  This detects overlapping
    prefixes (up to the length of *prev_tail*) and skips them so the client
    doesn't see duplicate sentences.

    Only removes overlap when both sides are >= *min_overlap* chars — shorter
    matches are likely coincidental character n-grams.
    """
    if not prev_tail or not chunk:
        return chunk
    max_overlap = min(len(prev_tail), len(chunk))
    for n in range(max_overlap, min_overlap - 1, -1):
        if prev_tail[-n:] == chunk[:n]:
            return chunk[n:]
    return chunk


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
        max_steps: int = 5,
        llm_timeout: float = 120.0,
    ) -> None:
        self.registry = registry
        self.max_steps = max(max_steps, 1)
        self.llm_timeout = llm_timeout
        # 收集非原生 FC 模型的文本以解析工具调用
        self._collected_text: list[str] = []
        # Track text sent across steps to dedup overlapping prefixes
        self._sent_text_tail = ""

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

        # Capture the original user request for sub-agent gate evaluation
        _orig_user_text = ""
        for _m in reversed(messages):
            if _m.get("role") == "user" and isinstance(_m.get("content"), str):
                _orig_user_text = _m["content"]
                break

        # For non-native-FC models (DeepSeek etc.), inject structured tool-call prompt
        # so the model knows to output ```tool_call blocks that we parse after each step.
        if has_tools and self.registry is not None:
            react_prompt = self.registry.to_react_prompt()
            if react_prompt:
                # Prepend as a system-level instruction before the first user message
                inserted = False
                for i, msg in enumerate(messages):
                    if msg.get("role") == "user":
                        messages.insert(i, {"role": "system", "content": react_prompt})
                        inserted = True
                        break
                if not inserted:
                    messages.insert(0, {"role": "system", "content": react_prompt})

        caps = getattr(adapter, "capabilities", None)
        if callable(caps):
            cap_list = caps()
        else:
            cap_list = caps or []
        native_fc = "tool_use" in cap_list
        native_history_mode = _native_tool_history_mode(adapter) if native_fc else "text"
        buffer_structured_tool_text = has_tools and not native_fc

        for step in range(1, self.max_steps + 1):
            logger.debug("ReAct step %d/%d", step, self.max_steps)

            tcf = _ToolCallFilter()
            step_chunks: list[dict[str, Any]] = []
            step_text = ""
            step_text_clean = ""  # tool_call blocks stripped
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
                            step_text += delta  # raw, for tool_call parsing
                            step_chunks.append(chunk)
                            if buffer_structured_tool_text:
                                continue
                            # Stream through filter: strips ```tool_call blocks
                            filtered = tcf.feed(delta)
                            if filtered:
                                step_text_clean += filtered
                                # Cross-step dedup: strip overlapping prefix
                                deduped = _dedup_prefix(self._sent_text_tail, filtered)
                                if deduped:
                                    self._sent_text_tail = (self._sent_text_tail + deduped)[-128:]
                                    yield {"type": "text", "delta": deduped}

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

                if not buffer_structured_tool_text:
                    # Flush filter: yield any clean text after the last tool_call block
                    tail = tcf.flush()
                    if tail:
                        step_text_clean += tail
                        deduped = _dedup_prefix(self._sent_text_tail, tail)
                        if deduped:
                            self._sent_text_tail = (self._sent_text_tail + deduped)[-128:]
                            yield {"type": "text", "delta": deduped}

                # ---- 检测工具调用 ----

                # 1. 原生 FC 模式
                if not step_tool_calls and has_tools:
                    step_tool_calls = _extract_tool_calls(step_chunks)

                # 2. 结构化提示词模式（非原生 FC）
                if not step_tool_calls and has_tools and step_text:
                    step_tool_calls = parse_tool_call_blocks(step_text)

                if buffer_structured_tool_text and not step_tool_calls:
                    if _TOOL_CALL_START.search(step_text):
                        messages.append({
                            "role": "system",
                            "content": (
                                "上一轮工具调用格式无效，系统已丢弃原始 tool_call 文本，"
                                "避免把 JSON 残片当成最终答案。请继续完成任务："
                                "如果要生成长文档，请直接输出完整 Markdown 正文；"
                                "如果必须调用 create_artifact，请确保 arguments 是严格 JSON，"
                                "content 字段内的换行使用 \\n 转义，不要在 tool_call JSON 字符串中嵌入未转义代码围栏。"
                            ),
                        })
                        yield {
                            "type": "observation",
                            "name": "tool_call_parser",
                            "result": "Invalid structured tool_call was discarded; retrying.",
                            "status": "done",
                            "step": step,
                        }
                        continue

                    clean_text = tcf.feed(step_text) + tcf.flush()
                    if clean_text:
                        step_text_clean += clean_text
                        deduped = _dedup_prefix(self._sent_text_tail, clean_text)
                        if deduped:
                            self._sent_text_tail = (self._sent_text_tail + deduped)[-128:]
                            yield {"type": "text", "delta": deduped}

                # 没有工具调用 → 结束
                if not step_tool_calls:
                    if usage_chunk:
                        yield usage_chunk
                    yield {"type": "done"}
                    return

                # ---- 执行工具并注入 Observation（并行执行独立工具） ----

                valid_calls = [tc for tc in step_tool_calls if tc.get("name")]
                if not valid_calls:
                    if usage_chunk:
                        yield usage_chunk
                    yield {"type": "done"}
                    return

                # Yield "running" for all tools before executing
                for tc in valid_calls:
                    yield {
                        "type": "observation",
                        "name": str(tc["name"]),
                        "arguments": tc.get("arguments", {}),
                        "status": "running",
                        "step": step,
                    }

                # Execute all tools concurrently
                async def _exec_one(name: str, args: dict[str, Any]) -> str:
                    try:
                        return await self.registry.execute(name, args)
                    except Exception as exc:
                        return f"Error executing {name}: {exc}"

                coros = [
                    _exec_one(str(tc["name"]), tc.get("arguments", {}))
                    for tc in valid_calls
                ]
                results = await asyncio.gather(*coros, return_exceptions=True)

                if native_fc and native_history_mode == "openai":
                    messages.append({
                        "role": "assistant",
                        "content": step_text_clean or None,
                        "tool_calls": [
                            {
                                "id": str(tc.get("call_id") or f"call_{step}_{idx}"),
                                "type": "function",
                                "function": {
                                    "name": str(tc["name"]),
                                    "arguments": _json_dumps_tool_args(tc.get("arguments", {})),
                                },
                            }
                            for idx, tc in enumerate(valid_calls)
                        ],
                    })

                # Yield results in original order, inject observations
                for i, tc in enumerate(valid_calls):
                    name = str(tc["name"])
                    call_id = str(tc.get("call_id") or f"call_{step}_{i}")
                    result = results[i] if i < len(results) else "??"
                    if isinstance(result, BaseException):
                        result = f"Error executing {name}: {result}"
                    result_str = str(result)

                    yield {
                        "type": "observation",
                        "name": name,
                        "result": result_str,
                        "status": "done",
                        "step": step,
                    }

                    if native_fc and native_history_mode == "openai":
                        # OpenAI-compatible native FC: tool results must follow
                        # an assistant message containing matching tool_calls.
                        messages.append({
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": result_str,
                        })
                    else:
                        # Legacy: plain-text injection for non-FC models
                        messages.append({
                            "role": "user",
                            "content": (
                                f"--- 工具调用结果: {name} ---\n{result_str}\n"
                                f"--- {name} 结束 ---"
                            ),
                        })

                # After tool results: inject continuation hint so the agent
                # doesn't stop after the first tool call. Non-FC models often
                # treat tool results as "task complete" without this nudge.
                if not native_fc and valid_calls:
                    messages.append({
                        "role": "system",
                        "content": (
                            "工具已执行完毕。请根据工具返回的结果继续完成你的任务。"
                            "如果还有其他步骤需要执行（如创建更多文件、生成HTML页面等），"
                            "请继续执行，不要停止。一次性完成所有工作。"
                        ),
                    })

                # ---- Sub-agent gate: suggest delegation for cross-domain tasks ----
                has_sub_agents = any(
                    tc.get("name") == "create_agent" for tc in step_tool_calls
                )
                hint = SubAgentGate.should_suggest_delegation(
                    user_text=_orig_user_text,
                    step_count=step,
                    has_sub_agents=has_sub_agents,
                )
                if hint and has_tools:
                    messages.append({"role": "system", "content": hint})

            except asyncio.TimeoutError:
                logger.warning("ReAct step %d timed out after %.0fs", step, self.llm_timeout)
                yield {"type": "warning", "code": "react_timeout", "message": f"LLM 响应超时（{self.llm_timeout:.0f}秒），已生成的内容将作为结果提交"}
                yield {"type": "done"}
                return
            except Exception as exc:
                logger.exception("ReAct step %d failed", step)
                yield {"type": "error", "code": "react_error", "message": f"ReAct 步骤 {step} 异常: {type(exc).__name__}: {exc}"}
                yield {"type": "done"}
                return

        # 达到最大步数 — 不是硬错误，Agent 已产出部分结果
        logger.warning("ReAct: max steps (%d) reached", self.max_steps)
        yield {"type": "warning", "code": "react_max_steps", "message": f"已达到最大推理步数（{self.max_steps}），已生成的内容将作为结果提交"}
        yield {"type": "done"}

    # ------------------------------------------------------------------
    # 工具函数
    # ------------------------------------------------------------------

    @staticmethod
    def should_use_react(adapter: AgentAdapter, user_text: str) -> bool:
        """判断当前请求是否需要走 ReAct 循环。

        启发式规则：
        - 极短消息（<=5 字，如"你好""继续""ok"）跳过 ReAct
        - adapter 有工具能力（``tool_use`` in capabilities）则启用 ReAct
        - 用户消息包含明显操作意图（文件/代码/创建/搜索等）也启用
        """
        user_stripped = user_text.strip()

        caps = getattr(adapter, "capabilities", None)
        if callable(caps):
            cap_list = caps()
        else:
            cap_list = caps or []
        has_tool_cap = "tool_use" in cap_list
        lower_text = user_stripped.lower()

        # Pure writing/document requests should not enter ReAct just because the
        # model has tools. Non-native tool prompts often wrap long Markdown in a
        # tool_call JSON block, which is brittle when the document itself
        # contains fenced code examples. Let the normal final-text artifact path
        # persist these as full Markdown documents.
        doc_terms = (
            "文档", "文章", "介绍", "教程", "说明", "报告",
            "document", "article", "guide", "explain", "write-up",
        )
        tool_or_workspace_terms = (
            "文件", "保存", "写入", "修改", "代码", "网页", "搜索", "查找",
            "html", "css", "javascript", "typescript", "workspace",
            "file", "save", "write file", "modify", "code", "web", "search",
        )
        if any(term in lower_text for term in doc_terms) and not any(
            term in lower_text for term in tool_or_workspace_terms
        ):
            return False

        # 操作意图关键词（中英文）
        intent_keywords = [
            "写", "生成", "创建", "修改", "删除", "搜索", "查找",
            "测试", "报告", "文档", "配置", "部署", "审查", "分析",
            "读取", "写入", "文件", "代码", "构建",
            "write", "create", "generate", "modify", "delete", "search",
            "test", "report", "document", "config", "deploy", "review",
            "build", "file", "code",
        ]
        has_intent = any(k in user_stripped.lower() for k in intent_keywords)

        # Short messages are continuations/follow-ups ("可以", "继续", "ok"),
        # not new task initiations. Don't enable ReAct — agent should respond directly.
        if len(user_stripped) <= 8:
            return False

        return has_tool_cap
