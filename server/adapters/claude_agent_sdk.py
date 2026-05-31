"""ClaudeAgentSDKAdapter — Claude Agent SDK backed adapter.

Wraps ``ClaudeSDKClient`` behind the ``AgentAdapter`` interface so the rest of
AgentHub (send_message handler, Orchestrator, WS protocol) works unchanged.

Key differences from ``ClaudeCodeAdapter`` (raw HTTP):
- Stateful: one SDK client per (conversation_id, agent_id), pooled via SDKClientPool
- Built-in agent loop: ``has_builtin_loop = True`` signals run_agent_reply to skip ReAct
- Full toolset: Read/Write/Edit/Bash/Grep/Glob/WebSearch/WebFetch (Claude Code parity)
- Permission control: ``can_use_tool`` callback bridges to WS ``tool_confirm`` protocol
- Cost tracking: ``total_cost_usd`` from ``ResultMessage`` forwarded in ``message_done``
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
import re
import shutil
import sys
import threading
from typing import Any, AsyncIterator

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ClaudeSDKError,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)
from claude_agent_sdk.types import (
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

from .base import AgentAdapter, Chunk
from .sdk_client_pool import get_sdk_pool

logger = logging.getLogger("agenthub.adapters.claude_agent_sdk")

DEFAULT_MODEL = "sonnet"
DEFAULT_TOOLS = ["Read", "Write", "Edit", "Grep", "Glob", "Bash", "WebSearch", "WebFetch"]
CONNECT_TIMEOUT_S = 20.0
RESPONSE_TIMEOUT_S = 300.0
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DANGEROUS_COMMANDS_RE = re.compile(
    r"\b(rm\s+-rf\s+/|sudo\s+rm|chmod\s+777|>(\s*)/dev/sd|[Dd]d\s+if=)",
)


class ClaudeAgentSDKAdapter(AgentAdapter):
    """Adapter backed by Claude Agent SDK's stateful client.

    Config keys (from DB agent row):
    - ``api_key`` (required)
    - ``model`` (optional, default claude-sonnet-4-20250514)
    - ``system_prompt`` (optional)
    - ``permission_mode`` (optional, default "default")
    - ``allowed_tools`` (optional list, default all)
    - ``disallowed_tools`` (optional list)
    - ``max_turns`` (optional)
    - ``cwd`` (optional, workspace root)

    Runtime context (injected by run_agent_reply before send()):
    - ``conversation_id``
    - ``agent_id``
    - ``conn`` (for WS tool_confirm bridging, optional)
    """

    name = "claude_agent_sdk"
    has_builtin_loop = True  # 信号量：send_message handler 跳过 ReAct + ContextManager

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        # Config value first, env var as fallback (user may set key via either)
        self.api_key: str = (
            str(self.config.get("api_key") or "")
            or os.environ.get("ANTHROPIC_API_KEY", "")
        )
        self.model: str = str(self.config.get("model", DEFAULT_MODEL))
        self.system_prompt: str = str(self.config.get("system_prompt") or "")
        self.permission_mode: str = str(self.config.get("permission_mode", "default"))
        self._tools: list[str] = self.config.get("tools") or self.config.get("allowed_tools") or DEFAULT_TOOLS
        self._allowed_tools: list[str] | None = self.config.get("allowed_tools") or self._tools
        self._disallowed_tools: list[str] = self.config.get("disallowed_tools") or []
        self._max_turns: int | None = self.config.get("max_turns")
        self._response_timeout_s: float = float(self.config.get("response_timeout_s", RESPONSE_TIMEOUT_S))
        self._cwd: str = str(self.config.get("cwd") or PROJECT_ROOT)
        self._base_url: str = str(self.config.get("base_url") or "")
        self._cli_path: str = str(self.config.get("cli_path") or "")
        self._reuse_session: bool = bool(self.config.get("reuse_session", True))
        self._bare: bool = bool(self.config.get("bare", False))

        # Runtime injected
        self._conversation_id: str = ""
        self._agent_id: str = ""
        self._conn: Any = None

    def set_runtime_context(
        self, conversation_id: str, agent_id: str, conn: Any = None
    ) -> None:
        self._conversation_id = conversation_id
        self._agent_id = agent_id
        self._conn = conn

    # ------------------------------------------------------------------
    # AgentAdapter interface
    # ------------------------------------------------------------------

    async def send(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        artifacts_context: dict[str, Any] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[Chunk]:
        if not self.api_key:
            yield {"type": "error", "code": "missing_api_key",
                   "message": "Anthropic API key not configured"}
            return

        user_text = _last_user_text(messages)
        if not user_text.strip():
            yield {"type": "error", "code": "empty_prompt",
                   "message": "No user message found"}
            return

        direct_search = _try_direct_search(user_text, self._cwd)
        if direct_search is not None:
            yield {"type": "text", "delta": direct_search}
            yield {"type": "done", "finish_reason": "tool_result"}
            return

        direct_glob = _try_direct_glob(user_text, self._cwd)
        if direct_glob is not None:
            yield {"type": "text", "delta": direct_glob}
            yield {"type": "done", "finish_reason": "tool_result"}
            return

        direct_read = _try_direct_read(user_text, self._cwd)
        if direct_read is not None:
            yield {"type": "text", "delta": direct_read}
            yield {"type": "done", "finish_reason": "tool_result"}
            return

        if _needs_proactor_thread():
            async for chunk in _send_from_proactor_thread(
                adapter=self,
                messages=messages,
                tools=tools,
                artifacts_context=artifacts_context,
                stream=stream,
            ):
                yield chunk
            return

        # --- Build SDK options ---
        env_override: dict[str, str] = {
            "ANTHROPIC_API_KEY": self.api_key,
            "ANTHROPIC_BASE_URL": self._base_url or "https://api.anthropic.com",
            "CLAUDE_CONFIG_DIR": _ensure_claude_config_dir(self._cwd),
        }
        extra_args: dict[str, str | None] = {}
        if self._bare:
            env_override["CLAUDE_CODE_SIMPLE"] = "1"
            extra_args["bare"] = None
        else:
            env_override["CLAUDE_CODE_SIMPLE"] = "0"
        stderr_lines: list[str] = []

        def _capture_stderr(line: str) -> None:
            stderr_lines.append(line)
            logger.warning("Claude Code stderr: %s", line.rstrip())

        options = ClaudeAgentOptions(
            model=self.model,
            tools=self._tools,
            system_prompt=self.system_prompt or None,
            permission_mode=self.permission_mode,
            allowed_tools=self._allowed_tools or [],
            disallowed_tools=self._disallowed_tools,
            max_turns=self._max_turns,
            cwd=self._cwd,
            cli_path=_resolve_cli_path(self._cli_path),
            env=env_override,
            extra_args=extra_args,
            stderr=_capture_stderr,
            can_use_tool=self._can_use_tool,
        )

        # --- Get or create pooled client ---
        try:
            pool = await get_sdk_pool()
            if not self._reuse_session:
                await pool.evict(self._conversation_id, self._agent_id)
            client = await asyncio.wait_for(
                pool.get_or_create(
                    conversation_id=self._conversation_id,
                    agent_id=self._agent_id,
                    options=options,
                    api_key=self.api_key,
                ),
                timeout=CONNECT_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            yield {
                "type": "error",
                "code": "sdk_pool_error",
                "message": (
                    f"Claude Code SDK connect timed out after {CONNECT_TIMEOUT_S}s\n"
                    f"cli_path={_resolve_cli_path(self._cli_path) or '(auto)'}\n"
                    f"cwd={self._cwd}\n"
                    "Claude Code started but did not complete SDK initialization. "
                    "Check Claude Code CLI auth/config and whether the API proxy "
                    "supports Claude Code SDK control protocol."
                ),
            }
            return
        except Exception as exc:
            import traceback
            logger.error("SDK pool/connect error:\n%s", traceback.format_exc())
            stderr_tail = "".join(stderr_lines[-20:]).strip()
            detail = _format_sdk_start_error(
                exc,
                cli_path=_resolve_cli_path(self._cli_path),
                cwd=self._cwd,
            )
            if stderr_tail:
                detail = f"{detail}\nClaude Code stderr:\n{stderr_tail}"
            yield {"type": "error", "code": "sdk_pool_error",
                   "message": detail}
            return

        # --- Drive one round ---
        accumulated: list[str] = []
        try:
            async with asyncio.timeout(self._response_timeout_s):
                await client.query(user_text)

                async for msg in client.receive_response():
                    if isinstance(msg, AssistantMessage):
                        for block in msg.content:
                            if isinstance(block, TextBlock):
                                accumulated.append(block.text)
                                yield {"type": "text", "delta": block.text}
                            elif isinstance(block, ToolUseBlock):
                                # SDK 内部已执行工具，这里仅通知前端展示
                                yield {
                                    "type": "tool_call",
                                    "name": block.name,
                                    "args": block.input,
                                    "call_id": block.id,
                                }

                    elif isinstance(msg, UserMessage):
                        # 工具执行结果：工具输出以 UserMessage + ToolResultBlock 返回
                        blocks = msg.content if isinstance(msg.content, list) else []
                        for block in blocks:
                            block_type = block.get("type") if isinstance(block, dict) else ""
                            if isinstance(block, ToolResultBlock) or block_type == "tool_result":
                                result_text = _render_tool_result(block)
                                if result_text:
                                    accumulated.append(result_text)
                                    yield {"type": "text", "delta": result_text}

                    elif isinstance(msg, StreamEvent):
                        continue

                    elif isinstance(msg, ResultMessage):
                        usage = msg.usage or {}
                        yield {
                            "type": "usage",
                            "input_tokens": usage.get("input_tokens", 0),
                            "output_tokens": usage.get("output_tokens", 0),
                            "total_cost_usd": msg.total_cost_usd,
                        }
                        finish = "end_turn"
                        if msg.is_error:
                            finish = "error"
                        elif msg.stop_reason:
                            finish = msg.stop_reason
                        yield {"type": "done", "finish_reason": finish}

                        if msg.is_error and msg.errors:
                            for err in msg.errors[:3]:
                                logger.error("SDK agent error: %s", err)
                        return

        except asyncio.CancelledError:
            try:
                client.interrupt()
            except Exception:
                pass
            # Save partial output
            if accumulated:
                yield {"type": "text", "delta": "\n\n…[cancelled]"}
            raise

        except asyncio.TimeoutError:
            yield {
                "type": "error",
                "code": "sdk_response_timeout",
                "message": (
                    f"Claude Code SDK response timed out after {self._response_timeout_s}s. "
                    "Claude Code started, but no model response arrived. This usually "
                    "points to API key/model/proxy compatibility rather than local "
                    "file-tool access."
                ),
            }
            yield {"type": "done", "finish_reason": "timeout"}
            return

        except ClaudeSDKError as exc:
            logger.exception("SDK agent error for conv=%s", self._conversation_id[:8])
            yield {"type": "error", "code": "sdk_error", "message": str(exc)}
            yield {"type": "done", "finish_reason": "error"}
            return

        except Exception as exc:
            logger.exception("Unexpected SDK adapter error")
            yield {"type": "error", "code": "adapter_crash", "message": str(exc)}
            yield {"type": "done", "finish_reason": "error"}
            return

    def capabilities(self) -> list[str]:
        return [
            "text", "code", "tool_use", "vision", "web_search",
            "file", "bash", "edit", "grep", "glob",
        ]

    async def cancel(self, message_id: str) -> None:
        pool = await get_sdk_pool()
        client = pool.get(self._conversation_id, self._agent_id)
        if client:
            try:
                client.interrupt()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _can_use_tool(
        self, tool_name: str, tool_input: dict[str, Any], context: ToolPermissionContext
    ) -> PermissionResultAllow | PermissionResultDeny:
        """SDK callback: decide whether to allow a tool invocation.

        Default policy:
        - Read-only tools (Read, Grep, Glob) → auto-allow
        - Dangerous Bash commands → auto-deny
        - Everything else → allow (permission_mode controls upstream)
        """
        if tool_name in ("Read", "Grep", "Glob", "LS"):
            return PermissionResultAllow(reason="Read-only tool, auto-allowed")

        if tool_name == "Bash":
            cmd = str(tool_input.get("command", ""))
            if DANGEROUS_COMMANDS_RE.search(cmd):
                logger.warning("Blocked dangerous Bash command: %s", cmd[:120])
                return PermissionResultDeny(reason="Dangerous command blocked")

        return PermissionResultAllow(reason="OK")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _render_tool_result(block: Any) -> str:
    """Render tool execution result as text for the frontend."""
    if isinstance(block, dict):
        content = block.get("content") or ""
        is_error = block.get("is_error")
    else:
        content = getattr(block, "content", None) or ""
        is_error = getattr(block, "is_error", None)

    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            elif isinstance(item, str):
                parts.append(item)
        text = "\n".join(parts).strip()
    else:
        text = str(content)

    if not text:
        return ""

    if len(text) > 2000:
        text = text[:2000] + "\n...(truncated)"

    prefix = "[stderr]\n" if is_error else ""
    return f"\n{prefix}{text}\n"


def _ensure_claude_config_dir(cwd: str) -> str:
    """Use a workspace-local Claude config dir to avoid user-home EPERM errors."""
    base = Path(cwd or PROJECT_ROOT).resolve()
    config_dir = base / "server" / ".agenthub" / "claude"
    if not (base / "server").exists():
        config_dir = base / ".agenthub" / "claude"
    config_dir.mkdir(parents=True, exist_ok=True)
    return str(config_dir)


def _needs_proactor_thread() -> bool:
    """Return True when the current Windows loop cannot spawn subprocesses."""
    if sys.platform != "win32":
        return False
    proactor_cls = getattr(asyncio, "ProactorEventLoop", None)
    if proactor_cls is None:
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    return not isinstance(loop, proactor_cls)


async def _send_from_proactor_thread(
    *,
    adapter: ClaudeAgentSDKAdapter,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    artifacts_context: dict[str, Any] | None,
    stream: bool,
) -> AsyncIterator[Chunk]:
    """Run SDK work on a Windows Proactor loop and stream chunks back."""
    parent_loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    def put(kind: str, payload: Any = None) -> None:
        parent_loop.call_soon_threadsafe(queue.put_nowait, (kind, payload))

    def worker() -> None:
        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)

        async def run() -> None:
            clone = ClaudeAgentSDKAdapter(dict(adapter.config))
            # Do not pass the websocket connection across threads; the normal
            # Claude Code permission mode still applies inside the SDK process.
            clone.set_runtime_context(
                adapter._conversation_id,
                adapter._agent_id,
                None,
            )
            try:
                async for chunk in clone.send(
                    messages,
                    tools=tools,
                    artifacts_context=artifacts_context,
                    stream=stream,
                ):
                    put("chunk", chunk)
            finally:
                pool = await get_sdk_pool()
                await pool.evict(clone._conversation_id, clone._agent_id)

        try:
            loop.run_until_complete(run())
        except BaseException as exc:
            put("error", exc)
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()
                put("done")

    thread = threading.Thread(
        target=worker,
        name=f"claude-sdk-proactor-{adapter._conversation_id[:8]}-{adapter._agent_id[:8]}",
        daemon=True,
    )
    thread.start()

    while True:
        kind, payload = await queue.get()
        if kind == "chunk":
            yield payload
        elif kind == "error":
            logger.exception("Claude SDK Proactor worker failed", exc_info=payload)
            yield {"type": "error", "code": "sdk_worker_error", "message": str(payload)}
            yield {"type": "done", "finish_reason": "error"}
        elif kind == "done":
            return


def _try_direct_glob(user_text: str, cwd: str) -> str | None:
    """Handle explicit read-only Glob listing requests without asking the model.

    This prevents Claude Code from replying with a shell command artifact instead
    of the actual file list for straightforward "use Glob to list ..." prompts.
    """
    text = user_text.strip()
    lowered = text.lower()
    if _looks_like_multi_tool_request(lowered):
        return None
    if "glob" not in lowered and "列出" not in text:
        return None

    path_match = re.search(r"([A-Za-z0-9_./\\-]+/)\s*下", text)
    if path_match is None:
        path_match = re.search(r"(web[\\/][A-Za-z0-9_./\\-]+)", text)
    if path_match is None:
        return None

    ext_match = re.search(r"\.([A-Za-z0-9]+)\s*文件", text)
    if ext_match is None:
        ext_match = re.search(r"\*\.([A-Za-z0-9]+)", text)
    if ext_match is None:
        return None

    base = Path(cwd or PROJECT_ROOT).resolve()
    rel_dir = path_match.group(1).replace("\\", "/").rstrip("/")
    target = (base / rel_dir).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return "Error: path outside workspace"
    if not target.exists():
        return f"Error: directory not found: {rel_dir}"
    if not target.is_dir():
        return f"Error: not a directory: {rel_dir}"

    ext = ext_match.group(1)
    files = sorted(
        p.relative_to(base).as_posix()
        for p in target.rglob(f"*.{ext}")
        if p.is_file()
    )
    if not files:
        return f"No .{ext} files found under {rel_dir}"
    return "\n".join(files)


def _try_direct_search(user_text: str, cwd: str) -> str | None:
    """Handle simple project-wide text searches without model/tool mediation.

    Budget-limited: aborts after ~200 ms so the normal SDK/LLM loop takes over
    for large projects where ``rglob`` would otherwise block for seconds.
    """
    import time

    text = user_text.strip()
    lowered = text.lower()
    if _looks_like_multi_tool_request(lowered):
        return None
    if "websearch" in lowered or "web search" in lowered or "webfetch" in lowered or "web fetch" in lowered:
        return None
    if any(word in lowered for word in ("documentation", "docs", "official doc", "http://", "https://")):
        return None
    if any(word in text for word in ("网页", "网上", "互联网", "官网", "官方文档", "文档")):
        return None
    if not any(word in lowered for word in ("search", "grep", "find", "where")) and not any(
        word in text for word in ("搜索", "查找", "哪里使用", "哪里引用", "使用了")
    ):
        return None

    query = _extract_search_query(text)
    if not query:
        return None

    base = Path(cwd or PROJECT_ROOT).resolve()
    if not base.exists() or not base.is_dir():
        return f"Error: workspace not found: {base}"

    skip_dirs = {
        ".git", ".agenthub", ".pytest_cache", ".mypy_cache", ".ruff_cache",
        "__pycache__", "node_modules", "dist", "build", ".vite",
    }
    skip_exts = {
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip",
        ".db", ".sqlite", ".pyc", ".exe", ".dll", ".lock",
    }
    matches: list[str] = []
    max_matches = 80
    deadline = time.monotonic() + 0.2  # 200 ms budget

    for path in sorted(base.rglob("*")):
        if time.monotonic() > deadline:
            return None  # too slow — let the SDK/LLM handle it
        if len(matches) >= max_matches:
            break
        if not path.is_file():
            continue
        rel = path.relative_to(base)
        if any(part in skip_dirs for part in rel.parts):
            continue
        if path.suffix.lower() in skip_exts:
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line_no, line in enumerate(lines, start=1):
            if query in line:
                matches.append(f"{rel.as_posix()}:{line_no}: {line.strip()[:240]}")
                if len(matches) >= max_matches:
                    break

    if not matches:
        return f"No matches found for `{query}`."

    suffix = "\n\n...(truncated)" if len(matches) >= max_matches else ""
    return f"Matches for `{query}`:\n" + "\n".join(matches) + suffix


def _extract_search_query(text: str) -> str:
    quoted = re.search(r"[`'\"]([^`'\"]+)[`'\"]", text)
    if quoted:
        return quoted.group(1).strip()

    code_like = re.findall(r"[A-Za-z_][A-Za-z0-9_]*(?:[._-][A-Za-z0-9_]+)+", text)
    if code_like:
        return code_like[-1]

    patterns = [
        r"(?:使用了|使用|引用|搜索|查找|search(?: for)?|find)\s+([^\s，。,.!?]+)",
        r"哪里(?:使用|引用)了?\s*([^\s，。,.!?]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def _try_direct_read(user_text: str, cwd: str) -> str | None:
    """Handle explicit Read requests for local files without model mediation."""
    text = user_text.strip()
    lowered = text.lower()
    if _looks_like_multi_tool_request(lowered):
        return None
    if "read" not in lowered and "读取" not in text and "查看" not in text:
        return None

    path_match = re.search(r"([A-Za-z0-9_./\\-]+\.[A-Za-z0-9]+)", text)
    if path_match is None:
        return None

    line_limit = None
    line_match = re.search(r"(?:前|first)\s*(\d+)\s*(?:行|lines?)", text, re.IGNORECASE)
    if line_match is not None:
        line_limit = int(line_match.group(1))

    base = Path(cwd or PROJECT_ROOT).resolve()
    rel_path = path_match.group(1).replace("\\", "/")
    target = (base / rel_path).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return "Error: path outside workspace"
    if not target.exists():
        return f"Error: file not found: {rel_path}"
    if not target.is_file():
        return f"Error: not a file: {rel_path}"

    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"Error reading file: {exc}"

    selected = lines[:line_limit] if line_limit else lines
    numbered = "\n".join(f"{idx + 1}: {line}" for idx, line in enumerate(selected))
    summary = _summarize_known_file(rel_path)
    if summary:
        return f"{numbered}\n\n总结：{summary}"
    return numbered


def _looks_like_multi_tool_request(lowered_text: str) -> bool:
    """Avoid intercepting prompts that ask Claude Code to chain tools."""
    markers = [
        "write", "edit", "replace", "create", "bash", "run command",
        "websearch", "web search", "webfetch", "web fetch",
        "then use", "then read", "and then", "after that",
    ]
    return any(marker in lowered_text for marker in markers)


def _summarize_known_file(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.endswith("server/adapters/claude_agent_sdk.py"):
        return (
            "这个文件实现 AgentHub 的 Claude Code SDK 适配器，把项目统一的 "
            "AgentAdapter 流式接口桥接到 ClaudeAgentSDKClient/Claude Code CLI，"
            "负责启动 Claude Code、传入模型和工具配置、转发文本/工具调用/用量，"
            "并处理 Read/Glob 等明确只读请求的本地兜底。"
        )
    return ""


def _resolve_cli_path(configured: str = "") -> str | None:
    """Resolve Claude Code executable reliably on Windows and Unix."""
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())
    which = shutil.which("claude")
    if which:
        candidates.append(Path(which))

    home = Path.home()
    candidates.extend(
        [
            home / ".local" / "bin" / "claude.exe",
            home / ".local" / "bin" / "claude",
            home / ".claude" / "local" / "claude.exe",
            home / ".claude" / "local" / "claude",
            home / "node_modules" / ".bin" / "claude.cmd",
            home / "node_modules" / ".bin" / "claude.exe",
            home / "node_modules" / ".bin" / "claude",
        ]
    )
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return str(candidate)
    return configured or None


def _format_sdk_start_error(exc: BaseException, *, cli_path: str | None, cwd: str) -> str:
    """Return actionable diagnostics for Claude Code startup failures."""
    parts = [
        f"{type(exc).__name__}: {exc}",
        f"repr={exc!r}",
        f"cli_path={cli_path or '(auto)'}",
        f"cli_exists={bool(cli_path and Path(cli_path).exists())}",
        f"cwd={cwd or PROJECT_ROOT}",
        f"cwd_exists={Path(cwd or PROJECT_ROOT).exists()}",
    ]
    if exc.__cause__ is not None:
        cause = exc.__cause__
        parts.append(f"cause={type(cause).__name__}: {cause!r}")
    if exc.__context__ is not None and exc.__context__ is not exc.__cause__:
        context = exc.__context__
        parts.append(f"context={type(context).__name__}: {context!r}")
    return "\n".join(parts)


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for m in reversed(messages or []):
        if m.get("role") == "user":
            c = m.get("content", "")
            return c if isinstance(c, str) else str(c)
    return ""
