"""HTML extraction, repair, preview generation, and LLM-driven preview assembly.

All the functions that turn agent text output into previewable artifacts.
"""

from __future__ import annotations

import asyncio
import html as _html_module
import json
import logging
import os
import re
import time
from typing import Any

from sqlalchemy import desc, select

from db.engine import get_sessionmaker
from db.models import Agent, ConversationMember
from db.models import Message as MessageModel
from db.models import new_id
from services.artifact import (
    create_artifact as create_service_artifact,
    read_artifact_content_with_session as read_service_artifact_content,
)
from ws import Connection, event

logger = logging.getLogger("agenthub.orchestrator.preview")

FRONTEND_PREVIEW_MAX_TOKENS = 24000
ORCHESTRATOR_AGENT_ID = "agent_orchestrator"


# ---------------------------------------------------------------------------
# HTML detection
# ---------------------------------------------------------------------------


def _is_complete_html_document(text: str) -> bool:
    lower = (text or "").lower()
    if "<!doctype html" not in lower and "<html" not in lower:
        return False
    if "<body" not in lower or "</body>" not in lower or "</html>" not in lower:
        return False
    if "<style" in lower and "</style>" not in lower:
        return False
    if "<script" in lower and "</script>" not in lower:
        return False
    return True


def _looks_like_html(text: str) -> bool:
    lower = (text or "").lower()
    if re.search(r"<([a-zA-Z][\w-]*)[^>]*>[\s\S]*?</\1>", text or ""):
        return True
    if "<!doctype html" in lower:
        return True
    if "<style" in lower or "<script" in lower:
        return True
    return False


# ---------------------------------------------------------------------------
# HTML extraction
# ---------------------------------------------------------------------------

HTML_BLOCK_RE = re.compile(r"```(?:html|HTML)?\s*\n([\s\S]*?)```", re.MULTILINE)


def _extract_html_from_text(text: str) -> str | None:
    from orchestrator.debug_hooks import _debug_event, _html_probe

    _debug_event("H2", "extract_input", _html_probe(text))
    for match in HTML_BLOCK_RE.finditer(text or ""):
        candidate = match.group(1).strip()
        _debug_event("H2", "extract_fence_candidate", _html_probe(candidate))
        if _is_complete_html_document(candidate):
            normalized = _normalize_html_document(candidate)
            _debug_event("H2", "extract_fence_complete", _html_probe(normalized))
            return normalized
        _debug_event("H2", "extract_fence_rejected_incomplete", _html_probe(candidate))

    lower = (text or "").lower()
    start_positions = [pos for pos in (lower.find("<!doctype html"), lower.find("<html")) if pos >= 0]
    if start_positions:
        start = min(start_positions)
        end = lower.rfind("</html>")
        _debug_event("H2", "extract_raw_bounds", {"start": start, "end": end, **_html_probe(text)})
        if end > start:
            candidate = text[start : end + len("</html>")]
            if _is_complete_html_document(candidate):
                normalized = _normalize_html_document(candidate.strip())
                _debug_event("H2", "extract_raw_complete", _html_probe(normalized))
                return normalized
        _debug_event("H2", "extract_raw_rejected_incomplete", _html_probe(text))
        return None

    if "```" not in (text or "") and _looks_like_html(text or ""):
        normalized = _normalize_html_document(text.strip())
        _debug_event("H2", "extract_fragment_wrapped", _html_probe(normalized))
        return normalized

    _debug_event("H2", "extract_none", _html_probe(text))
    return None


def _normalize_html_document(candidate: str) -> str:
    text = candidate.strip()
    if "<html" not in text.lower():
        text = f"<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"></head><body>{text}</body></html>"
    if not text.lower().lstrip().startswith("<!doctype html"):
        text = "<!doctype html>\n" + text
    return text


# ---------------------------------------------------------------------------
# HTML repair (partial / truncated output)
# ---------------------------------------------------------------------------


