"""Orchestrator debug telemetry (HTML preview truncation investigation).

Only activates when ``.dbg/html-preview-truncation.env`` is present.
"""TODO: remove before答辩 — debug telemetry should not ship to production.

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib import request

DEBUG_ENV_PATH = Path(__file__).resolve().parent.parent / ".dbg" / "html-preview-truncation.env"


def _debug_event(hypothesis_id: str, point: str, payload: dict[str, Any]) -> None:
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


def _html_probe(text: str | None) -> dict[str, Any]:
    from orchestrator.preview import _is_complete_html_document, _looks_like_html

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
