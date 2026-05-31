"""四层上下文管理 — 系统提示词 + 项目上下文 + 工具上下文 + 会话历史。

架构
====
每一层在最终消息列表中的顺序与优先级：

  Layer  System Prompt (永不截断)
       ↓
  Layer  Project Context (pinned + 关键产物, 最后截断)
       ↓
  Layer  Tool Context (工具定义 + 调用结果, 最后截断)
       ↓
  Layer  Conversation History (从中间向两端裁剪)

三种裁剪策略由 ``ContextManager`` 根据对话状态自动切换：

  ``sliding`` — 对话轮数 < 10，固定保留最后 N 轮
  ``token``   — 中等长度，按 token 预算精确裁剪
  ``hybrid``  — 长对话，先滑窗再按 token 裁剪

用法
====
  cm = ContextManager(conversation_id, model="gpt-4o")
  async with Session() as s:
      await cm.load(s, system_prompt="...")
  messages = cm.build()

  # 直接传给 adapter
  async for chunk in adapter.send(messages=messages):
      ...
"""

from __future__ import annotations

import json
import logging
import time as _time
from typing import Any, Optional

from sqlalchemy import desc, select

from db.models import Message

logger = logging.getLogger("agenthub.services.context_manager")

# ---------------------------------------------------------------------------
# Module-level TTL cache for build() results — avoids redundant assembly
# when the same conversation is queried in rapid succession.
# ---------------------------------------------------------------------------

_BUILD_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_BUILD_CACHE_TTL = 5.0  # seconds
_BUILD_CACHE_MAX = 64


def _cache_get(key: str) -> list[dict[str, Any]] | None:
    entry = _BUILD_CACHE.get(key)
    if entry is None:
        return None
    ts, data = entry
    if _time.monotonic() - ts > _BUILD_CACHE_TTL:
        del _BUILD_CACHE[key]
        return None
    return data


def _cache_set(key: str, messages: list[dict[str, Any]]) -> None:
    if len(_BUILD_CACHE) >= _BUILD_CACHE_MAX:
        oldest = min(_BUILD_CACHE, key=lambda k: _BUILD_CACHE[k][0])
        del _BUILD_CACHE[oldest]
    _BUILD_CACHE[key] = (_time.monotonic(), messages)

# ---------------------------------------------------------------------------
# 模型上下文窗口上限（留 20% 给回复）
# ---------------------------------------------------------------------------

MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "claude-sonnet-4-20250514": 200_000,
    "claude-opus-4-7": 200_000,
    "gpt-4o": 128_000,
    "gpt-5.4": 128_000,
    "gpt-4o-2024-11-20": 128_000,
    "deepseek-chat": 64_000,
    "deepseek-v4-flash": 64_000,
}

DEFAULT_CONTEXT_LIMIT = 128_000
MAX_RESPONSE_TOKENS = 4096
SAFETY_MARGIN_RATIO = 0.90  # 预留 10% 给回复和 buffer（原 0.75 过于保守）

STRATEGY_SLIDING_WINDOW = "sliding"
STRATEGY_TOKEN_CONTROL = "token"
STRATEGY_HYBRID = "hybrid"