def _close_partial_html(text: str, user_text: str, reason: str) -> str:
    raw = text or ""
    lower = raw.lower()
    starts = [pos for pos in (lower.find("<!doctype html"), lower.find("<html")) if pos >= 0]
    if not starts:
        return _fallback_preview_html(user_text, reason)

    candidate = raw[min(starts):].strip()
    candidate = re.sub(r"```+\s*$", "", candidate).strip()
    lower = candidate.lower()

    if "<style" in lower and "</style>" not in lower:
        candidate += "\n</style>"
        lower = candidate.lower()
    if "<script" in lower and "</script>" not in lower:
        candidate += "\n</script>"
        lower = candidate.lower()
    if "<body" not in lower:
        candidate += (
            "\n</head><body><main style=\"min-height:100vh;display:grid;place-items:center;"
            "background:#050505;color:white;font-family:Arial,sans-serif;padding:24px;text-align:center\">"
            f"<section><h1>{_html_module.escape(_clean_requirement(user_text))}</h1>"
            f"<p>模型输出被截断，系统已保留可恢复的页面骨架。原因：{_html_module.escape(reason)}</p>"
            "</section></main>"
        )
        lower = candidate.lower()
    if "</body>" not in lower:
        candidate += "\n</body>"
        lower = candidate.lower()
    if "</html>" not in lower:
        candidate += "\n</html>"
    return _normalize_html_document(candidate)


# ---------------------------------------------------------------------------
# Fallback preview
# ---------------------------------------------------------------------------


def _clean_requirement(user_text: str) -> str:
    text = re.sub(r"@Orchestrator\b", "", user_text, flags=re.IGNORECASE).strip()
    return text or user_text.strip() or "HTML 页面"


def _is_im_chat_request(user_text: str) -> bool:
    lower = user_text.lower()
    return any(k in lower for k in ["微信", "wechat", "im", "聊天", "会话", "群聊", "单聊", "agent"])


