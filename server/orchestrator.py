"""Orchestrator for @Orchestrator multi-agent collaboration (F-W3-2).

Complete pipeline:
1. Emit ``planning`` status immediately (within 3s)
2. Load conversation history + pinned messages for context
3. Run complexity analysis and task decomposition
4. Create parent + subtask records in DB with ``depends_on[]`` / ``input_summary``
5. Fan-out: dispatch each subtask to its agent via normal message flow
6. Track progress: emit ``task_update`` on each status change
7. Summary: when all subtasks done, send a summary text message
8. Error handling: retry-once, blocked fallback, conflict detection
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from urllib import request
from typing import Any, Optional

from sqlalchemy import desc, select

from db.engine import get_sessionmaker
from db.models import Agent, Conversation, ConversationMember
from db.models import Message as MessageModel
from db.models import new_id
from services import create_message as create_service_message
from services import message_to_dict, update_message_content
from services.artifact import (
    create_artifact as create_service_artifact,
    read_artifact_content_with_session as read_service_artifact_content,
)
from services.animation_bus import animation_bus
from services.react_loop import ReActEngine
from services.task import (
    create_task,
    get_task,
    list_subtasks,
    task_to_dict,
    update_task_status,
)
from services.tool_registry import get_tool_registry
from ws import Connection, event

_SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if _SRC_DIR not in sys.path:
    sys.path.append(_SRC_DIR)

from scheduler.complexity import ComplexityJudge, TaskInput
from scheduler.enhanced_decomposer import EnhancedTaskDecomposer

from dag_engine import DAG, DAGNode, DAGExecutor

logger = logging.getLogger("agenthub.orchestrator")

ORCHESTRATOR_AGENT_ID = "agent_orchestrator"

AGENT_CODE_MAP: dict[str, str] = {
    "A": "agent_mock",
    "B": "agent_mock_2",
    "C": "agent_claude",
    "D": "agent_deepseek",
}

RETRY_LIMIT = 1
HTML_BLOCK_RE = re.compile(r"```(?:html|HTML)?\s*\n([\s\S]*?)```", re.MULTILINE)
DEBUG_ENV_PATH = Path(__file__).resolve().parent.parent / ".dbg" / "html-preview-truncation.env"
FRONTEND_PREVIEW_MAX_TOKENS = 24000


def _is_login_collaboration_demo(user_text: str) -> bool:
    text = _clean_requirement(user_text).lower()
    required = ("login" in text or "\u767b\u5f55" in text) and ("page" in text or "\u9875\u9762" in text or "\u9875" in text)
    collaboration_terms = [
        "frontend", "backend", "api", "database", "test",
        "\u524d\u7aef", "\u540e\u7aef", "\u63a5\u53e3", "\u6570\u636e\u5e93", "\u6d4b\u8bd5",
    ]
    return required and sum(1 for term in collaboration_terms if term in text) >= 3


def _login_collaboration_demo_subtasks(user_text: str) -> list[Any]:
    requirement = _clean_requirement(user_text)
    specs = [
        (
            "demo_frontend_login",
            "frontend",
            "Frontend Agent: generate login page code and preview",
            "Build the login page UI. Return previewable HTML/CSS/JavaScript or a React structure with account, password, submit button, error state, loading state, and responsive layout.",
        ),
        (
            "demo_backend_login",
            "backend",
            "Backend Agent: design the login API",
            "Design POST /api/login. Return request fields, response shape, error codes, authentication flow, password verification, and token/session handling suggestions.",
        ),
        (
            "demo_database_login",
            "database",
            "Database Agent: design the user table schema",
            "Design the users table for login. Return columns, types, unique constraints, indexes, password hash fields, audit fields, and ORM/SQL examples.",
        ),
        (
            "demo_test_login",
            "test",
            "Test & Docs Agent: generate test cases and acceptance checklist",
            "Generate login feature tests covering successful login, wrong password, missing account, empty fields, API failures, rate limiting, security boundaries, and acceptance criteria.",
        ),
    ]
    return [
        type("_", (), {
            "id": task_id,
            "description": f"{title}\n\nOriginal requirement: {requirement}\n\n{subtask_desc}",
            "domain": domain,
            "dependencies": [],
        })()
        for task_id, domain, title, subtask_desc in specs
    ]


def _debug_event(hypothesis_id: str, point: str, payload: dict[str, Any]) -> None:
    #region debug-point html-preview-truncation
    try:
        if not DEBUG_ENV_PATH.exists():
            return
        env = dict(
            line.split("=", 1)
            for line in DEBUG_ENV_PATH.read_text(encoding="utf-8").splitlines()
            if "=" in line
        )
        url = env.get("DEBUG_SERVER_URL")
        if not url:
            return
        body = json.dumps({
            "sessionId": env.get("DEBUG_SESSION_ID", "html-preview-truncation"),
            "runId": "pre",
            "hypothesisId": hypothesis_id,
            "point": point,
            "payload": payload,
            "ts": int(time.time() * 1000),
        }, ensure_ascii=False).encode("utf-8")
        req = request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        request.urlopen(req, timeout=0.2).close()
    except Exception:
        pass
    #endregion debug-point html-preview-truncation


def _html_probe(text: str | None) -> dict[str, Any]:
    #region debug-point html-preview-truncation
    value = text or ""
    lower = value.lower()
    return {
        "length": len(value),
        "starts_with_doctype": lower.lstrip().startswith("<!doctype html"),
        "doctype_pos": lower.find("<!doctype html"),
        "html_pos": lower.find("<html"),
        "closing_html_pos": lower.rfind("</html>"),
        "has_fence": "```" in value,
        "complete_html": _is_complete_html_document(value),
        "looks_like_html": _looks_like_html(value),
        "head": value[:180],
        "tail": value[-180:],
    }
    #endregion debug-point html-preview-truncation


def _visible_generation_error(code: str, message: str) -> str:
    if code == "output_truncated":
        return (
            "\n\n---\n"
            "[Notice] Output reached the model length limit and may be incomplete. "
            "Send 'continue' or increase this Agent's max_tokens before regenerating."
        )
    clean = message.strip() or code
    return f"\n\n---\n[Notice] Generation stopped: {clean}"


def _agent_code_to_display_name(code: str) -> str:
    AGENT_DISPLAY_NAMES = {
        "A": "MockAdapter (frontend)",
        "B": "CustomAgentAdapter",
        "C": "ClaudeCodeAdapter",
        "D": "CodexAdapter",
    }
    return AGENT_DISPLAY_NAMES.get(code, code)


def _agent_code_to_agent_id(code: str) -> str:
    return AGENT_CODE_MAP.get(code, "agent_mock")


def _agent_capability_score(agent: Agent, domain: str) -> int:
    name_text = (agent.name or "").lower()
    adapter_text = (agent.adapter_type or "").lower()

    # Primary signal: Role prompt (system_prompt)
    try:
        cfg = json.loads(agent.config) if agent.config else {}
    except (TypeError, ValueError):
        cfg = {}
    prompt_text = str(cfg.get("system_prompt", "") or "").lower()

    score = 0

    # Mock adapters should never be chosen for real work when LLM agents exist
    if adapter_text == "mock":
        score -= 999

    domain_aliases = {
        "frontend": ["frontend", "ui", "html", "css", "react", "preview", "component", "vue"],
        "backend": ["backend", "api", "server", "service", "python", "routing"],
        "database": ["database", "db", "sql", "orm", "schema", "query", "migration"],
        "test": ["test", "testing", "qa", "verify", "quality", "acceptance"],
        "docs": ["docs", "doc", "readme", "writer"],
        "devops": ["devops", "ci", "deploy", "ops", "docker"],
    }

    # Role prompt is the primary signal
    if domain.lower() in prompt_text:
        score += 30
    score += sum(5 for alias in domain_aliases.get(domain, []) if alias in prompt_text)

    # Agent name is a secondary signal
    if domain.lower() in name_text:
        score += 8
    score += sum(1 for alias in domain_aliases.get(domain, []) if alias in name_text)

    # Adapter type gives a small generalist baseline
    if adapter_text in ("claude_code", "anthropic", "codex", "openai", "deepseek", "opencode"):
        score += 1

    # API key: agent must be functional, but does NOT bias domain selection
    try:
        cfg = json.loads(agent.config) if agent.config else {}
    except (TypeError, ValueError):
        cfg = {}
    has_api_key = bool(cfg.get("api_key")) or (adapter_text == "codex" and os.environ.get("OPENAI_API_KEY"))
    if has_api_key:
        score += 5  # Small tiebreaker, not a dominating factor

    return score


async def _pick_agent_for_domain(
    s: Any,
    *,
    domain: str,
    conversation_id: str,
) -> tuple[str, str]:
    """Pick the best available conversation member for a domain.

    Custom agents created by the user participate naturally because the score
    is based on the persisted capability tags/name/adapter type.
    """
    member_ids = (
        await s.scalars(
            select(ConversationMember.member_id).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.member_type == "agent",
                ConversationMember.member_id != ORCHESTRATOR_AGENT_ID,
            )
        )
    ).all()
    candidates: list[Agent] = []
    if member_ids:
        candidates = (
            await s.scalars(select(Agent).where(Agent.id.in_(list(member_ids))))
        ).all()
    if not candidates:
        candidates = (
            await s.scalars(
                select(Agent).where(Agent.id != ORCHESTRATOR_AGENT_ID)
            )
        ).all()

    if not candidates:
        fallback_code = {
            "frontend": "A",
            "backend": "B",
            "database": "C",
            "test": "D",
            "docs": "D",
            "devops": "D",
        }.get(domain, "B")
        return _agent_code_to_agent_id(fallback_code), _agent_code_to_display_name(fallback_code)

    best = max(
        candidates,
        key=lambda agent: (
            _agent_capability_score(agent, domain),
            agent.created_at or 0,
        ),
    )

    return best.id, best.name


def _conflict_resolution_note(subtask_records: list[tuple[Any, str, str, str, list[str]]]) -> str:
    by_domain: dict[str, list[str]] = {}
    for st, _agent_name, _agent_id, _input_summary, _deps in subtask_records:
        if st.domain:
            by_domain.setdefault(st.domain, []).append(st.title[:60])
    overlaps = {domain: titles for domain, titles in by_domain.items() if len(titles) > 1}
    if not overlaps:
        return "Conflict resolution: no overlapping domain writes detected; artifacts can be merged directly."
    parts = []
    for domain, titles in sorted(overlaps.items()):
        parts.append(f"{domain}: {len(titles)} competing outputs kept as separate review items")
    return "Conflict resolution: " + "; ".join(parts) + "."


def _clean_requirement(user_text: str) -> str:
    text = re.sub(r"@Orchestrator\b", "", user_text, flags=re.IGNORECASE).strip()
    return text or user_text.strip() or "HTML 椤甸潰"


def _is_im_chat_request(user_text: str) -> bool:
    lower = user_text.lower()
    return any(k in lower for k in [
        "qq", "wechat", "im", "chat", "message", "friend", "group",
        "聊天", "单聊", "群聊", "即时通讯", "好友", "消息", "会话", "联系人", "agent",
    ])


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
    """Check if text appears to be an HTML document (not just containing incidental tags)."""
    lower = (text or "").lower()
    # Must have a clear document-level HTML element
    if "<!doctype html" in lower:
        return True
    if "<html" in lower or "</html>" in lower:
        return True
    if "<head" in lower or "<body" in lower:
        return True
    # Has paired tags AND is substantial enough to be a document (> 200 chars)
    if len(text or "") > 200 and re.search(r"<([a-zA-Z][\w-]*)[^>]*>[\s\S]*?</\1>", text or ""):
        return True
    return False


def _extract_html_from_text(text: str) -> str | None:
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
        # Only wrap as HTML document if it already has document-level structure
        if "<html" in lower or "<!doctype html" in lower:
            normalized = _normalize_html_document(text.strip())
            _debug_event("H2", "extract_fragment_wrapped", _html_probe(normalized))
            return normalized
        _debug_event("H2", "extract_fragment_no_doc_structure", _html_probe(text))
        return None

    _debug_event("H2", "extract_none", _html_probe(text))
    return None


def _normalize_html_document(candidate: str) -> str:
    text = candidate.strip()
    if "<html" not in text.lower():
        text = f"<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"></head><body>{text}</body></html>"
    if not text.lower().lstrip().startswith("<!doctype html"):
        text = "<!doctype html>\n" + text
    return text


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
            f"<section><h1>{html.escape(_clean_requirement(user_text))}</h1>"
            f"<p>模型输出被截断，系统已保留可恢复的页面骨架。原因：{html.escape(reason)}</p>"
            "</section></main>"
        )
        lower = candidate.lower()
    if "</body>" not in lower:
        candidate += "\n</body>"
        lower = candidate.lower()
    if "</html>" not in lower:
        candidate += "\n</html>"
    return _normalize_html_document(candidate)


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
    # Preserve original text so downstream _collect_subtask_outputs
    # can extract HTML without needing to read the artifact file.
    if original_text:
        base["text"] = original_text
    return base


def _im_chat_preview_html(user_text: str) -> str:
    requirement = html.escape(_clean_requirement(user_text))
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>AgentHub IM 协作原型</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; min-height: 100vh; background: #eef2f7; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Microsoft YaHei', sans-serif; color: #111827; }}
    .app {{ width: min(1200px, calc(100vw - 32px)); height: min(760px, calc(100vh - 32px)); margin: 16px auto; display: grid; grid-template-columns: 260px 1fr 240px; border: 1px solid #d7dde8; border-radius: 18px; overflow: hidden; background: white; box-shadow: 0 24px 80px rgba(15, 23, 42, .16); }}
    aside {{ background: #f8fafc; border-right: 1px solid #e5e7eb; padding: 18px; }}
    aside.right {{ border-right: 0; border-left: 1px solid #e5e7eb; }}
    h1, h2, h3, p {{ margin: 0; }}
    .brand {{ font-weight: 800; font-size: 18px; }}
    .muted {{ color: #64748b; font-size: 12px; }}
    .conv {{ margin-top: 16px; padding: 12px; border-radius: 12px; background: #e0f2fe; border: 1px solid #bae6fd; }}
    main {{ display: flex; flex-direction: column; min-width: 0; }}
    header {{ padding: 18px 22px; border-bottom: 1px solid #e5e7eb; }}
    .messages {{ flex: 1; padding: 22px; overflow: auto; background: linear-gradient(#ffffff, #f8fafc); }}
    .msg {{ max-width: 72%; margin: 14px 0; padding: 12px 14px; border-radius: 16px; line-height: 1.7; font-size: 14px; }}
    .agent {{ background: #f1f5f9; border-top-left-radius: 4px; }}
    .user {{ margin-left: auto; background: #2563eb; color: white; border-bottom-right-radius: 4px; }}
    .card {{ margin-top: 10px; border: 1px solid #dbe3ef; border-radius: 12px; padding: 12px; background: white; }}
    .composer {{ padding: 14px; border-top: 1px solid #e5e7eb; display: flex; gap: 10px; }}
    textarea {{ flex: 1; resize: none; border: 1px solid #d1d5db; border-radius: 12px; padding: 10px 12px; }}
    button {{ border: 0; border-radius: 12px; background: #16a34a; color: white; padding: 0 18px; font-weight: 700; }}
  </style>
</head>
<body>
  <section class="app">
    <aside>
      <div class="brand">AgentHub</div>
      <p class="muted">多 Agent 协作 · 预览模式</p>
      <div class="conv"><strong>Orchestrator 缇よ亰</strong><p class="muted">Frontend / Backend / Database / Test</p></div>
    </aside>
    <main>
      <header><h2>Orchestrator 群聊</h2><p class="muted">需求：{requirement}</p></header>
      <div class="messages">
        <div class="msg user">@Orchestrator 璇峰府鎴戝疄鐜拌繖涓渶姹?/div>
        <div class="msg agent">Orchestrator 已理解需求，正在拆解并分派给合适的 Agent</div>
        <div class="msg agent">Frontend Agent 已生成前端页面，预览如下：<div class="card">页面渲染中 · 右侧点击全屏查看</div></div>
        <div class="msg agent">Review Agent 浠ｇ爜瀹℃煡閫氳繃锛孌iff 宸插簲鐢?/div>
      </div>
      <div class="composer"><textarea>@Frontend 再优化一下样式</textarea><button>发送</button></div>
    </main>
    <aside class="right">
      <h3>涓婁笅鏂?/h3>
      <p class="muted">已固定消息会自动注入到每次 Agent 调用中。</p>
    </aside>
  </section>
</body>
</html>"""

