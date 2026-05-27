"""Artifact utility functions — code-block extraction, persistence, message content."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select

from db.engine import get_sessionmaker
from db.models import Message as MessageModel
from services import update_message_content
from services.artifact import create_artifact as create_service_artifact
from ws import Connection, event

CODE_BLOCK_RE = re.compile(r"```(\w+)?\n([\s\S]*?)```", re.MULTILINE)


async def try_create_artifact(
    Session, conn: Connection, message_id: str, conversation_id: str, agent_id: str, text: str
) -> dict[str, Any] | None:
    matches = list(CODE_BLOCK_RE.finditer(text))
    if not matches:
        return None

    first_artifact_id: str | None = None
    first_content_payload: dict[str, Any] | None = None

    for idx, m in enumerate(matches):
        lang = (m.group(1) or "text").strip().lower()
        code = m.group(2).strip()
        if not code:
            continue

        title = f"{lang.capitalize()} Block"
        if idx == 0:
            title = f"Code ({lang})"
        elif idx > 0:
            title = f"Code Block {idx + 1} ({lang})"

        kind = "preview" if lang == "html" else "code"
        mime_type = "text/plain"
        ext_map = {
            "python": ("text/x-python", ".py"),
            "javascript": ("text/javascript", ".js"),
            "typescript": ("text/typescript", ".ts"),
            "jsx": ("text/jsx", ".jsx"),
            "tsx": ("text/tsx", ".tsx"),
            "html": ("text/html", ".html"),
            "css": ("text/css", ".css"),
            "json": ("application/json", ".json"),
            "yaml": ("text/yaml", ".yaml"),
            "markdown": ("text/markdown", ".md"),
            "bash": ("text/x-shellscript", ".sh"),
            "sql": ("text/x-sql", ".sql"),
        }
        if lang in ext_map:
            mime_type, ext = ext_map[lang]
            file_name = f"code{ext}"
        else:
            file_name = "code.txt"

        async with Session() as s:
            artifact = await create_service_artifact(
                s,
                conversation_id=conversation_id,
                kind=kind,
                title=title,
                mime_type=mime_type,
                file_name=file_name,
                content=code,
                source_message_id=message_id,
                created_by=agent_id,
                meta={"language": lang},
            )

        if idx == 0:
            first_artifact_id = artifact["id"]
            content_payload = artifact_message_content(artifact)
            first_content_payload = content_payload
            async with Session() as s:
                await update_message_content(s, message_id, content_payload)
                m = await s.scalar(select(MessageModel).where(MessageModel.id == message_id))
                if m:
                    m.artifact_id = first_artifact_id
                    await s.commit()

        await conn.send(
            event(
                "artifact_ready",
                conversation_id=conversation_id,
                artifact=artifact,
                message_id=message_id if idx == 0 else None,
            )
        )

    if first_artifact_id:
        return first_content_payload
    return None


def artifact_message_content(artifact: dict[str, Any]) -> dict[str, Any]:
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
            "applied_artifact_id": artifact["id"],
        }
    return {
        "type": "code",
        **base,
        "fileName": artifact["file_name"] or artifact["title"],
        "language": meta.get("language") or "plaintext",
    }


async def persist_message_content(Session, message_id: str, content: dict[str, Any]) -> None:
    async with Session() as s:
        await update_message_content(s, message_id, content)


async def persist_artifact_chunk(
    Session,
    message_id: str,
    conversation_id: str,
    agent_id: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    kind = str(payload.get("kind") or "file")
    title = str(payload.get("title") or payload.get("file_name") or "Artifact")
    mime_type = str(payload.get("mime_type") or payload.get("mimeType") or "text/plain")
    file_name = payload.get("file_name") or payload.get("fileName")
    content = payload.get("content")
    if content is None:
        content = payload.get("text", "")
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    parent_id = payload.get("parent_id") or payload.get("parentId")

    async with Session() as s:
        artifact = await create_service_artifact(
            s,
            conversation_id=conversation_id,
            kind=kind,
            title=title,
            mime_type=mime_type,
            file_name=str(file_name) if file_name else None,
            content=str(content),
            source_message_id=message_id,
            created_by=agent_id,
            parent_id=str(parent_id) if parent_id else None,
            meta=meta,
        )
        content_payload = artifact_message_content(artifact)
        await update_message_content(s, message_id, content_payload)
        m = await s.scalar(select(MessageModel).where(MessageModel.id == message_id))
        if m:
            m.artifact_id = artifact["id"]
            await s.commit()
    return {"artifact": artifact, "content": content_payload}


async def persist_final(Session, message_id: str, text: str) -> None:
    async with Session() as s:
        await update_message_content(s, message_id, {"type": "text", "text": text})