def _html_title(html_text: str, fallback: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html_text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        title = re.sub(r"\s+", " ", match.group(1)).strip()
        if title:
            return title[:80]
    return fallback[:80] or "模型生成网页预览"


def _preview_message_content(artifact: dict[str, Any], original_text: str = "") -> dict[str, Any]:
    base: dict[str, Any] = {
        "type": "preview",
        "artifact_id": artifact["id"],
        "title": artifact["title"],
        "mimeType": artifact["mime_type"],
        "fileSize": artifact["file_size"],
        "url": artifact.get("url"),
        "previewUrl": artifact.get("preview_url"),
        "version": artifact.get("version", 1),
    }
    if original_text:
        base["text"] = original_text
    return base


def _should_create_w4_preview(user_text: str) -> bool:
    lower = user_text.lower()
    return any(k in lower for k in ["html", "网页", "页面", "web", "应用", "landing", "预览"])


def _is_frontend_preview_subtask(st: Any, user_text: str) -> bool:
    domain = str(getattr(st, "domain", "") or "").lower()
    title = str(getattr(st, "title", "") or "")
    description = str(getattr(st, "description", "") or "")
    haystack = f"{user_text}\n{title}\n{description}".lower()
    return domain == "frontend" and _should_create_w4_preview(haystack)


def _compact_frontend_prompt(agent_prompt: str) -> str:
    return (
        f"{agent_prompt}\n\n"
        "[Frontend output contract]\n"
        "Return exactly one complete single-file HTML document.\n"
        "Start with <!doctype html> and end with </html>.\n"
        "Do not include markdown fences, explanation, install steps, or backend code.\n"
        "Keep it concise: one screen-focused demo, compact CSS, inline JS only if necessary.\n"
        "Use placeholder gradients/blocks instead of long asset URLs. Target under 450 lines.\n"
    )


def _fallback_preview_html(user_text: str, reason: str) -> str:
    requirement = _html_module.escape(_clean_requirement(user_text))
    reason_html = _html_module.escape(reason)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>预览生成需要模型输出</title>
  <style>
    body {{ margin:0; min-height:100vh; display:grid; place-items:center; background:#101828; color:#f8fafc; font-family:'Microsoft YaHei',system-ui,sans-serif; }}
    main {{ max-width:760px; padding:32px; }}
    h1 {{ margin:0 0 16px; font-size:34px; }}
    p {{ color:#cbd5e1; line-height:1.8; }}
    code {{ color:#93c5fd; }}
  </style>
</head>
<body>
  <main>
    <h1>没有拿到可预览 HTML</h1>
    <p>Orchestrator 已完成分派，但模型没有返回完整 HTML 文档，或当前会话没有可调用的模型 Agent。</p>
    <p><strong>原始需求：</strong>{requirement}</p>
    <p><strong>原因：</strong><code>{reason_html}</code></p>
  </main>
</body>
</html>"""


def _visible_generation_error(code: str, message: str) -> str:
    if code == "output_truncated":
        return (
            "\n\n---\n"
            "[提示] 输出达到模型长度上限，当前内容可能不完整。"
            "请发送「继续生成」，或提高该 Agent 的 max_tokens 后重新生成。"
        )
    clean = message.strip() or code
    return f"\n\n---\n[提示] 生成中断：{clean}"


# ---------------------------------------------------------------------------
# LLM-driven preview assembly
# ---------------------------------------------------------------------------


async def _collect_subtask_outputs(
    s: Any,
    subtask_messages: dict[str, str],
) -> dict[str, str]:
    if not subtask_messages:
        return {}
    rows = (
        await s.scalars(
            select(MessageModel).where(MessageModel.id.in_(list(subtask_messages.values())))
        )
    ).all()
    outputs: dict[str, str] = {}
    for row in rows:
        try:
            raw = json.loads(row.content) if row.content else {}
        except (TypeError, ValueError):
            raw = {}
        text = raw.get("text", "") if isinstance(raw, dict) else ""
        artifact_id = row.artifact_id
        if not artifact_id and isinstance(raw, dict):
            candidate = raw.get("artifact_id")
            artifact_id = candidate if isinstance(candidate, str) else None
        if artifact_id:
            artifact_text = await read_service_artifact_content(s, artifact_id)
            if artifact_text and artifact_text.strip():
                text = artifact_text
        if isinstance(text, str) and text.strip():
            outputs[row.id] = text
    return outputs


def _build_preview_prompt(
    *,
    user_text: str,
    conversation_history: list[dict[str, Any]],
    subtask_records: list[tuple[Any, str, str, str, list[str]]],
    subtask_outputs: dict[str, str],
) -> list[dict[str, str]]:
    recent_context = "\n".join(
        f"{msg['role']}: {msg['content'][:500]}" for msg in conversation_history[-8:]
    )
    assignments = "\n".join(
        f"- {agent_name} / {st.domain or 'general'}: {st.title}"
        for st, agent_name, _agent_id, _input_summary, _deps in subtask_records
    )
    outputs = []
    for st, agent_name, _agent_id, _input_summary, _deps in subtask_records:
        text = subtask_outputs.get(st.id, "")
        if not text:
            continue
        outputs.append(f"## {agent_name} / {st.domain}\n{text[:4000]}")
    outputs_text = "\n\n".join(outputs) or "No usable subtask text was returned."

    system_prompt = (
        "你是一个资深前端设计与实现 Agent。根据用户每一次不同的需求，"
        "动态生成完全不同的、可直接预览的单文件 HTML。"
        "不要使用固定模板，不要输出 AgentHub 交付页，不要只写方案。"
        "必须只返回完整 HTML 文档，不要 Markdown 代码围栏。"
        "CSS 和必要 JavaScript 必须内联，不能依赖外部资源。"
    )
    user_prompt = f"""请把下面的用户需求和多 Agent 分工结果聚合成最终可运行 HTML 预览。

原始用户需求：
{user_text}

近期聊天上下文：
{recent_context or "无"}

Orchestrator 分工：
{assignments or "无"}

各 Agent 产出摘要：
{outputs_text}

生成要求：
1. 页面必须直接体现用户的具体需求，而不是通用交付说明。
2. 视觉风格、内容结构、文案、交互都要按本次需求重新设计。
3. 如果用户要求模仿某类产品，只学习信息架构和交互风格，不复制商标或真实品牌素材。
4. 输出必须是完整 HTML，从 <!doctype html> 或 <html> 开始，到 </html> 结束。
"""
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


async def _pick_preview_generator_agent(
    s: Any,
    *,
    conversation_id: str,
    subtask_records: list[tuple[Any, str, str, str, list[str]]],
) -> tuple[str, str, str] | None:
    member_ids = (
        await s.scalars(
            select(ConversationMember.member_id).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.member_type == "agent",
                ConversationMember.member_id != ORCHESTRATOR_AGENT_ID,
            )
        )
    ).all()
    query = select(Agent).where(Agent.id != ORCHESTRATOR_AGENT_ID)
    if member_ids:
        query = query.where(Agent.id.in_(list(member_ids)))
    agents = (await s.scalars(query)).all()
    if not agents:
        return None

    subtask_agent_ids = {agent_id for st, _name, agent_id, _input, _deps in subtask_records if st.domain == "frontend"}

    def _can_generate(agent: Agent) -> bool:
        try:
            cfg = json.loads(agent.config) if agent.config else {}
        except (TypeError, ValueError):
            cfg = {}
        if agent.adapter_type == "codex" and os.environ.get("OPENAI_API_KEY"):
            return True
        if bool(cfg.get("api_key")):
            return True
        if agent.adapter_type not in ("mock", "") and bool(cfg.get("model")):
            return True
        return False

    candidates = [a for a in agents if _can_generate(a)]
    if not candidates:
        return None

    def score(agent: Agent) -> tuple[int, int]:
        try:
            cfg = json.loads(agent.config) if agent.config else {}
        except (TypeError, ValueError):
            cfg = {}
        prompt_text = str(cfg.get("system_prompt", "") or "").lower()
        searchable = " ".join([agent.name or "", agent.adapter_type or "", prompt_text]).lower()
        value = 0
        if agent.id in subtask_agent_ids:
            value += 35
        if any(term in searchable for term in ("frontend", "html", "ui", "react", "web", "preview")):
            value += 25
        if any(term in searchable for term in ("code", "tool_use")):
            value += 10
        return value, int(agent.created_at or 0)

    best = max(candidates, key=score)
    if score(best)[0] <= 0:
        return None
    reason = f"capability_score:{score(best)[0]}"
    return best.id, best.name, reason


async def _generate_preview_html_with_model(
    *,
    conversation_id: str,
    user_text: str,
    conversation_history: list[dict[str, Any]],
    subtask_records: list[tuple[Any, str, str, str, list[str]]],
    subtask_messages: dict[str, str],
) -> tuple[str, str, str]:
    from orchestrator.im_prototype import _im_chat_preview_html

    if _is_im_chat_request(user_text):
        html_doc = _im_chat_preview_html(user_text)
        return html_doc, _html_title(html_doc, "Agent IM · 聊天式协作原型"), "agenthub_im_template"

    Session = get_sessionmaker()
    async with Session() as s:
        message_outputs = await _collect_subtask_outputs(s, subtask_messages)
        task_outputs = {
            subtask_id: message_outputs.get(message_id, "")
            for subtask_id, message_id in subtask_messages.items()
        }

        for text in task_outputs.values():
            html_doc = _extract_html_from_text(text)
            if html_doc:
                return html_doc, _html_title(html_doc, _clean_requirement(user_text)), "frontend_subtask_html"

        picked = await _pick_preview_generator_agent(
            s,
            conversation_id=conversation_id,
            subtask_records=subtask_records,
        )

    if picked is None:
        html_doc = _fallback_preview_html(user_text, "no_model_agent_available")
        return html_doc, _html_title(html_doc, "预览生成需要模型输出"), "fallback"

    agent_id, agent_name, reason = picked
    from handlers.agent_ops import load_adapter_for

    loaded = await load_adapter_for(agent_id)
    if loaded is None:
        html_doc = _fallback_preview_html(user_text, f"adapter_init_failed:{agent_id}")
        return html_doc, _html_title(html_doc, "预览生成需要模型输出"), "fallback"

    adapter, _display_name = loaded
    if hasattr(adapter, "max_tokens"):
        try:
            adapter.max_tokens = max(int(getattr(adapter, "max_tokens", 0)), 12000)
        except (TypeError, ValueError):
            adapter.max_tokens = 12000
    messages = _build_preview_prompt(
        user_text=user_text,
        conversation_history=conversation_history,
        subtask_records=subtask_records,
        subtask_outputs=task_outputs,
    )

    final_parts: list[str] = []
    errors: list[str] = []
    async for chunk in adapter.send(messages=messages, stream=False):
        ctype = chunk.get("type")
        if ctype == "text":
            final_parts.append(str(chunk.get("delta", "")))
        elif ctype == "error":
            errors.append(f"{chunk.get('code', 'adapter_error')}: {chunk.get('message', '')}")
            break

    final_text = "".join(final_parts)
    html_doc = _extract_html_from_text(final_text)
    if html_doc:
        return html_doc, _html_title(html_doc, _clean_requirement(user_text)), f"{reason}:{agent_name}"

    if errors:
        fallback_reason = "; ".join(errors)
    else:
        fallback_reason = f"model_returned_no_complete_html:{agent_name}"
    html_doc = _fallback_preview_html(user_text, fallback_reason)
    return html_doc, _html_title(html_doc, "预览生成需要模型输出"), "fallback"