def _fallback_preview_html(user_text: str, reason: str) -> str:
    requirement = html.escape(_clean_requirement(user_text))
    reason_html = html.escape(reason)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>AgentHub 预览生成</title>
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
    <h1>预览暂不可用</h1>
    <p>Orchestrator 宸插畬鎴愪换鍔″垎瑙ｏ紝浣嗘湭杩斿洖瀹屾暣 HTML 鏂囨。锛屾垨褰撳墠浼氳瘽娌℃湁鍙敤鐨勫墠绔?Agent銆備綘浠嶅彲浠ュ湪缂栬緫鍣ㄦ煡鐪嬪拰淇敼婧愮爜銆?/p>
    <p><strong>原始需求：</strong>{requirement}</p>
    <p><strong>鍘熷洜锛?/strong><code>{reason_html}</code></p>
  </main>
</body>
</html>"""

def _should_create_w4_preview(user_text: str) -> bool:
    lower = user_text.lower()
    return any(k in lower for k in ["html", "web", "app", "landing", "preview", "\u7f51\u9875", "\u9875\u9762", "\u5e94\u7528", "\u9884\u89c8"])


def _ensure_preview_collaboration_domains(user_text: str, domains: set[str]) -> set[str]:
    expanded = set(domains)
    lower = user_text.lower()

    # Simple HTML/page requests keep the collaboration focused on frontend.
    simple_html_keywords = [
        r"generate.*html",
        r"write.*html",
        r"create.*page",
        r"html.*page",
        r"\u751f\u6210.*html",
        r"\u5199.*html",
        r"\u521b\u5efa.*\u9875\u9762",
        r"\u505a.*\u9875\u9762",
    ]
    is_simple_html = any(re.search(k, lower) for k in simple_html_keywords)
    if is_simple_html:
        expanded.add("frontend")
        return expanded

    if not _should_create_w4_preview(user_text):
        return domains or {"frontend"}

    expanded.add("frontend")
    if any(k in lower for k in ["login", "register", "order", "product", "api", "app", "\u767b\u5f55", "\u6ce8\u518c", "\u8ba2\u5355", "\u5546\u54c1", "\u63a5\u53e3", "\u5e94\u7528"]):
        expanded.update({"backend", "database"})
    return expanded


def _build_subtask_description(subtask: Any, decompose_result: Any) -> str:
    # Keep the decomposer-provided task details intact for agent assignment.
    return subtask.description or ""


def _agent_config(agent: Agent) -> dict[str, Any]:
    try:
        return json.loads(agent.config) if agent.config else {}
    except (TypeError, ValueError):
        return {}


def _agent_can_call_model(agent: Agent) -> bool:
    cfg = _agent_config(agent)
    if cfg.get("api_key"):
        return True
    if agent.adapter_type == "codex" and os.environ.get("OPENAI_API_KEY"):
        return True
    return False


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

    # Filter out agents that cannot actually call a real LLM
    # (mock adapter has no API key and returns canned text, not real HTML)
    def _can_generate(agent: Agent) -> bool:
        try:
            cfg = json.loads(agent.config) if agent.config else {}
        except (TypeError, ValueError):
            cfg = {}
        # Codex adapter uses OPENAI_API_KEY env var
        if agent.adapter_type == "codex" and os.environ.get("OPENAI_API_KEY"):
            return True
        # Must have api_key configured
        if bool(cfg.get("api_key")):
            return True
        # Non-mock adapters with a model set are worth trying
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
    workspace_files: dict[str, str] | None = None,
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

    # Include workspace file contents as additional context
    workspace_text = ""
    if workspace_files:
        wf_parts = []
        for fname, fcontent in workspace_files.items():
            wf_parts.append(f"### File: {fname}\n```\n{fcontent[:6000]}\n```")
        workspace_text = "\n\n---\n\n**Workspace files written by agents:**\n\n" + "\n\n".join(wf_parts)

    system_prompt = (
        "You are a senior frontend design and implementation agent. "
        "Generate a complete, previewable single-file HTML document that directly "
        "satisfies the user request. Return ONLY complete HTML starting with "
        "<!doctype html> and ending with </html>. Use inline CSS for styling "
        "and vanilla JavaScript for interaction when needed. "
        "Make the page polished, responsive, and production-quality. "
        "Do NOT output markdown, explanations, or code fences; pure HTML only."
    )
    user_prompt = f"""Convert the user request and multi-agent outputs into a runnable HTML preview.

