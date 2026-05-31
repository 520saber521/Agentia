"""REST 端点 — /api/artifacts, /api/upload, /api/preview — F-W4-2 / F-W4-3。

预览卡片 iframe 由 ``/preview/{artifact_id}`` 静态托管。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib import request
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, field_validator

from db import DEFAULT_USER_ID
from db.engine import get_sessionmaker
from services.artifact import (
    ARTIFACTS_DIR,
    artifact_has_child_version,
    create_artifact,
    get_artifact,
    list_artifact_history,
    list_artifacts,
    read_artifact_content_with_session,
)
from services.conversation import get_conversation
from services.message import create_message, message_to_dict
from difflib import unified_diff
from ws import event, hub

router = APIRouter()
DEBUG_ENV_PATH = Path(__file__).resolve().parents[2] / ".dbg" / "html-preview-truncation.env"


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


def _content_probe(content: str | None) -> dict[str, Any]:
    #region debug-point html-preview-truncation
    value = content or ""
    lower = value.lower()
    return {
        "length": len(value),
        "starts_with_doctype": lower.lstrip().startswith("<!doctype html"),
        "doctype_pos": lower.find("<!doctype html"),
        "html_pos": lower.find("<html"),
        "closing_html_pos": lower.rfind("</html>"),
        "has_fence": "```" in value,
        "head": value[:180],
        "tail": value[-180:],
    }
    #endregion debug-point html-preview-truncation


def _is_complete_html(content: str | None) -> bool:
    value = content or ""
    lower = value.lower()
    return (
        ("<!doctype html" in lower or "<html" in lower)
        and "<body" in lower
        and "</body>" in lower
        and "</html>" in lower
        and not lower.lstrip().startswith("<!doctype html>\n```")
    )


def _invalid_preview_html(artifact_id: str) -> str:
    safe_id = artifact_id.replace("<", "").replace(">", "")
    return f"""<!doctype html>
<html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>预览内容不完整</title><style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#111827;color:#f9fafb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif}}main{{max-width:680px;padding:32px;border-radius:24px;background:#1f2937;box-shadow:0 24px 80px rgba(0,0,0,.35)}}h1{{margin:0 0 12px;font-size:28px}}p{{line-height:1.8;color:#d1d5db}}code{{color:#93c5fd}}</style></head><body><main><h1>预览内容不完整</h1><p>该历史产物的 HTML 在生成时被截断，已阻止直接渲染残缺源码。</p><p>Artifact：<code>{safe_id}</code></p><p>请重新让 Orchestrator/Frontend Agent 生成一次；新生成的预览会校验完整 HTML 后再保存。</p></main></body></html>"""


# ---------------------------------------------------------------------------
# POST /api/artifacts — create
# ---------------------------------------------------------------------------


