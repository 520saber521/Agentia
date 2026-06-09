"""MockAdapter -- offline fixed reply for W1 chain verification.

Features:

- No external API calls, runs fully offline (CI / dev).
- Tokenizes by English word / CJK char / whitespace / punctuation to simulate LLM streaming.
- ``delay_ms`` controls per-token sleep for demo or load testing.
- Detects Orchestrator subtask dispatch and generates domain-specific fake replies,
  so the full调度链路 can be verified without any external API.
- Passes through ``asyncio.CancelledError`` for BFF cancel support.
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
    "You said: {echo}"
)

_TOKEN_RE = re.compile(r"[A-Za-z]+|[0-9]+|\s+|[一-鿿]|.", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    return [tok for tok in _TOKEN_RE.findall(text or "") if tok]


def _last_user_text(messages: List[dict[str, Any]] | None) -> str:
    for m in reversed(messages or []):
        if m.get("role") == "user":
            c = m.get("content")
            return c if isinstance(c, str) else str(c)
    return ""


# ---------------------------------------------------------------------------
# Orchestrator subtask detection & domain-specific fake replies
# ---------------------------------------------------------------------------

_SUBTASK_PREFIX = "[Orchestrator Subtask Assignment]"
_DOMAIN_RE = re.compile(r"\*\*Domain\*\*\s*[:：]?\s*(\S+)", re.IGNORECASE)
_TASK_RE = re.compile(r"\*\*Task\*\*\s*[:：]?\s*(.+)", re.IGNORECASE)
_DESC_RE = re.compile(r"\*\*Description\*\*\s*[:：]?\s*(.+)", re.IGNORECASE)


def _detect_subtask(messages: List[dict[str, Any]] | None) -> dict[str, str] | None:
    text = _last_user_text(messages)
    if not text or _SUBTASK_PREFIX not in text:
        return None
    return {
        "domain": _domain(text),
        "task": _extract(_TASK_RE, text, ""),
        "description": _extract(_DESC_RE, text, ""),
    }


def _domain(text: str) -> str:
    m = _DOMAIN_RE.search(text)
    return m.group(1).strip().lower() if m else "general"


def _extract(p: re.Pattern, text: str, fallback: str) -> str:
    m = p.search(text)
    return m.group(1).strip() if m else fallback


_DOMAIN_REPLIES: dict[str, str] = {
    "frontend": (
        "Frontend UI implementation complete.\n\n"
        "The interface follows a clean card-based waterfall layout:\n"
        "- Card feed with cover images, titles, author info\n"
        "- Immersive search bar at top\n"
        "- Bottom Tab navigation (Home, Discover, Post, Messages, Profile)\n\n"
        "```html\n"
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>Xiaohongshu Clone</title>"
        "<style>"
        "*{box-sizing:border-box;margin:0;padding:0}"
        "body{background:#f5f5f5;font-family:-apple-system,sans-serif}"
        ".app{max-width:430px;margin:0 auto;background:#fff;min-height:100vh}"
        ".header{display:flex;align-items:center;justify-content:space-between;padding:12px 16px}"
        ".header h1{font-size:18px;font-weight:700;color:#ff2442}.feed{display:grid;"
        "grid-template-columns:1fr 1fr;gap:8px;padding:0 8px}"
        ".card{border-radius:12px;overflow:hidden;background:#fff;"
        "box-shadow:0 1px 4px rgba(0,0,0,.06)}"
        ".card .cover{height:180px;background:linear-gradient(135deg,#fce4ec,#ffcdd2);"
        "display:flex;align-items:center;justify-content:center;color:#999;font-size:12px}"
        ".card .info{padding:8px 10px 12px}"
        ".card .info h3{font-size:13px;font-weight:500;"
        "overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2}"
        ".tabs{position:fixed;bottom:0;max-width:430px;width:100%;background:#fff;"
        "border-top:1px solid #eee;display:flex;justify-content:space-around;padding:8px 0}"
        "</style></head><body>"
        "<div class=\"app\">"
        "<div class=\"header\"><h1>Xiaohongshu</h1><span>bell</span></div>"
        "<div class=\"feed\">"
        "<div class=\"card\"><div class=\"cover\">Cover</div>"
        "<div class=\"info\"><h3>Sample Note Title</h3></div></div>"
        "<div class=\"card\"><div class=\"cover\">Cover</div>"
        "<div class=\"info\"><h3>Another Note</h3></div></div>"
        "</div></div>"
        "<div class=\"tabs\"><button>Home</button><button>Discover</button>"
        "<button>Post</button><button>Messages</button><button>Profile</button></div>"
        "</body></html>"
        "```\n\n"
        "Delivered: card feed, search bar, bottom tabs, like/comment counts."
    ),
    "backend": (
        "Backend API implementation complete.\n\n"
        "Endpoints:\n"
        "- GET /api/notes -- paginated note list\n"
        "- GET /api/notes/:id -- note detail\n"
        "- POST /api/notes -- create note\n"
        "- POST /api/like -- toggle like\n"
        "- POST /api/follow -- toggle follow\n"
        "- GET /api/user/profile -- user profile\n\n"
        "Built with FastAPI + SQLite, includes CORS and pagination."
    ),
    "database": (
        "Database schema complete.\n\n"
        "Tables: users, notes, likes, follows\n"
        "Indexes on notes.created_at, likes unique constraint, follows bidirectional.\n"
        "All migrations are idempotent."
    ),
    "test": (
        "Test suite complete.\n\n"
        "Coverage:\n"
        "1. API endpoint tests (200/400/404 for each route)\n"
        "2. Model CRUD + constraint tests\n"
        "3. Component rendering tests (React Testing Library)\n"
        "4. Integration: create note -> show in feed -> like -> follow\n\n"
        "Framework: pytest + httpx (backend), Vitest + Testing Library (frontend)."
    ),
    "docs": (
        "Documentation complete.\n\n"
        "Files:\n"
        "1. README.md -- project overview, stack, quickstart\n"
        "2. API.md -- endpoint reference with curl examples\n"
        "3. ARCHITECTURE.md -- system design\n"
        "4. COMPONENTS.md -- frontend component tree\n\n"
        "All in Markdown, API docs include request/response examples."
    ),
    "devops": (
        "DevOps configuration complete.\n\n"
        "- Multi-stage Dockerfile (<150MB image)\n"
        "- docker-compose.yml (frontend + backend + db)\n"
        "- GitHub Actions CI: lint -> test -> build -> deploy\n"
        "- Nginx reverse proxy with static asset caching"
    ),
}


class MockAdapter(AgentAdapter):
    """W1 Mock: fixed template or domain-aware subtask reply when no API available."""

    name = "mock"

    def __init__(self, config: Optional[dict[str, Any]] = None) -> None:
        super().__init__(config)
        self.delay_ms: int = int(self.config.get("delay_ms", 20))
        self.reply_template: str = str(self.config.get("reply", DEFAULT_REPLY))
        self.role: str = str(self.config.get("role", "通用助手"))

    async def send(
        self,
        messages: List[dict[str, Any]],
        *,
        tools: Optional[List[dict[str, Any]]] = None,
        artifacts_context: Optional[dict[str, Any]] = None,
        stream: bool = True,
    ) -> AsyncIterator[Chunk]:
        subtask = _detect_subtask(messages)
        if subtask:
            domain = subtask.get("domain", "general")
            full = _DOMAIN_REPLIES.get(domain, f"Subtask for {domain} completed.\n\n{subtask.get('description', '')}")
        else:
            echo = _last_user_text(messages) or "<empty>"
            role_intro = f"（我是 {self.role}）\n" if self.role and self.role != "通用助手" else ""
            full = role_intro + self.reply_template.format(echo=echo)

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
                await asyncio.sleep(delay)

        yield {
            "type": "usage",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        yield {"type": "done"}

    def capabilities(self) -> List[str]:
        return ["text", "mock"]