Original user request:
{user_text}

Recent chat context:
{recent_context or "None"}

Orchestrator assignments:
{assignments or "None"}

Agent output summaries:
{outputs_text}
{workspace_text}

Requirements:
1. The page must directly satisfy the specific user request above.
2. Design layout, copy, visual style, and interaction specifically for this request.
3. If referencing another product's UI, adopt structure/interaction patterns only.
4. Output complete HTML starting with <!doctype html> or <html> and ending with </html>.
5. Make the page fully self-contained with inline CSS and JS; no external dependencies.
6. Return raw HTML only; no markdown wrappers, no explanations, no code blocks."""
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


async def _scan_workspace_for_html(conversation_id: str) -> str | None:
    """Scan workspace directory for any .html files written by agents."""
    try:
        workspace_dir = Path(__file__).resolve().parents[1] / "workspaces" / conversation_id
        if not workspace_dir.is_dir():
            return None
        for f in sorted(workspace_dir.rglob("*.html")):
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                if _is_complete_html_document(content):
                    return content
                if _looks_like_html(content):
                    return _close_partial_html(content, f"Workspace file: {f.name}", "workspace_partial")
            except Exception:
                continue
    except Exception:
        pass
    return None


async def _read_workspace_files_for_preview(conversation_id: str) -> dict[str, str]:
    """Read key workspace files to enrich the preview generation prompt."""
    result: dict[str, str] = {}
    try:
        workspace_dir = Path(__file__).resolve().parents[1] / "workspaces" / conversation_id
        if not workspace_dir.is_dir():
            return result
        for f in sorted(workspace_dir.rglob("*")):
            if f.is_file() and f.suffix in (".md", ".html", ".json", ".txt", ".css", ".js", ".py"):
                try:
                    content = f.read_text(encoding="utf-8", errors="replace")
                    if len(content) > 50:
                        rel = str(f.relative_to(workspace_dir))
                        result[rel] = content[:8000]  # cap per file
                except Exception:
                    continue
    except Exception:
        pass
    return result


def _build_content_preview(
    user_text: str,
    task_outputs: dict[str, str],
    subtask_records: list[tuple[Any, str, str, str, list[str]]],
) -> str | None:
    """Build a simple HTML page from available agent text outputs when
    the model-based preview generation is unavailable.

    Returns None if there is no content worth showing.
    """
    requirement = html.escape(_clean_requirement(user_text))
    sections: list[str] = []

    for st, agent_name, _agent_id, _input_summary, _deps in subtask_records:
        text = ""
        for subtask_id, output_text in task_outputs.items():
            if subtask_id == st.id:
                text = output_text
                break
        if not text or len(text.strip()) < 10:
            continue

        escaped = html.escape(text[:6000])
        # Convert markdown-style code fences to <pre> blocks for basic rendering
        escaped = re.sub(
            r"```(\w*)\n([\s\S]*?)```",
            lambda m: f'<pre style="background:#1e293b;color:#e2e8f0;padding:12px;border-radius:8px;overflow-x:auto;font-size:13px;margin:8px 0;"><code>{html.escape(m.group(2))}</code></pre>',
            escaped,
        )
        # Basic markdown: headers, bold, line breaks
        escaped = re.sub(r"^### (.+)$", r"<h4>\1</h4>", escaped, flags=re.MULTILINE)
        escaped = re.sub(r"^## (.+)$", r"<h3>\1</h3>", escaped, flags=re.MULTILINE)
        escaped = re.sub(r"^# (.+)$", r"<h2>\1</h2>", escaped, flags=re.MULTILINE)
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        escaped = re.sub(r"\n\n", "<br><br>", escaped)
        escaped = re.sub(r"\n", "<br>", escaped)

        sections.append(
            f'<section style="margin-bottom:24px;">'
            f'<h2 style="color:#e2e8f0;font-size:16px;margin:0 0 8px;">{html.escape(agent_name)} / {html.escape(st.domain or "general")}</h2>'
            f'<div style="background:#0f172a;border:1px solid #334155;border-radius:12px;padding:16px;color:#cbd5e1;font-size:14px;line-height:1.8;">{escaped}</div>'
            f"</section>"
        )

    if not sections:
        return None

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{requirement}</title>
  <style>
    * {{ box-sizing:border-box; }}
    body {{ margin:0; min-height:100vh; background:#0f172a; color:#e2e8f0; font-family:-apple-system,BlinkMacSystemFont,'Microsoft YaHei',sans-serif; }}
    .container {{ max-width:960px; margin:0 auto; padding:32px 24px; }}
    h1 {{ font-size:24px; margin:0 0 8px; }}
    .subtitle {{ color:#64748b; font-size:14px; margin:0 0 32px; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>{requirement}</h1>
    <p class="subtitle">Orchestrator 多 Agent 协作产出汇总</p>
    {"".join(sections)}
  </div>
</body>
</html>"""