class CreateArtifactRequest(BaseModel):
    conversation_id: str
    kind: str
    title: str
    mime_type: str
    file_name: Optional[str] = None
    content: str = ""
    parent_id: Optional[str] = None
    source_message_id: Optional[str] = None
    meta: Optional[dict[str, Any]] = None

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value: str) -> str:
        if value not in {"code", "preview", "file", "diff"}:
            raise ValueError("invalid_content")
        return value

    @field_validator("conversation_id", "title", "mime_type")
    @classmethod
    def validate_required_string(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("invalid_content")
        return value


class ApplyDiffRequest(BaseModel):
    before: str
    after: str
    summary: Optional[str] = None
    file_name: Optional[str] = None
    source_message_id: Optional[str] = None


@router.post("/api/artifacts", status_code=201)
@router.post("/artifacts", status_code=201)
async def api_create_artifact(body: CreateArtifactRequest) -> dict[str, Any]:
    Session = get_sessionmaker()
    diff_message: dict[str, Any] | None = None
    async with Session() as s:
        parent_content: str | None = None
        if body.parent_id:
            parent = await get_artifact(s, body.parent_id)
            if parent is None:
                raise HTTPException(404, "parent artifact not found")
            parent_content = await read_artifact_content_with_session(s, body.parent_id)
            if parent_content is None:
                raise HTTPException(404, "parent artifact content not found")

        result = await create_artifact(
            s,
            conversation_id=body.conversation_id,
            kind=body.kind,
            title=body.title,
            mime_type=body.mime_type,
            file_name=body.file_name,
            content=body.content,
            source_message_id=body.source_message_id,
            created_by=DEFAULT_USER_ID,
            parent_id=body.parent_id,
            meta=body.meta,
        )
        _debug_event("H1", "artifact_created", {
            "artifact_id": result["id"],
            "kind": body.kind,
            "mime_type": body.mime_type,
            "file_name": body.file_name,
            **_content_probe(body.content),
        })

        if not body.parent_id:
            msg = await create_message(
                s,
                conversation_id=body.conversation_id,
                sender_id=DEFAULT_USER_ID,
                sender_type="user",
                content=_message_content_for_artifact(result),
                artifact_id=result["id"],
            )
            diff_message = message_to_dict(msg)
        elif body.parent_id and parent_content is not None:
            msg = await create_message(
                s,
                conversation_id=body.conversation_id,
                sender_id=DEFAULT_USER_ID,
                sender_type="user",
                content=_version_message_content(parent, result, parent_content, body.content),
                artifact_id=result["id"],
            )
            diff_message = message_to_dict(msg)

    if diff_message is not None:
        await hub.broadcast_conversation(
            body.conversation_id,
            event("message_created", message=diff_message),
        )
    await hub.broadcast_conversation(
        body.conversation_id,
        event(
            "artifact_ready",
            conversation_id=body.conversation_id,
            artifact=result,
            message_id=diff_message["id"] if diff_message is not None else None,
        ),
    )

    return {"artifact": result, "message": diff_message}


# ---------------------------------------------------------------------------
# GET /api/artifacts/{id}
# ---------------------------------------------------------------------------


@router.get("/api/artifacts/{artifact_id}")
@router.get("/artifacts/{artifact_id}")
async def api_get_artifact(artifact_id: str) -> dict[str, Any]:
    Session = get_sessionmaker()
    async with Session() as s:
        a = await get_artifact(s, artifact_id)
        if a is None:
            raise HTTPException(404, "artifact not found")
        return {"artifact": a}


# ---------------------------------------------------------------------------
# GET /api/artifacts/{id}/content
# ---------------------------------------------------------------------------


@router.get("/api/artifacts/{artifact_id}/content")
@router.get("/artifacts/{artifact_id}/content")
async def api_get_artifact_content(artifact_id: str) -> dict[str, str]:
    Session = get_sessionmaker()
    async with Session() as s:
        content = await read_artifact_content_with_session(s, artifact_id)
        if content is None:
            raise HTTPException(404, "artifact content not found")
        return {"content": content}


# ---------------------------------------------------------------------------
# GET /api/artifacts/{id}/history
# ---------------------------------------------------------------------------


@router.get("/api/artifacts/{artifact_id}/history")
@router.get("/artifacts/{artifact_id}/history")
async def api_artifact_history(artifact_id: str) -> dict[str, Any]:
    Session = get_sessionmaker()
    async with Session() as s:
        history = await list_artifact_history(s, artifact_id)
        if not history:
            raise HTTPException(404, "artifact not found")
        return {"artifact_id": artifact_id, "history": history}


# ---------------------------------------------------------------------------
# POST /api/artifacts/{id}/apply-diff — F-W4-5
# ---------------------------------------------------------------------------


def _version_message_content(
    parent: dict[str, Any],
    artifact: dict[str, Any],
    before: str,
    after: str,
) -> dict[str, Any]:
    meta = artifact.get("meta") or {}
    file_name = artifact.get("file_name") or parent.get("file_name") or artifact["title"]
    diff = "\n".join(
        unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"{file_name}@v{parent.get('version', 1)}",
            tofile=f"{file_name}@v{artifact.get('version', 1)}",
            lineterm="",
        )
    )
    return {
        "type": "diff",
        "artifact_id": artifact["id"],
        "title": artifact["title"],
        "mimeType": artifact["mime_type"],
        "fileSize": artifact["file_size"],
        "url": artifact.get("url"),
        "previewUrl": artifact.get("preview_url"),
        "version": artifact.get("version", 1),
        "fileName": file_name,
        "summary": meta.get("diff_summary") or "产物版本变更",
        "diff": diff,
        "base_artifact_id": parent["id"],
        "applied_artifact_id": artifact["id"],
    }


def _message_content_for_artifact(artifact: dict[str, Any], content: str = "") -> dict[str, Any]:
    meta = artifact.get("meta") or {}
    base = {
        "artifact_id": artifact["id"],
        "title": artifact["title"],
        "mimeType": artifact["mime_type"],
        "fileSize": artifact["file_size"],
        "url": artifact.get("url"),
        "previewUrl": artifact.get("preview_url"),
        "version": artifact.get("version", 1),
    }
    if artifact["kind"] == "preview":
        return {"type": "preview", **base}
    if artifact["kind"] == "file":
        return {
            "type": "file",
            **base,
            "fileName": artifact["file_name"] or artifact["title"],
        }
    if artifact["kind"] == "diff":
        return {
            "type": "diff",
            **base,
            "fileName": artifact["file_name"] or artifact["title"],
            "summary": meta.get("diff_summary") or "产物版本变更",
            "base_artifact_id": artifact.get("parent_id"),
            "applied_artifact_id": artifact["id"],
        }
    return {
        "type": "code",
        **base,
        "fileName": artifact["file_name"] or artifact["title"],
        "language": meta.get("language") or "plaintext",
    }