# 滑窗策略保留的对话轮数（针对 200K 上下文模型提升）
SLIDING_WINDOW_TURNS = 30  # 30 轮 = 60 条消息 (user + assistant)
HYBRID_WINDOW_TURNS = 50   # hybrid 先保留 50 轮，再按 token 进一步裁剪


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Estimate token count, preferring tiktoken for accuracy."""
    if not text:
        return 0
    try:
        import tiktoken
        _enc = tiktoken.get_encoding("cl100k_base")
        return len(_enc.encode(text))
    except (ImportError, Exception):
        pass
    # Fallback: character-based heuristic
    cjk = sum(1 for c in text if "一" <= c <= "鿿" or "　" <= c <= "〿")
    rest = len(text) - cjk
    return int(cjk / 1.5 + rest / 4) + 1


def _safe_json_loads(raw: str | None) -> dict[str, Any]:
    try:
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def _extract_artifact_summary(raw: dict[str, Any]) -> str | None:
    """从富媒体消息内容中提取一句话摘要。"""
    msg_type = raw.get("type", "")
    if msg_type == "text":
        text = raw.get("text", "")
        if text and len(text) > 10:
            return text[:200]
        return text or None
    if msg_type == "code":
        title = raw.get("title") or raw.get("fileName") or "代码文件"
        lang = raw.get("language") or ""
        return f"[代码] {title}" + (f" ({lang})" if lang else "")
    if msg_type == "diff":
        fname = raw.get("fileName") or raw.get("file_name") or "文件"
        summary = raw.get("summary") or ""
        return f"[变更] {fname}" + (f" — {summary}" if summary else "")
    if msg_type == "preview":
        title = raw.get("title") or "预览页面"
        return f"[预览] {title}"
    if msg_type == "file":
        fname = raw.get("fileName") or raw.get("file_name") or "文件"
        return f"[文件] {fname}"
    if msg_type in ("task_status", "deploy_status"):
        return None  # 状态类消息不需要带入上下文
    return None


def _format_tree_for_agent(root: str, max_depth: int = 2, prefix: str = "") -> str:
    """Generate a `tree`-like text representation of a directory."""
    import os

    _SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", ".agenthub", ".codex_team"}
    lines: list[str] = []
    try:
        entries = sorted(os.scandir(root), key=lambda e: (not e.is_dir(), e.name.lower()))
    except (PermissionError, OSError):
        return ""

    count = 0
    for entry in entries:
        if count >= 50:
            lines.append(f"{prefix}... (truncated)")
            break
        if entry.name.startswith(".") or entry.name in _SKIP:
            continue
        count += 1
        if entry.is_dir():
            lines.append(f"{prefix}{entry.name}/")
            if max_depth > 1:
                subtree = _format_tree_for_agent(
                    entry.path, max_depth - 1, prefix + "  "
                )
                if subtree:
                    lines.append(subtree)
        else:
            try:
                size = entry.stat().st_size
            except OSError:
                size = 0
            if size >= 1024:
                size_str = f" ({size / 1024:.1f} KB)"
            else:
                size_str = f" ({size} B)" if size > 0 else ""
            lines.append(f"{prefix}{entry.name}{size_str}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ContextManager
# ---------------------------------------------------------------------------


class ContextManager:
    """四层上下文管理器。

    参数
    ----------
    conversation_id : str
    model : str
        模型名称，用于查询上下文窗口上限。
    """

    def __init__(
        self,
        conversation_id: str,
        model: str = "gpt-4o",
    ) -> None:
        self.conversation_id = conversation_id
        self.model = model
        context_limit = MODEL_CONTEXT_LIMITS.get(model, DEFAULT_CONTEXT_LIMIT)
        self.max_tokens = int(context_limit * SAFETY_MARGIN_RATIO) - MAX_RESPONSE_TOKENS

        # 四层原始数据
        self.system_prompt: str = ""
        self.project_context: list[dict[str, Any]] = []  # pinned + 关键产物
        self.tool_context: list[dict[str, Any]] = []     # 工具定义 + 调用结果
        self.history: list[dict[str, Any]] = []           # 会话消息

        # 当前策略
        self.strategy: str = STRATEGY_SLIDING_WINDOW
        self._total_turns: int = 0
        self._total_chars: int = 0

    # ------------------------------------------------------------------
    # 加载
    # ------------------------------------------------------------------

    async def load(
        self,
        session,
        *,
        system_prompt: str = "",
        tools: Optional[list[dict[str, Any]]] = None,
        current_user_text: str = "",
    ) -> None:
        """从 DB 加载会话消息并构建四层上下文。"""
        self.system_prompt = system_prompt

        rows = (
            await session.scalars(
                select(Message)
                .where(Message.conversation_id == self.conversation_id)
                .order_by(desc(Message.created_at))
                .limit(200)
            )
        ).all()

        # 构建 history + project_context
        self.history = []
        self.project_context = []
        for m in reversed(rows):
            role = "assistant" if m.sender_type == "agent" else "user"
            raw = _safe_json_loads(m.content)
            text = raw.get("text", "") if isinstance(raw, dict) else ""
            if m.sender_type == "agent" and not text.strip():
                continue
            content_text = text or ""

            # 非纯文本消息 → 生成摘要
            msg_type = raw.get("type", "text") if isinstance(raw, dict) else "text"
            if msg_type != "text" or (msg_type == "text" and m.artifact_id):
                summary = _extract_artifact_summary(raw)
                if summary and not content_text:
                    content_text = summary
                elif summary:
                    content_text = content_text + "\n" + summary
                elif m.artifact_id:
                    content_text = content_text or f"[产物] {raw.get('title', raw.get('fileName', 'unknown'))}"

            if not content_text.strip():
                continue

            # Annotate artifact messages with ID so agents can call read_artifact
            if m.artifact_id and m.sender_type == "agent":
                content_text += (
                    f"\n[artifact_id: {m.artifact_id}"
                    + (f", file: {raw.get('fileName', raw.get('file_name', ''))}" if raw.get("fileName") or raw.get("file_name") else "")
                    + "]"
                )

            entry: dict[str, Any] = {
                "role": role,
                "content": content_text,
                "pinned": bool(m.pinned),
                "artifact_id": m.artifact_id,
                "sender_id": m.sender_id,
            }

            if m.pinned:
                self.project_context.append(entry)
            self.history.append(entry)

        # 确保当前用户消息在上下文中
        if current_user_text and not any(
            msg.get("content") == current_user_text for msg in self.history
        ):
            self.history.append({"role": "user", "content": current_user_text, "pinned": False})

        # 工具层
        if tools:
            self.tool_context = [
                {"role": "system", "content": json.dumps(t, ensure_ascii=False)}
                for t in tools
            ]

        # 统计
        self._total_turns = sum(1 for m in self.history if m["role"] == "user")
        self._total_chars = sum(len(m["content"]) for m in self.history)
        self._pinned_count = len(self.project_context)
        self._total_loaded = len(self.history)

        # 自动选择并执行策略
        self._pick_strategy()
        self._prune()

    # ------------------------------------------------------------------
    # 策略自动选择
    # ------------------------------------------------------------------

    def _pick_strategy(self) -> None:
        """根据对话轮数和消息总长度自动选择裁剪策略。"""
        if self._total_turns < 20:
            self.strategy = STRATEGY_SLIDING_WINDOW
        elif self._total_chars < 50_000:
            self.strategy = STRATEGY_TOKEN_CONTROL
        else:
            self.strategy = STRATEGY_HYBRID
        logger.debug(
            "Context strategy=%s for conv=%s (turns=%d, chars=%d)",
            self.strategy, self.conversation_id, self._total_turns, self._total_chars,
        )

    # ------------------------------------------------------------------
    # 裁剪策略
    # ------------------------------------------------------------------

    def _prune(self) -> None:
        if self.strategy == STRATEGY_SLIDING_WINDOW:
            self._prune_sliding_window()
        elif self.strategy == STRATEGY_TOKEN_CONTROL:
            self._prune_token_control()
        elif self.strategy == STRATEGY_HYBRID:
            self._prune_hybrid()

    def _estimate_layer_tokens(self) -> int:
        """估算四层总 token（system_prompt 单独计算）。"""
        total = estimate_tokens(self.system_prompt)
        for m in self.project_context:
            total += estimate_tokens(m["content"])
        for m in self.tool_context:
            total += estimate_tokens(m["content"])
        for m in self.history:
            total += estimate_tokens(m["content"])
        return total

    def _prune_sliding_window(self) -> None:
        """保留最后 N 轮对话 + project_context 完整保留。"""
        pinned_ids = {id(m) for m in self.project_context}

        # 非 pinned 消息：保留最后 SLIDING_WINDOW_TURNS 轮
        non_pinned = [m for m in self.history if id(m) not in pinned_ids]
        if len(non_pinned) > SLIDING_WINDOW_TURNS * 2:
            keep = non_pinned[-(SLIDING_WINDOW_TURNS * 2):]
            self.history = [m for m in self.history if id(m) in pinned_ids or m in keep]

    def _prune_token_control(self) -> None:
        """按 token 预算从中间向两端裁剪。"""
        pinned_ids = {id(m) for m in self.project_context}
        budget = self.max_tokens

        # 固定占用的 token
        fixed = estimate_tokens(self.system_prompt)
        for m in self.project_context:
            fixed += estimate_tokens(m["content"])
        for m in self.tool_context:
            fixed += estimate_tokens(m["content"])

        history_budget = budget - fixed
        if history_budget <= 0:
            self.history = [m for m in self.history if id(m) in pinned_ids]
            return

        # 保留 pinned 消息，然后从两端向中间丢弃
        pinned_msgs = [m for m in self.history if id(m) in pinned_ids]
        non_pinned = [m for m in self.history if id(m) not in pinned_ids]

        # 计算 pinned 已占用
        pinned_tokens = sum(estimate_tokens(m["content"]) for m in pinned_msgs)
        remaining = history_budget - pinned_tokens

        if remaining <= 0:
            self.history = pinned_msgs
            return

        # 从两端保留：最近的最重要，最早的最重要（开头 context）
        # 策略：保留前 3 条 + 后 N 条，丢弃中间
        if len(non_pinned) <= 6:
            keep = non_pinned
        else:
            head = non_pinned[:3]
            tail = non_pinned[3:]
            # 从 tail 的中间向前丢弃，直到 fit
            keep = list(head)
            for msg in reversed(tail):
                tok = estimate_tokens(msg["content"])
                if remaining - tok >= 0:
                    keep.append(msg)
                    remaining -= tok
                else:
                    break

        self.history = pinned_msgs + keep

    def _prune_hybrid(self) -> None:
        """先滑窗保留最近 30 轮，再按 token 预算精确裁剪。"""
        pinned_ids = {id(m) for m in self.project_context}

        # 第一步：滑窗
        non_pinned = [m for m in self.history if id(m) not in pinned_ids]
        if len(non_pinned) > HYBRID_WINDOW_TURNS * 2:
            keep = non_pinned[-(HYBRID_WINDOW_TURNS * 2):]
            self.history = [m for m in self.history if id(m) in pinned_ids or m in keep]

        # 第二步：token 控制
        self._prune_token_control()

    # ------------------------------------------------------------------
    # 构建最终消息列表
    # ------------------------------------------------------------------

    def build(self) -> list[dict[str, Any]]:
        """按四层顺序构建最终消息列表，用于传给 ``adapter.send()``。"""
        # Check TTL cache first — avoids redundant assembly on rapid successive calls
        cache_key = f"{self.conversation_id}:{self._pinned_count}:{len(self.tool_context)}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        messages: list[dict[str, Any]] = []

        # Layer 1: System prompt — 由 adapter 自行注入　（codex 用 system message，claude 用 system 参数）
        # 这里不插入 system message，避免重复

        # Layer 2: Project context — pinned 作为 system 级指令
        for msg in self.project_context:
            messages.append({"role": "system", "content": msg["content"]})

        # Layer 3: Tool context
        messages.extend(self.tool_context)

        # Layer 4: Conversation history（排除已放入 project context 的 pinned 消息）
        pinned_ids = {id(m) for m in self.project_context}
        for msg in self.history:
            if id(msg) not in pinned_ids:
                messages.append({"role": msg["role"], "content": msg["content"]})

        logger.debug(
            "ContextManager built %d messages (%.0f tok est) for conv=%s strategy=%s",
            len(messages),
            self._estimate_layer_tokens(),
            self.conversation_id,
            self.strategy,
        )
        _cache_set(cache_key, messages)
        return messages

    # ------------------------------------------------------------------
    # Workspace 上下文注入
    # ------------------------------------------------------------------

    def inject_workspace_context(self, workspace_root: str) -> None:
        """将 workspace 文件树摘要注入 project_context 层，Agent 可据此了解文件结构。"""
        import os
        if not workspace_root or not os.path.isdir(workspace_root):
            return
        tree_text = _format_tree_for_agent(workspace_root, max_depth=2)
        if not tree_text:
            return
        self.project_context.append({
            "role": "system",
            "content": (
                "## Workspace 文件结构\n"
                f"根目录: {workspace_root}\n"
                "你可以使用 read_file / write_file / list_files 操作此目录下的文件。\n\n"
                f"```\n{tree_text}\n```"
            ),
            "pinned": False,
            "artifact_id": None,
            "sender_id": "system",
        })

    # ------------------------------------------------------------------
    # 调试辅助
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """返回上下文统计摘要，用于调试面板。"""
        return {
            "conversation_id": self.conversation_id,
            "model": self.model,
            "strategy": self.strategy,
            "max_tokens": self.max_tokens,
            "turns": self._total_turns,
            "total_chars": self._total_chars,
            "history_count": len(self.history),
            "total_loaded": self._total_loaded,
            "pinned_count": self._pinned_count,
            "tool_count": len(self.tool_context),
            "has_system_prompt": bool(self.system_prompt),
            "estimated_tokens": self._estimate_layer_tokens(),
        }