async def _generate_preview_html_with_model(
    *,
    conversation_id: str,
    user_text: str,
    conversation_history: list[dict[str, Any]],
    subtask_records: list[tuple[Any, str, str, str, list[str]]],
    subtask_messages: dict[str, str],
) -> tuple[str, str, str]:
    Session = get_sessionmaker()
    async with Session() as s:
        message_outputs = await _collect_subtask_outputs(s, subtask_messages)
        task_outputs = {
            subtask_id: message_outputs.get(message_id, "")
            for subtask_id, message_id in subtask_messages.items()
        }

        # Scan task outputs for HTML
        for text in task_outputs.values():
            html_doc = _extract_html_from_text(text)
            if html_doc:
                return html_doc, _html_title(html_doc, _clean_requirement(user_text)), "frontend_subtask_html"

        # Also scan workspace files written by agents (e.g. write_file tool)
        workspace_html = await _scan_workspace_for_html(conversation_id)
        if workspace_html:
            return workspace_html, _html_title(workspace_html, _clean_requirement(user_text)), "workspace_file"

        picked = await _pick_preview_generator_agent(
            s,
            conversation_id=conversation_id,
            subtask_records=subtask_records,
        )

    if picked is None:
        raise RuntimeError("No configured LLM agent is available to generate the preview HTML")

    agent_id, agent_name, reason = picked
    from handlers.send_message import load_adapter_for

    loaded = await load_adapter_for(agent_id)
    if loaded is None:
        raise RuntimeError(f"LLM adapter could not be initialized: {agent_id}")

    adapter, _display_name = loaded
    if hasattr(adapter, "max_tokens"):
        try:
            adapter.max_tokens = max(int(getattr(adapter, "max_tokens", 0)), 12000)
        except (TypeError, ValueError):
            adapter.max_tokens = 12000

    # Enrich prompt with workspace file contents when available
    workspace_file_contents = await _read_workspace_files_for_preview(conversation_id)
    messages = _build_preview_prompt(
        user_text=user_text,
        conversation_history=conversation_history,
        subtask_records=subtask_records,
        subtask_outputs=task_outputs,
        workspace_files=workspace_file_contents,
    )

    # Try streaming first for better results
    final_parts: list[str] = []
    errors: list[str] = []
    try:
        async with asyncio.timeout(90.0):
            async for chunk in adapter.send(messages=messages, stream=True):
                ctype = chunk.get("type")
                if ctype == "text":
                    final_parts.append(str(chunk.get("delta", "")))
                elif ctype == "error":
                    errors.append(f"{chunk.get('code', 'adapter_error')}: {chunk.get('message', '')}")
                    break
                elif ctype == "done":
                    break
    except asyncio.TimeoutError as exc:
        raise RuntimeError(f"LLM preview generation timed out after 90s: {agent_name}") from exc

    final_text = "".join(final_parts)
    html_doc = _extract_html_from_text(final_text)
    if html_doc:
        return html_doc, _html_title(html_doc, _clean_requirement(user_text)), f"{reason}:{agent_name}"

    if errors:
        raise RuntimeError("; ".join(errors))
    raise RuntimeError(f"LLM agent returned no complete HTML document: {agent_name}")


async def _llm_analyze_task(user_text: str) -> tuple[str | None, set[str]]:
    """Use a configured LLM agent to classify the task AND detect required domains.

    Returns ``(task_type, domains)`` where:
    - ``task_type``: ``"software"``, ``"non_software"``, or ``None`` (LLM unavailable)
    - ``domains``: set of domain strings like ``{"frontend", "backend", "database"}``
    """
    Session = get_sessionmaker()
    async with Session() as s:
        agents = (
            await s.scalars(
                select(Agent).where(
                    Agent.id != ORCHESTRATOR_AGENT_ID,
                    Agent.adapter_type != "mock",
                )
            )
        ).all()
        llm_agents = []
        for a in agents:
            try:
                cfg = json.loads(a.config) if a.config else {}
            except (TypeError, ValueError):
                cfg = {}
            if cfg.get("api_key"):
                llm_agents.append(a)
    if not llm_agents:
        return None, set()

    from handlers.send_message import load_adapter_for
    loaded = await load_adapter_for(llm_agents[0].id)
    if loaded is None:
        return None, set()
    adapter, _ = loaded

    prompt = (
        "Analyze the user request below. Return a JSON object with exactly two fields:\n\n"
        '  "type": "software" or "non_software"\n'
        '  "domains": array of relevant domains\n\n'
        "Domain definitions:\n"
        '- "frontend": UI/pages/components/styling/layout/interaction\n'
        '- "backend": API/business logic/routing/middleware/auth\n'
        '- "database": data model/SQL/migrations/schema/storage\n'
        '- "test": testing/quality assurance\n'
        '- "docs": documentation/readme\n'
        '- "devops": CI/CD/Docker/deployment\n\n'
        "software = creating/modifying web pages, UI, APIs, databases, apps, deployment.\n"
        "non_software = math modeling, data analysis, papers, research, academic questions.\n\n"
        "Only include domains the user explicitly or implicitly needs. "
        "For non_software tasks, use domain \"code\".\n\n"
        "Reply with ONLY the JSON object, no other text.\n\n"
        "User request:\n"
        f"{user_text[:3000]}"
    )
    try:
        async with asyncio.timeout(20):
            result = ""
            async for chunk in adapter.send(
                messages=[{"role": "user", "content": prompt}]
            ):
                if chunk.get("type") == "text":
                    result += chunk.get("delta", "")
                elif chunk.get("type") == "error":
                    logger.warning("LLM analyze error: %s", chunk.get("message"))
                    return None, set()
                elif chunk.get("type") == "done":
                    break

            # Parse JSON from response
            json_match = re.search(r"\{[\s\S]*\}", result)
            if not json_match:
                logger.warning("LLM analyze: no JSON found in response")
                return None, set()

            try:
                data = json.loads(json_match.group())
            except json.JSONDecodeError:
                logger.warning("LLM analyze: invalid JSON")
                return None, set()

            task_type = data.get("type", "software")
            if task_type not in ("software", "non_software"):
                task_type = "software"

            raw_domains = data.get("domains", [])
            if not isinstance(raw_domains, list):
                raw_domains = []

            valid_domains = {"frontend", "backend", "database", "test", "docs", "devops", "code"}
            domains = {d for d in raw_domains if isinstance(d, str) and d in valid_domains}

            logger.info("LLM analyzed task: type=%s domains=%s", task_type, domains)
            return task_type, domains

    except asyncio.TimeoutError:
        logger.warning("LLM task analysis timed out after 20s")
        return None, set()
    except Exception as exc:
        logger.warning("LLM task analysis failed: %s", exc)
        return None, set()


async def _resolve_decomposer_deps_with_llm(decomposer, decompose_result) -> Any:
    """Resolve subtask dependencies using LLM instead of hardcoded DOMAIN_DEPENDENCIES.

    Loads a configured LLM agent and delegates to
    EnhancedTaskDecomposer.resolve_dependencies_llm().

    Returns the (possibly updated) decompose_result. On failure returns the
    original result unchanged.
    """
    from db.engine import get_sessionmaker

    Session = get_sessionmaker()
    async with Session() as s:
        from db.models import Agent
        agents = (
            await s.scalars(
                select(Agent).where(
                    Agent.id != ORCHESTRATOR_AGENT_ID,
                    Agent.adapter_type != "mock",
                )
            )
        ).all()
        llm_agents = []
        for a in agents:
            try:
                cfg = json.loads(a.config) if a.config else {}
            except (TypeError, ValueError):
                cfg = {}
            if cfg.get("api_key"):
                llm_agents.append(a)
    if not llm_agents:
        logger.warning("No LLM agent available for dependency resolution")
        return decompose_result

    from handlers.send_message import load_adapter_for
    loaded = await load_adapter_for(llm_agents[0].id)
    if loaded is None:
        logger.warning("Failed to load LLM adapter for dependency resolution")
        return decompose_result
    adapter, _ = loaded

    try:
        return await decomposer.resolve_dependencies_llm(
            decompose_result,
            adapter.send,
            timeout=30.0,
        )
    except Exception as exc:
        logger.warning("LLM dependency resolution failed: %s", exc)
        return decompose_result


