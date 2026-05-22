"""REST 端点 — /api/artifacts, /api/upload, /api/preview — F-W4-2 / F-W4-3。

预览卡片 iframe 由 ``/preview/{artifact_id}`` 静态托管。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile
from pydantic import BaseModel

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
from ws import event, hub

router = APIRouter()


# ---------------------------------------------------------------------------
# POST /api/artifacts — create
# ---------------------------------------------------------------------------


class CreateArtifactRequest(BaseModel):
    conversation_id: str
    kind: str  # 'code' | 'preview' | 'file' | 'diff'
    title: str
    mime_type: str
    file_name: Optional[str] = None
    content: str = ""
    parent_id: Optional[str] = None
    source_message_id: Optional[str] = None
    meta: Optional[dict[str, Any]] = None


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

        if body.parent_id and parent_content is not None:
            msg = await create_message(
                s,
                conversation_id=body.conversation_id,
                sender_id=DEFAULT_USER_ID,
                sender_type="user",
                content={
                    "type": "diff",
                    "before": parent_content,
                    "after": body.content,
                    "fileName": body.file_name or body.title,
                    "summary": f"保存 {body.title} 的新版本 v{result['version']}",
                    "applied_artifact_id": result["id"],
                },
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
                message_id=diff_message["id"],
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


def _message_content_for_artifact(artifact: dict[str, Any], content: str) -> dict[str, Any]:
    if artifact["kind"] == "preview":
        return {
            "type": "preview",
            "title": artifact["title"],
            "mimeType": artifact["mime_type"],
            "fileSize": artifact["file_size"],
        }
    if artifact["kind"] == "file":
        return {
            "type": "file",
            "fileName": artifact["file_name"] or artifact["title"],
            "mimeType": artifact["mime_type"],
            "fileSize": artifact["file_size"],
        }
    meta = artifact.get("meta") or {}
    return {
        "type": "code",
        "title": artifact["title"],
        "code": content,
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
            raise HTTPException(409, "artifact_conflict")

        current = await read_artifact_content_with_session(s, base_artifact_id)
        if current is None:
            raise HTTPException(404, "artifact content not found")
        if current != body.before:
            raise HTTPException(409, "artifact_conflict")

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
            content=_message_content_for_artifact(new_artifact, body.after),
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
    from fastapi.responses import HTMLResponse, Response

    Session = get_sessionmaker()
    async with Session() as s:
        a = await get_artifact(s, artifact_id)
        if a is None:
            raise HTTPException(404, "artifact not found")

        content = await read_artifact_content_with_session(s, artifact_id)
        if content is None:
            raise HTTPException(404, "content not found")

        return Response(
            content=content,
            media_type=a.get("mime_type", "text/plain"),
            headers={
                "X-Artifact-Id": a["id"],
                "X-Artifact-Version": str(a.get("version", 1)),
            },
        )