@router.post("/api/artifacts/{base_artifact_id}/apply-diff")
@router.post("/artifacts/{base_artifact_id}/apply-diff")
async def api_apply_diff(
    base_artifact_id: str, body: ApplyDiffRequest
) -> dict[str, Any]:
    Session = get_sessionmaker()
    async with Session() as s:
        base = await get_artifact(s, base_artifact_id)
        if base is None:
            raise HTTPException(404, "artifact not found")

        if await artifact_has_child_version(s, base_artifact_id):
            raise HTTPException(status_code=409, detail="artifact_conflict")

        current = await read_artifact_content_with_session(s, base_artifact_id)
        if current is None:
            raise HTTPException(404, "artifact content not found")
        if current != body.before:
            raise HTTPException(status_code=409, detail="artifact_conflict")

        new_artifact = await create_artifact(
            s,
            conversation_id=base["conversation_id"],
            kind=base["kind"],
            title=base["title"],
            mime_type=base["mime_type"],
            file_name=body.file_name or base["file_name"],
            content=body.after,
            source_message_id=body.source_message_id,
            created_by=DEFAULT_USER_ID,
            parent_id=base_artifact_id,
            meta={
                **(base.get("meta") or {}),
                "applied_from": "diff",
                "diff_summary": body.summary or "",
            },
        )

        msg = await create_message(
            s,
            conversation_id=base["conversation_id"],
            sender_id=DEFAULT_USER_ID,
            sender_type="user",
            content=_version_message_content(base, new_artifact, current, body.after),
            artifact_id=new_artifact["id"],
        )
        message = message_to_dict(msg)

    await hub.broadcast_conversation(
        base["conversation_id"],
        event("message_created", message=message),
    )
    await hub.broadcast_conversation(
        base["conversation_id"],
        event(
            "artifact_ready",
            conversation_id=base["conversation_id"],
            artifact=new_artifact,
            message_id=message["id"],
        ),
    )
    return {"artifact": new_artifact, "message": message}


# ---------------------------------------------------------------------------
# GET /api/conversations/{conv_id}/artifacts
# ---------------------------------------------------------------------------


@router.get("/api/conversations/{conv_id}/artifacts")
@router.get("/conversations/{conv_id}/artifacts")
async def api_list_conv_artifacts(
    conv_id: str,
    kind: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    Session = get_sessionmaker()
    async with Session() as s:
        items = await list_artifacts(s, conv_id, kind=kind, limit=limit)
    return {"conversation_id": conv_id, "artifacts": items, "limit": limit}


# ---------------------------------------------------------------------------
# POST /api/upload — multipart file upload (F-W4-6)
# ---------------------------------------------------------------------------


@router.post("/api/upload", status_code=201)
@router.post("/upload", status_code=201)
async def api_upload(
    file: UploadFile,
    conversation_id: str = Query(),
    title: Optional[str] = Query(default=None),
    source_message_id: Optional[str] = Query(default=None),
) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(400, "file name required")

    content_bytes = await file.read()
    content = content_bytes.decode("utf-8", errors="replace")
    mime = file.content_type or "application/octet-stream"

    Session = get_sessionmaker()
    async with Session() as s:
        result = await create_artifact(
            s,
            conversation_id=conversation_id,
            kind="file",
            title=title or file.filename or "untitled",
            mime_type=mime,
            file_name=file.filename or "untitled",
            content=content,
            source_message_id=source_message_id,
            created_by=DEFAULT_USER_ID,
        )
    return {"artifact": result}


# ---------------------------------------------------------------------------
# GET /preview/{artifact_id} — iframe 预览静态托管 (F-W4-3)
# ---------------------------------------------------------------------------


@router.get("/preview/{artifact_id}")
async def api_preview(artifact_id: str) -> Any:
    """Serve artifact content as-is for iframe embedding."""
    Session = get_sessionmaker()
    async with Session() as s:
        a = await get_artifact(s, artifact_id)
        if a is None:
            raise HTTPException(404, "artifact not found")

        content = await read_artifact_content_with_session(s, artifact_id)
        if content is None:
            raise HTTPException(404, "content not found")

        _debug_event("H3", "preview_served", {
            "artifact_id": artifact_id,
            "kind": a.get("kind"),
            "mime_type": a.get("mime_type"),
            "file_size": a.get("file_size"),
            **_content_probe(content),
        })
        media_type = a.get("mime_type", "text/plain")
        if "html" in str(media_type).lower() and not _is_complete_html(content):
            _debug_event("H3", "preview_blocked_incomplete_html", {
                "artifact_id": artifact_id,
                "kind": a.get("kind"),
                "mime_type": media_type,
                **_content_probe(content),
            })
            content = _invalid_preview_html(artifact_id)
            media_type = "text/html"
        return Response(
            content=content,
            media_type=media_type,
            headers={
                "X-Artifact-Id": a["id"],
                "X-Artifact-Version": str(a.get("version", 1)),
                "Cache-Control": "no-store",
            },
        )