async def handle_orchestrator_mention(
    conn: Connection,
    conversation_id: str,
    user_text: str,
    mentions: list[str],
    originating_message_id: str,
) -> None:
    logger.info("Orchestrator invoked in conv=%s: %.80s", conversation_id, user_text)

    Session = get_sessionmaker()

    # Load conversation history + pinned messages for context
    conversation_history: list[dict[str, Any]] = []
    pinned_context: list[str] = []
    async with Session() as s:
        rows = (
            await s.scalars(
                select(MessageModel)
                .where(MessageModel.conversation_id == conversation_id)
                .order_by(desc(MessageModel.created_at))
                .limit(50)
            )
        ).all()
        for m in reversed(rows):
            role = "assistant" if m.sender_type == "agent" else "user"
            try:
                raw = json.loads(m.content) if m.content else {}
                text = raw.get("text", "") if isinstance(raw, dict) else ""
            except (json.JSONDecodeError, TypeError):
                text = ""
            if text.strip():
                conversation_history.append({"role": role, "content": text, "pinned": bool(m.pinned)})
        pinned_context = [msg["content"] for msg in conversation_history if msg.get("pinned")]

    # 1. Emit planning status (must appear within 3s per SPEC)
    demo_mode = _is_login_collaboration_demo(user_text)

    # 1. Emit planning status (must appear within 3s per SPEC)
    planning_msg = "正在理解用户意图、读取上下文，并准备拆解多 Agent 协作任务。"
    process_text = (
        "**Orchestrator 已接管任务**\n\n"
        f"- 用户意图：{_clean_requirement(user_text)[:180]}\n"
        f"- 上下文：已读取最近 {len(conversation_history)} 条消息，其中 {len(pinned_context)} 条为 pin 长期上下文\n"
        "- 协调策略：先拆解任务，再按 Agent 能力分派，最后汇总结论并检查冲突\n"
    )
    if demo_mode:
        process_text += (
            "\n本次识别为登录页协作 Demo，我会固定拆成 4 个子任务："
            "前端页面、后端接口、数据库表设计、测试与验收建议。"
        )
    await conn.send(event(
        "stream_chunk",
        message_id=originating_message_id,
        sender_id=ORCHESTRATOR_AGENT_ID,
        conversation_id=conversation_id,
        seq=1,
        delta=process_text,
    ))
    async with Session() as s:
        await update_message_content(s, originating_message_id, {"type": "text", "text": process_text})

    await conn.send(event(
        "context_info",
        conversation_id=conversation_id,
        total_messages=len(conversation_history),
        pinned_messages=len(pinned_context),
    ))

    await conn.send(event(
        "task_update",
        conversation_id=conversation_id,
        task={
            "id": "planning",
            "conversation_id": conversation_id,
            "parent_task_id": None,
            "title": user_text[:80],
            "description": user_text,
            "status": "planning",
            "domain": None,
            "assigned_agent_id": ORCHESTRATOR_AGENT_ID,
            "originating_message_id": originating_message_id,
            "result_summary": planning_msg,
            "progress_pct": 0,
            "created_at": int(time.time() * 1000),
            "updated_at": int(time.time() * 1000),
        },
        action="created",
    ))
    animation_bus.agent_created(
        conversation_id=conversation_id,
        agent_id=ORCHESTRATOR_AGENT_ID,
        role="Orchestrator",
        parent_id=None,
        domain="orchestrator",
        agent_name="Orchestrator",
    )
    animation_bus.agent_status(
        conversation_id=conversation_id,
        agent_id=ORCHESTRATOR_AGENT_ID,
        status="BUSY",
    )
    animation_bus.viz_event(
        conversation_id=conversation_id,
        kind="llm",
        label="Orchestrator: 开始规划",
    )

    # 2. LLM-driven task analysis: classify type AND detect required domains
    #    Single LLM call replaces both _llm_classify_task and ComplexityJudge
    llm_type, llm_domains = await _llm_analyze_task(user_text)

    if demo_mode:
        llm_type = "software"
        complexity_domains = {"frontend", "backend", "database", "test"}
    elif llm_type == "non_software":
        complexity_domains = {"code"}
    elif llm_domains:
        complexity_domains = _ensure_preview_collaboration_domains(user_text, llm_domains)
    else:
        # LLM unavailable; fall back to keyword-based ComplexityJudge
        judge = ComplexityJudge()
        task_input = TaskInput(description=user_text, context=None)
        complexity = judge.judge(task_input)
        complexity_domains = set(complexity.domains)
        complexity_domains = _ensure_preview_collaboration_domains(user_text, complexity_domains)
        if not complexity_domains:
            complexity_domains = {"code"}

    # 3. Build prompt context for subtask description
    context_str = ""
    if pinned_context:
        context_str = "Pinned context:\n" + "\n---\n".join(pinned_context[:5]) + "\n"

    # 4. Create subtasks
    if demo_mode:
        decompose_subtasks = _login_collaboration_demo_subtasks(user_text)
        decompose_result = None
    elif llm_type == "non_software":
        # Single subtask: let one agent handle everything
        decompose_subtasks = [
            type("_", (), {
                "id": "task_code",
                "description": _clean_requirement(user_text),
                "domain": "code",
                "dependencies": [],
            })()
        ]
        decompose_result = None
    else:
        decomposer = EnhancedTaskDecomposer()
        task_input = TaskInput(description=user_text, context=context_str or None)

        # Try LLM-driven decomposition first; fall back to keyword-based
        if llm_type == "software" and llm_domains:
            from handlers.send_message import load_adapter_for
            Session2 = get_sessionmaker()
            async with Session2() as s2:
                agents = (
                    await s2.scalars(
                        select(Agent).where(
                            Agent.id != ORCHESTRATOR_AGENT_ID,
                            Agent.adapter_type != "mock",
                        )
                    )
                ).all()
                llm_agent = None
                for a in agents:
                    try:
                        cfg = json.loads(a.config) if a.config else {}
                    except (TypeError, ValueError):
                        cfg = {}
                    if cfg.get("api_key"):
                        llm_agent = a
                        break

            if llm_agent is not None:
                loaded = await load_adapter_for(llm_agent.id)
                if loaded is not None:
                    llm_adapter, _ = loaded
                    logger.info("Using LLM-driven decomposition for task")
                    decompose_result = await decomposer.decompose_with_llm(
                        task=task_input,
                        domains=complexity_domains,
                        llm_send_fn=llm_adapter.send,
                        timeout=30.0,
                    )
                else:
                    decompose_result = decomposer.decompose_with_contract(
                        task=task_input,
                        domains=complexity_domains,
                    )
            else:
                decompose_result = decomposer.decompose_with_contract(
                    task=task_input,
                    domains=complexity_domains,
                )
        else:
            decompose_result = decomposer.decompose_with_contract(
                task=task_input,
                domains=complexity_domains,
            )
        decompose_subtasks = decompose_result.subtasks

        all_same = len(set(st.description for st in decompose_subtasks)) <= 1
        if decompose_subtasks and not all_same:
            decompose_result = await _resolve_decomposer_deps_with_llm(decomposer, decompose_result)
        else:
            logger.info("All subtasks share the same description; parallel execution, skipping LLM dep resolution")
        decompose_subtasks = decompose_result.subtasks

        if not decompose_subtasks:
            decompose_subtasks = [
                type("_", (), {
                    "id": "fallback_1",
                    "description": _clean_requirement(user_text),
                    "domain": next(iter(complexity_domains)),
                    "dependencies": [],
                })()
            ]

    # 5. Create parent & subtask records in DB
    async with Session() as s:
        parent = await create_task(
            s,
            conversation_id=conversation_id,
            title=user_text[:80],
            description=user_text,
            domain=",".join(sorted(complexity_domains)),
            originating_message_id=originating_message_id,
        )
        parent_id = parent.id

        subtask_records = []
        subtask_id_map = {}
        for i, subtask in enumerate(decompose_subtasks):
            agent_id, agent_name = await _pick_agent_for_domain(
                s,
                domain=subtask.domain,
                conversation_id=conversation_id,
            )

            enhanced_desc = _build_subtask_description(subtask, decompose_result)
            depends_on_list = subtask.dependencies if hasattr(subtask, "dependencies") and subtask.dependencies else []
            input_summary = (
                f"Domain: {subtask.domain}. "
                f"{'Depends on: ' + ', '.join(depends_on_list) + '. ' if depends_on_list else ''}"
                f"{subtask.description[:100]}"
            )

            st = await create_task(
                s,
                conversation_id=conversation_id,
                title=subtask.description[:80],
                description=enhanced_desc,
                domain=subtask.domain,
                assigned_agent_id=agent_id,
                agent_name=agent_name,
                originating_message_id=originating_message_id,
                parent_task_id=parent_id,
            )
            subtask_id_map[subtask.id] = st.id
            subtask_records.append((st, agent_name, agent_id, input_summary, list(depends_on_list)))

        subtask_records = [
            (
                st,
                agent_name,
                agent_id,
                input_summary,
                [subtask_id_map[d] for d in depends_on_list if d in subtask_id_map],
            )
            for st, agent_name, agent_id, input_summary, depends_on_list in subtask_records
        ]

    for st, agent_name, agent_id, _input_summary, deps in subtask_records:
        animation_bus.agent_created(
            conversation_id=conversation_id,
            agent_id=agent_id,
            role=st.domain or "agent",
            parent_id=ORCHESTRATOR_AGENT_ID,
            domain=st.domain,
            agent_name=agent_name,
        )
        animation_bus.beam(
            conversation_id=conversation_id,
            from_id=ORCHESTRATOR_AGENT_ID,
            to_id=agent_id,
            kind="create",
            label=st.title[:24],
        )
        animation_bus.viz_event(
            conversation_id=conversation_id,
            kind="agent",
            label=f"閸掑棙娣崇紒?{agent_name}",
        )
        for dep_id in deps:
            dep_record = next((item for item in subtask_records if item[0].id == dep_id), None)
            if dep_record is not None:
                animation_bus.beam(
                    conversation_id=conversation_id,
                    from_id=dep_record[2],
                    to_id=agent_id,
                    kind="message",
                    label="依赖传递",
                )

    # 6. Update planning to running
    async with Session() as s:
        parent = await update_task_status(s, parent_id, "running",
            result_summary=f"Decomposed into {len(subtask_records)} subtasks")

    await conn.send(event(
        "task_update",
        conversation_id=conversation_id,
        task=task_to_dict(parent),
        action="status_changed",
    ))

    dispatch_plan = "\n".join(
        f"- {agent_name}：{st.title[:80]}（{st.domain or 'general'}）"
        for st, agent_name, _aid, _is, _dep in subtask_records
    )
    dispatch_intro = (
        f"\n\n**任务拆解完成，共 {len(subtask_records)} 个子任务**\n"
        f"{dispatch_plan}"
    )
    await conn.send(event(
        "stream_chunk",
        message_id=originating_message_id,
        sender_id=ORCHESTRATOR_AGENT_ID,
        conversation_id=conversation_id,
        seq=2,
        delta=dispatch_intro,
    ))

    for st, _agent_name, _aid, _is, _dep in subtask_records:
        task_dict = task_to_dict(st)
        task_dict["depends_on"] = _dep
        await conn.send(event(
            "task_update",
            conversation_id=conversation_id,
            task=task_dict,
            action="created",
        ))

    # 7. Build DAG and execute via event-driven DAG engine
    #     (no barrier: nodes dispatch as soon as dependencies are met)
    dag = DAG()
    for st, _agent_name, _agent_id, _input_summary, deps in subtask_records:
        dag.add_node(DAGNode(
            id=st.id,
            domain=st.domain or "",
            description=st.description or "",
            title=st.title or "",
            dependencies=list(deps),
            assigned_agent_id=_agent_id,
            assigned_agent_name=_agent_name,
            input_summary=_input_summary,
            metadata={"task_record": st},
        ))

    async def _dispatch_node(node: DAGNode) -> str:
        st = node.metadata["task_record"]
        async with Session() as s:
            updated = await update_task_status(s, st.id, "running")
        if updated is not None:
            await conn.send(event(
                "task_update",
                conversation_id=conversation_id,
                task=task_to_dict(updated),
                task_id=updated.parent_task_id or updated.id,
                subtask_id=updated.id if updated.parent_task_id else None,
                status=updated.status,
                progress=updated.progress_pct,
                message_id=None,
                action="status_changed",
            ))
        animation_bus.agent_status(
            conversation_id=conversation_id,
            agent_id=node.assigned_agent_id,
            status="BUSY",
        )
        animation_bus.viz_event(
            conversation_id=conversation_id,
            kind="llm",
            label=f"{node.assigned_agent_name}: 开始执行",
        )
        try:
            result_message_id = await _dispatch_subtask_with_retry(
                conn, st,
                agent_id=node.assigned_agent_id,
                conversation_id=conversation_id,
                user_text=(
                    f"[Orchestrator] Subtask: {node.title}\nInput: {node.input_summary}"
                ),
                pinned_context=pinned_context,
            )
            animation_bus.viz_event(
                conversation_id=conversation_id,
                kind="llm",
                label=f"{node.assigned_agent_name}: 执行完成",
            )
            return result_message_id
        finally:
            animation_bus.agent_status(
                conversation_id=conversation_id,
                agent_id=node.assigned_agent_id,
                status="IDLE",
            )

    executor = DAGExecutor(dag, _dispatch_node, max_concurrency=len(subtask_records))
    dag_result = await executor.execute()

    completed_ids: set[str] = dag_result["completed"]
    failed_ids: set[str] = dag_result["failed"]
    subtask_messages: dict[str, str] = dag_result["subtask_messages"]

    # 8. Mark parent as done or failed
    all_done = len(completed_ids) == len(subtask_records)
    some_failed = len(failed_ids) > 0

    w4_artifact: dict[str, Any] | None = None

    if all_done:
        summary_text = (
            "**协作完成**\n\n"
            f"Orchestrator 已汇总 {len(subtask_records)} 个 Agent 子任务产出：\n"
        )

        if _should_create_w4_preview(user_text):
            try:
                html_content, preview_title, preview_source = await _generate_preview_html_with_model(
                    conversation_id=conversation_id,
                    user_text=user_text,
                    conversation_history=conversation_history,
                    subtask_records=subtask_records,
                    subtask_messages=subtask_messages,
                )
                async with Session() as s:
                    artifact = await create_service_artifact(
                        s,
                        conversation_id=conversation_id,
                        kind="preview",
                        title=preview_title,
                        mime_type="text/html",
                        file_name="orchestrator-preview.html",
                        content=html_content,
                        source_message_id=originating_message_id,
                        created_by=ORCHESTRATOR_AGENT_ID,
                        meta={
                            "source": "orchestrator",
                            "preview_source": preview_source,
                            "parent_task_id": parent_id,
                            "language": "html",
                        },
                    )
                    w4_artifact = artifact
                summary_text += f"\n已生成网页预览产物：`{artifact['id']}` ({preview_source})\n"
            except Exception as exc:
                logger.warning("Failed to create W4 preview artifact: %s", exc)
        for st, agent_name, aid, is_, deps in subtask_records:
            summary_text += f"- {agent_name}：{st.title[:80]}\n"
        if demo_mode:
            summary_text += (
                "\n最终交付清单：\n"
                "1. 前端页面：登录页代码与预览卡片\n"
                "2. 鍚庣鎺ュ彛锛氱櫥褰?API 璁捐銆佽姹傚搷搴斿拰閿欒澶勭悊\n"
                "3. 数据库：用户表结构、约束和索引建议\n"
                "4. 娴嬭瘯楠屾敹锛氭牳蹇冩祴璇曠敤渚嬪拰楠屾敹娓呭崟\n"
            )
        summary_text += f"\n{_conflict_resolution_note(subtask_records)}\n"

        async with Session() as s:
            parent = await update_task_status(s, parent_id, "done",
                result_summary=f"All {len(subtask_records)} subtasks completed")
    elif some_failed:
        success_count = len(completed_ids)
        fail_count = len(failed_ids)
        recovered_preview = False
        if _should_create_w4_preview(user_text):
            try:
                html_content, preview_title, preview_source = await _generate_preview_html_with_model(
                    conversation_id=conversation_id,
                    user_text=user_text,
                    conversation_history=conversation_history,
                    subtask_records=subtask_records,
                    subtask_messages=subtask_messages,
                )
                async with Session() as s:
                    artifact = await create_service_artifact(
                        s,
                        conversation_id=conversation_id,
                        kind="preview",
                        title=preview_title,
                        mime_type="text/html",
                        file_name="orchestrator-preview.html",
                        content=html_content,
                        source_message_id=originating_message_id,
                        created_by=ORCHESTRATOR_AGENT_ID,
                        meta={"source": preview_source, "llm_generated_after_subtask_failure": True},
                    )
                    preview_msg_id = new_id("msg")
                    preview_content = _preview_message_content(artifact, html_content)
                    preview_msg = await create_service_message(
                        s,
                        conversation_id=conversation_id,
                        sender_id=ORCHESTRATOR_AGENT_ID,
                        sender_type="agent",
                        content=preview_content,
                        message_id=preview_msg_id,
                        artifact_id=artifact["id"],
                    )
                    preview_msg_dict = message_to_dict(preview_msg)
                await conn.send(event("message_created", message=preview_msg_dict))
                await conn.send(event(
                    "artifact_ready",
                    conversation_id=conversation_id,
                    artifact=artifact,
                    message_id=preview_msg_id,
                ))
                await conn.send(event(
                    "message_done",
                    message_id=preview_msg_id,
                    sender_id=ORCHESTRATOR_AGENT_ID,
                    conversation_id=conversation_id,
                    final_content=preview_content,
                ))
                recovered_preview = True
                w4_artifact = artifact
            except Exception as exc:
                logger.warning("Failed to create LLM preview artifact: %s", exc)

        summary_text = (
            ("**协作完成（已降级补全）**\n\n" if recovered_preview else "⚠️ **Task Partially Complete**\n\n")
            + f"{success_count}/{len(subtask_records)} subtasks completed, "
            + f"{fail_count} failed.\n\n"
        )
        summary_text = (
            ("**Collaboration complete (LLM preview generated)**\n\n" if recovered_preview else "⚠️ **Task Partially Complete**\n\n")
            + f"{success_count}/{len(subtask_records)} subtasks completed, "
            + f"{fail_count} failed.\n\n"
        )
        if recovered_preview and w4_artifact is not None:
            summary_text += f"已根据现有子任务输出和需求补全网页预览产物：`{w4_artifact['id']}`。\n\n"
        if recovered_preview and w4_artifact is not None:
            summary_text = (
                "**Collaboration complete (LLM preview generated)**\n\n"
                + f"{success_count}/{len(subtask_records)} subtasks completed, "
                + f"{fail_count} failed.\n\n"
                + f"LLM model generated preview artifact: `{w4_artifact['id']}`.\n\n"
            )
        for st, agent_name, aid, is_, deps in subtask_records:
            if st.id in completed_ids:
                summary_text += f"- ✅ {st.title[:60]}\n"
            else:
                summary_text += f"- ❌ {st.title[:60]}\n"
        summary_text += f"\nLLM preview generation: "
        summary_text += "completed by a configured model.\n" if recovered_preview else "not completed; no fallback output was generated.\n"
        summary_text += f"{_conflict_resolution_note(subtask_records)}\n"

        async with Session() as s:
            parent = await update_task_status(
                s,
                parent_id,
                "done" if recovered_preview else "failed",
                result_summary=(
                    f"LLM preview generated with {success_count}/{len(subtask_records)} completed"
                    if recovered_preview
                    else f"{success_count}/{len(subtask_records)} completed, {fail_count} failed"
                ),
            )
    else:
        blocked_count = len(subtask_records) - len(completed_ids) - len(failed_ids)
        summary_text = (
            f"⚠️ **Task Blocked**\n\n"
            f"{len(completed_ids)}/{len(subtask_records)} subtasks completed, "
            f"{blocked_count} blocked by unresolved dependencies.\n\n"
        )
        for st, agent_name, aid, is_, deps in subtask_records:
            if st.id in completed_ids:
                summary_text += f"- ✅ {st.title[:60]}\n"
            else:
                summary_text += f"- ⏳ {st.title[:60]}\n"
                async with Session() as s:
                    updated = await update_task_status(s, st.id, "failed",
                        result_summary="Blocked by unresolved dependencies")
                if updated is not None:
                    await conn.send(event(
                        "task_update",
                        conversation_id=conversation_id,
                        task=task_to_dict(updated),
                        task_id=updated.parent_task_id or updated.id,
                        subtask_id=updated.id if updated.parent_task_id else None,
                        status=updated.status,
                        progress=updated.progress_pct,
                        message_id=None,
                        action="status_changed",
                    ))
        summary_text += f"\nFailure degradation: blocked subtasks were reported without discarding completed work.\n{_conflict_resolution_note(subtask_records)}\n"

        async with Session() as s:
            parent = await update_task_status(s, parent_id, "failed",
                result_summary="Some subtasks were blocked by unresolved dependencies")

    # 9. Send summary as a message in chat
    summary_msg_id = new_id("msg")
    async with Session() as s:
        msg_obj = await create_service_message(
            s,
            conversation_id=conversation_id,
            sender_id=ORCHESTRATOR_AGENT_ID,
            sender_type="agent",
            content={"type": "text", "text": summary_text},
            message_id=summary_msg_id,
        )
        summary_msg_dict = message_to_dict(msg_obj)

    await conn.send(event("message_created", message=summary_msg_dict))

    async with Session() as s:
        await update_message_content(s, summary_msg_id, {"type": "text", "text": summary_text})

    await conn.send(event(
        "message_done",
        message_id=summary_msg_id,
        sender_id=ORCHESTRATOR_AGENT_ID,
        conversation_id=conversation_id,
        final_content={"type": "text", "text": summary_text},
    ))

    await conn.send(event(
        "message_done",
        message_id=originating_message_id,
        sender_id=ORCHESTRATOR_AGENT_ID,
        conversation_id=conversation_id,
        final_content={"type": "text", "text": process_text},
    ))
    animation_bus.agent_status(
        conversation_id=conversation_id,
        agent_id=ORCHESTRATOR_AGENT_ID,
        status="IDLE",
    )
    animation_bus.viz_event(
        conversation_id=conversation_id,
        kind="llm",
        label="Orchestrator: 协作完成",
    )

    if w4_artifact is not None:
        preview_msg_id = new_id("msg")
        preview_content = {
            "type": "preview",
            "artifact_id": w4_artifact["id"],
            "title": w4_artifact["title"],
            "mimeType": w4_artifact["mime_type"],
            "fileSize": w4_artifact["file_size"],
            "url": w4_artifact.get("url"),
            "previewUrl": w4_artifact.get("preview_url"),
            "version": w4_artifact.get("version", 1),
        }
        async with Session() as s:
            preview_msg = await create_service_message(
                s,
                conversation_id=conversation_id,
                sender_id=ORCHESTRATOR_AGENT_ID,
                sender_type="agent",
                content=preview_content,
                message_id=preview_msg_id,
                artifact_id=w4_artifact["id"],
            )
            preview_msg_dict = message_to_dict(preview_msg)
        await conn.send(event("message_created", message=preview_msg_dict))
        await conn.send(event(
            "artifact_ready",
            conversation_id=conversation_id,
            artifact=w4_artifact,
            message_id=preview_msg_id,
        ))
        await conn.send(event(
            "message_done",
            message_id=preview_msg_id,
            sender_id=ORCHESTRATOR_AGENT_ID,
            conversation_id=conversation_id,
            final_content=preview_content,
        ))

    await conn.send(event(
        "task_update",
        conversation_id=conversation_id,
        task=task_to_dict(parent),
        action="completed",
    ))

    logger.info("Orchestrator completed parent=%s (%d subtasks, %d ok, %d failed)",
                parent_id, len(subtask_records), len(completed_ids), len(failed_ids))


async def _dispatch_subtask_with_result(
    conn: Connection,
    st: Any,
    agent_id: str,
    conversation_id: str,
    user_text: str,
    pinned_context: list[str] | None = None,
) -> str:
    """Dispatch a subtask to an agent and create a message bubble for it.

    Returns the message_id of the agent's reply message.
    """
    Session = get_sessionmaker()

    # Create agent placeholder message for this subtask
    async with Session() as s:
        agent_msg = await create_service_message(
            s,
            conversation_id=conversation_id,
            sender_id=agent_id,
            sender_type="agent",
            content={"type": "text", "text": f"⏳ 正在处理：{st.title[:80]}..."},
        )
        msg_id = agent_msg.id
        msg_dict = message_to_dict(agent_msg)

    await conn.send(event("message_created", message=msg_dict))
    await conn.send(event("agent_typing", agent_id=agent_id, conversation_id=conversation_id))

    # Build a concise subtask message with pinned context
    pinned_block = ""
    if pinned_context:
        pinned_block = (
            "\n**Pinned Context锛堝浐瀹氫笂涓嬫枃锛?**\n"
            + "\n---\n".join(pc[:500] for pc in pinned_context[:5])
            + "\n"
        )

    agent_prompt = (
        f"[Orchestrator Subtask Assignment]\n\n"
        f"**Original Input**: {user_text}\n"
        f"**Task**: {st.title}\n"
        f"**Domain**: {st.domain}\n"
        f"**Description**: {st.description}\n"
        f"{pinned_block}"
    )

    from handlers.send_message import load_adapter_for, persist_final
    loaded = await load_adapter_for(agent_id)

    if loaded is None:
        async with Session() as s:
            await update_message_content(s, msg_id, {
                "type": "text",
                "text": f"❌ Agent `{agent_id}` not available for subtask: {st.title[:60]}",
            })
        await conn.send(event(
            "message_done",
            message_id=msg_id,
            sender_id=agent_id,
            conversation_id=conversation_id,
            final_content={"type": "text", "text": "❌ Agent unavailable."},
        ))
        async with Session() as s:
            updated = await update_task_status(s, st.id, "failed",
                result_summary=f"Agent {agent_id} not available")
        if updated is not None:
            await conn.send(event(
                "task_update",
                conversation_id=conversation_id,
                task=task_to_dict(updated),
                task_id=updated.parent_task_id or updated.id,
                subtask_id=updated.id if updated.parent_task_id else None,
                status=updated.status,
                progress=updated.progress_pct,
                message_id=msg_id,
                action="status_changed",
            ))
        raise RuntimeError(f"Agent {agent_id} not available")

    adapter, _agent_name = loaded
    is_frontend_preview = False
    # Setup workspace + ToolRegistry
    # All agents in the same conversation share the same workspace directory
    _PROJECT_ROOT = Path(__file__).resolve().parents[1]
    async with Session() as s:
        conv = await s.scalar(select(Conversation).where(Conversation.id == conversation_id))
        conv_workspace_path = conv.workspace_path if conv else None

    if conv_workspace_path:
        workspace_dir = Path(conv_workspace_path)
    else:
        workspace_dir = _PROJECT_ROOT / "workspaces" / conversation_id
    workspace_dir.mkdir(parents=True, exist_ok=True)

    registry = get_tool_registry(project_root=str(workspace_dir))
    tool_artifacts_list: list[dict[str, Any]] = []
    registry.set_runtime_context(
        conversation_id=conversation_id,
        current_agent_id=agent_id,
        conn=conn,
        _artifacts=tool_artifacts_list,
    )

    if hasattr(adapter, 'set_runtime_context'):
        adapter.set_runtime_context(conversation_id, agent_id, conn)

    # Tell agent about its workspace and available tools
    workspace_note = (
        f"\n**Workspace**: {workspace_dir}\n"
        f"你可以使用 read_file / write_file / list_files / web_search 等工具辅助完成任务。\n"
        f"所有文件操作默认在 workspace 目录下进行。\n"
        f"此 workspace 由本对话的所有 Agent 共享，你可以看到其他 Agent 创建的文件。\n"
        f"\n**重要规则**：\n"
        f"- 直接执行任务，不要询问用户问题或征求确认。\n"
        f"- 如需使用工具（如 web_search / write_file），直接调用即可，无需提前告知。\n"
        f"- 不要输出需要我确认的问题，直接行动。\n"
        f"- 一次性完成全部工作，产出完整可用的成果。\n"
    )
    agent_prompt += workspace_note

    builtin_loop = getattr(adapter, 'has_builtin_loop', False)
    if builtin_loop:
        messages = [{"role": "user", "content": agent_prompt}]
        chunk_source = adapter.send(messages=messages)
    else:
        messages = [{"role": "user", "content": agent_prompt}]
        has_tools = bool(registry.list_tools())
        if has_tools and ReActEngine.should_use_react(adapter, agent_prompt):
            engine = ReActEngine(registry=registry, max_steps=10, llm_timeout=180.0)
            tool_schemas = registry.get_openai_schemas()
            chunk_source = engine.run(adapter, messages, tools=tool_schemas)
        else:
            chunk_source = adapter.send(messages=messages)

    final_parts: list[str] = []
    error_parts: list[str] = []
    seq = 0

    try:
        async for chunk in chunk_source:
            ctype = chunk.get("type")
            if ctype == "text":
                seq += 1
                delta = chunk.get("delta", "")
                final_parts.append(delta)
                await conn.send(event(
                    "stream_chunk",
                    message_id=msg_id,
                    sender_id=agent_id,
                    conversation_id=conversation_id,
                    seq=seq,
                    delta=delta,
                ))
            elif ctype == "tool_call":
                tool_name = str(chunk.get("name") or chunk.get("tool_name") or "tool")
                tool_args = chunk.get("args") or chunk.get("tool_arguments") or {}
                await conn.send(event(
                    "tool_call",
                    message_id=msg_id,
                    sender_id=agent_id,
                    conversation_id=conversation_id,
                    tool_name=tool_name,
                    tool_arguments=tool_args if isinstance(tool_args, dict) else {},
                    status="running",
                ))
                animation_bus.viz_event(
                    conversation_id=conversation_id,
                    kind="tool",
                    label=f"{_agent_name}: 调用工具 {tool_name}",
                )
            elif ctype == "observation":
                obs_name = str(chunk.get("name") or "tool")
                obs_result = chunk.get("result") or ""
                obs_text = obs_result if isinstance(obs_result, str) else str(obs_result)
                await conn.send(event(
                    "tool_call",
                    message_id=msg_id,
                    sender_id=agent_id,
                    conversation_id=conversation_id,
                    tool_name=obs_name,
                    status="done",
                    result_summary=obs_text[:240],
                ))
                animation_bus.viz_event(
                    conversation_id=conversation_id,
                    kind="tool",
                    label=f"{_agent_name}: 工具返回 {obs_name}",
                )
            elif ctype == "usage":
                await conn.send(event(
                    "usage",
                    message_id=msg_id,
                    sender_id=agent_id,
                    input_tokens=chunk.get("input_tokens", 0),
                    output_tokens=chunk.get("output_tokens", 0),
                    total_cost_usd=chunk.get("total_cost_usd"),
                ))
            elif ctype == "warning":
                # Warnings (e.g. max_steps reached) are informational, not failures
                warn_code = chunk.get("code") or "react_warning"
                warn_msg = chunk.get("message") or ""
                logger.warning("Subtask agent warning: %s - %s", warn_code, warn_msg)
                final_parts.append(f"\n[Notice] {warn_msg}")
            elif ctype == "error":
                code = chunk.get("code") or "adapter_error"
                message = chunk.get("message") or "Agent adapter error"
                error_parts.append(f"{code}: {message}")
            elif ctype == "done":
                break

        if error_parts and is_frontend_preview:
            error_text = "; ".join(error_parts)
            final_text = "".join(final_parts)
            html_doc = _extract_html_from_text(final_text) or _close_partial_html(
                final_text,
                user_text,
                error_text,
            )
            async with Session() as s:
                artifact_payload = await create_service_artifact(
                    s,
                    conversation_id=conversation_id,
                    kind="preview",
                    title=_html_title(html_doc, st.title),
                    mime_type="text/html",
                    file_name="subtask-preview.html",
                    content=html_doc,
                    source_message_id=msg_id,
                    created_by=agent_id,
                    meta={
                        "source": "frontend_recovered_html",
                        "language": "html",
                        "task_id": st.id,
                        "recovery_reason": error_text,
                    },
                )
                content_payload = _preview_message_content(artifact_payload, html_doc)
                await update_message_content(s, msg_id, content_payload)
                row = await s.get(MessageModel, msg_id)
                if row is not None:
                    row.artifact_id = artifact_payload["id"]
                    await s.commit()
            await conn.send(event(
                "artifact_ready",
                conversation_id=conversation_id,
                artifact=artifact_payload,
                message_id=msg_id,
            ))
            await conn.send(event(
                "message_done",
                message_id=msg_id,
                sender_id=agent_id,
                conversation_id=conversation_id,
                final_content=content_payload,
            ))
            display_text = f"已生成可预览 HTML（截断后恢复）：{artifact_payload['title']}"
            async with Session() as s:
                updated = await update_task_status(
                    s,
                    st.id,
                    "done",
                    result_summary=f"{display_text}; recovery_reason={error_text}"[:200],
                    progress_pct=100,
                )
            if updated is not None:
                await conn.send(event(
                    "task_update",
                    conversation_id=conversation_id,
                    task=task_to_dict(updated),
                    task_id=updated.parent_task_id or updated.id,
                    subtask_id=updated.id if updated.parent_task_id else None,
                    status=updated.status,
                    progress=updated.progress_pct,
                    message_id=msg_id,
                    action="status_changed",
                ))
            return msg_id

        if error_parts:
            final_text = "".join(final_parts) + _visible_generation_error(
                str(code),
                str(message),
            )
            async with Session() as s:
                await update_message_content(s, msg_id, {"type": "text", "text": final_text})
            await conn.send(event(
                "message_done",
                message_id=msg_id,
                sender_id=agent_id,
                conversation_id=conversation_id,
                final_content={"type": "text", "text": final_text},
            ))
            async with Session() as s:
                updated = await update_task_status(s, st.id, "failed",
                    result_summary=final_text[:200])
            if updated is not None:
                await conn.send(event(
                    "task_update",
                    conversation_id=conversation_id,
                    task=task_to_dict(updated),
                    task_id=updated.parent_task_id or updated.id,
                    subtask_id=updated.id if updated.parent_task_id else None,
                    status=updated.status,
                    progress=updated.progress_pct,
                    message_id=msg_id,
                    action="status_changed",
                ))
            raise RuntimeError(final_text)

        final_text = "".join(final_parts) or f"✅ 子任务已完成：{st.title[:100]}"
        async with Session() as s:
            await update_message_content(s, msg_id, {"type": "text", "text": final_text})
        await conn.send(event(
            "message_done",
            message_id=msg_id,
            sender_id=agent_id,
            conversation_id=conversation_id,
            final_content={"type": "text", "text": final_text},
        ))

        display_text = final_text
        artifact_payload = None
        if agent_id.startswith("agent_mock") or is_frontend_preview:
            html_doc = _extract_html_from_text(final_text)
            if html_doc is None and is_frontend_preview and _looks_like_html(final_text):
                html_doc = _close_partial_html(final_text, user_text, "frontend_html_incomplete")
            if html_doc:
                async with Session() as s:
                    artifact_payload = await create_service_artifact(
                        s,
                        conversation_id=conversation_id,
                        kind="preview",
                        title=_html_title(html_doc, st.title),
                        mime_type="text/html",
                        file_name="subtask-preview.html",
                        content=html_doc,
                        source_message_id=msg_id,
                        created_by=agent_id,
                        meta={"source": "subtask_html", "language": "html", "task_id": st.id},
                    )
                    # Create a separate preview message instead of overwriting the text message
                    preview_msg_id = new_id("msg")
                    preview_content = _preview_message_content(artifact_payload, html_doc)
                    preview_msg = await create_service_message(
                        s,
                        conversation_id=conversation_id,
                        sender_id=agent_id,
                        sender_type="agent",
                        content=preview_content,
                        message_id=preview_msg_id,
                        artifact_id=artifact_payload["id"],
                    )
                    preview_msg_dict = message_to_dict(preview_msg)
                await conn.send(event("message_created", message=preview_msg_dict))
                await conn.send(event(
                    "artifact_ready",
                    conversation_id=conversation_id,
                    artifact=artifact_payload,
                    message_id=preview_msg_id,
                ))
                await conn.send(event(
                    "message_done",
                    message_id=preview_msg_id,
                    sender_id=agent_id,
                    conversation_id=conversation_id,
                    final_content=preview_content,
                ))
                display_text = f"Generated preview HTML: {artifact_payload['title']}"

        # Mark subtask as done
        async with Session() as s:
            updated = await update_task_status(s, st.id, "done",
                result_summary=display_text[:200],
                progress_pct=100)
        if updated is not None:
            await conn.send(event(
                "task_update",
                conversation_id=conversation_id,
                task=task_to_dict(updated),
                task_id=updated.parent_task_id or updated.id,
                subtask_id=updated.id if updated.parent_task_id else None,
                status=updated.status,
                progress=updated.progress_pct,
                message_id=msg_id,
                action="status_changed",
            ))

    except asyncio.CancelledError:
        async with Session() as s:
            await update_message_content(s, msg_id, {"type": "text", "text": "[cancelled]"})
        raise

    return msg_id


async def _dispatch_subtask_with_retry(
    conn: Connection,
    st: Any,
    agent_id: str,
    conversation_id: str,
    user_text: str,
    pinned_context: list[str] | None = None,
) -> str:
    last_exc: Exception | None = None
    for attempt in range(RETRY_LIMIT + 1):
        try:
            return await _dispatch_subtask_with_result(
                conn,
                st,
                agent_id=agent_id,
                conversation_id=conversation_id,
                user_text=user_text,
                pinned_context=pinned_context,
            )
        except Exception as exc:
            last_exc = exc
            if attempt >= RETRY_LIMIT:
                break
            Session = get_sessionmaker()
            async with Session() as s:
                updated = await update_task_status(
                    s,
                    st.id,
                    "running",
                    result_summary=f"Retrying after adapter failure: {str(exc)[:120]}",
                    progress_pct=25,
                )
            if updated is not None:
                await conn.send(event(
                    "task_update",
                    conversation_id=conversation_id,
                    task=task_to_dict(updated),
                    action="status_changed",
                ))
            await asyncio.sleep(0.25)
    raise RuntimeError(f"subtask degraded after retry: {last_exc}") from last_exc
