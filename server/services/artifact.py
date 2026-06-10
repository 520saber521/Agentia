"""Artifact CRUD + 版本链 — F-W4-2。

所有"可被预览 / 编辑 / 下载"的对象（代码、网页、文件、Diff 等）
都落在这里，消息 content 只存 artifact_id + 预览元数据。

本地 FS 布局（``server/.agenthub/artifacts/``）:
  artifacts/{conversation_id}/{artifact_id}/v{version}/{file_name}
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Artifact, now_ms, new_id

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / ".agenthub" / "artifacts"


def _ensure_dir(conv_id: str, artifact_id: str, version: int) -> Path:
    p = ARTIFACTS_DIR / conv_id / artifact_id / f"v{version}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _format_css(text: str) -> str:
    """Break single-line CSS into multi-line with proper indentation."""
    result = []
    i = 0
    n = len(text)
    buf = ""
    brace_depth = 0
    in_comment = False
    while i < n:
        ch = text[i]
        if in_comment:
            buf += ch
            if ch == "*" and i + 1 < n and text[i + 1] == "/":
                buf += text[i + 1]
                i += 2
                in_comment = False
                continue
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            in_comment = True
            buf += ch
            i += 1
            continue
        if ch == "{":
            buf = buf.rstrip()
            if buf:
                result.append("  " * brace_depth + buf)
            result.append("  " * brace_depth + "{")
            brace_depth += 1
            buf = ""
            i += 1
            continue
        if ch == "}":
            buf = buf.rstrip()
            if buf:
                result.append("  " * brace_depth + buf + ";")
            brace_depth = max(0, brace_depth - 1)
            result.append("  " * brace_depth + "}")
            buf = ""
            i += 1
            continue
        if ch == ";":
            buf = buf.strip()
            if buf:
                result.append("  " * brace_depth + buf + ";")
            buf = ""
            i += 1
            continue
        if ch == "\n" or ch == "\r":
            buf = buf.strip()
            if buf:
                result.append("  " * brace_depth + buf)
            buf = ""
            i += 1
            continue
        buf += ch
        i += 1
    buf = buf.strip()
    if buf:
        result.append(buf)
    return "\n".join(result)


def _format_js(text: str) -> str:
    """Break single-line JS into multi-line with basic formatting."""
    result = []
    i = 0
    n = len(text)
    buf = ""
    in_string = False
    string_char = ""
    in_tpl = False
    in_comment_line = False
    in_comment_block = False
    brace_depth = 0

    while i < n:
        ch = text[i]
        if in_comment_line:
            buf += ch
            if ch == "\n":
                in_comment_line = False
            i += 1
            continue
        if in_comment_block:
            buf += ch
            if ch == "*" and i + 1 < n and text[i + 1] == "/":
                buf += text[i + 1]
                i += 2
                in_comment_block = False
                continue
            i += 1
            continue
        if ch == "/" and i + 1 < n:
            if text[i + 1] == "/":
                in_comment_line = True
                buf += ch
                i += 1
                continue
            if text[i + 1] == "*":
                in_comment_block = True
                buf += ch
                i += 1
                continue
        if ch == "`" and not in_string:
            in_tpl = not in_tpl
            buf += ch
            i += 1
            continue
        if (ch == '"' or ch == "'") and not in_tpl:
            if not in_string:
                in_string = True
                string_char = ch
            elif ch == string_char and (i == 0 or text[i - 1] != "\\"):
                in_string = False
            buf += ch
            i += 1
            continue
        if in_string or in_tpl:
            buf += ch
            i += 1
            continue
        if ch == "{":
            buf = buf.rstrip()
            if buf:
                result.append("  " * brace_depth + buf)
            result.append("  " * brace_depth + "{")
            brace_depth += 1
            buf = ""
            i += 1
            continue
        if ch == "}":
            buf = buf.rstrip()
            if buf:
                result.append("  " * brace_depth + buf)
            brace_depth -= 1
            result.append("  " * brace_depth + "}")
            buf = ""
            i += 1
            continue
        if ch == ";":
            buf = buf.rstrip()
            if buf:
                result.append("  " * brace_depth + buf + ";")
            buf = ""
            i += 1
            continue
        if ch == "\n" or ch == "\r":
            buf = buf.strip()
            if buf:
                result.append("  " * brace_depth + buf)
            buf = ""
            i += 1
            continue
        buf += ch
        i += 1
    buf = buf.strip()
    if buf:
        result.append(buf)
    return "\n".join(result)


def _format_html_content(text: str) -> str:
    if len(text) < 200:
        return text
    lower = text.lower()
    if "<!doctype html" not in lower and "<html" not in lower:
        return text

    NO_INDENT = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
    INDENT_TAGS = {
        "html", "head", "body", "div", "section", "article", "header",
        "footer", "nav", "main", "aside", "ul", "ol", "li", "table",
        "thead", "tbody", "tr", "th", "td", "form", "fieldset", "select",
        "option", "details", "summary", "figure", "figcaption", "blockquote",
        "pre", "code", "video", "audio", "canvas", "svg", "a", "p",
        "h1", "h2", "h3", "h4", "h5", "h6", "span", "button", "label",
        "iframe", "dl", "dt", "dd", "menu", "template", "dialog",
    }
    result = []
    indent = 0
    INDENT_SIZE = 2
    i = 0
    n = len(text)
    in_style = False
    in_script = False
    in_pre = False
    style_buf = ""
    script_buf = ""
    line_buffer = ""

    while i < n:
        ch = text[i]
        if ch == "<":
            rest = text[i:]
            if rest.startswith("<!--"):
                end = text.find("-->", i)
                if end == -1:
                    result.append(text[i:])
                    break
                if line_buffer.strip():
                    result.append(" " * (indent * INDENT_SIZE) + line_buffer.rstrip())
                result.append(" " * (indent * INDENT_SIZE) + text[i:end + 3])
                line_buffer = ""
                i = end + 3
                continue
            if rest.startswith("<!doctype") or rest.startswith("<!DOCTYPE"):
                end = text.find(">", i)
                if end == -1:
                    result.append(text[i:])
                    break
                result.append(text[i:end + 1])
                i = end + 1
                continue
            if rest.startswith("</"):
                end = text.find(">", i)
                if end == -1:
                    result.append(text[i:])
                    break
                tag = text[i:end + 1]
                tag_name = re.match(r'</(\w+)', tag)
                name = tag_name.group(1).lower() if tag_name else ""
                if name == "style":
                    in_style = False
                    formatted = _format_css(style_buf)
                    for line in formatted.split("\n"):
                        result.append(" " * (indent * INDENT_SIZE) + line)
                    style_buf = ""
                elif name == "script":
                    in_script = False
                    formatted = _format_js(script_buf)
                    for line in formatted.split("\n"):
                        result.append(" " * (indent * INDENT_SIZE) + line)
                    script_buf = ""
                elif name == "pre":
                    in_pre = False
                if name in INDENT_TAGS and indent > 0:
                    indent -= 1
                if line_buffer.strip():
                    result.append(" " * (indent * INDENT_SIZE) + line_buffer.rstrip())
                result.append(" " * (indent * INDENT_SIZE) + tag)
                line_buffer = ""
                i = end + 1
                continue
            end = text.find(">", i)
            if end == -1:
                result.append(text[i:])
                break
            tag = text[i:end + 1]
            is_self_closing = tag.endswith("/>")
            tag_match = re.match(r'<(\w+)', tag)
            name = tag_match.group(1).lower() if tag_match else ""
            if name == "style":
                in_style = True
                style_buf = ""
            elif name == "script":
                in_script = True
                script_buf = ""
            elif name == "pre":
                in_pre = True
            if line_buffer.strip():
                result.append(" " * (indent * INDENT_SIZE) + line_buffer.rstrip())
            if is_self_closing or name in NO_INDENT:
                result.append(" " * (indent * INDENT_SIZE) + tag)
            else:
                result.append(" " * (indent * INDENT_SIZE) + tag)
                if name in INDENT_TAGS:
                    indent += 1
            line_buffer = ""
            i = end + 1
        elif in_style:
            style_buf += ch
            i += 1
        elif in_script:
            script_buf += ch
            i += 1
        elif not in_pre and ch == "\n":
            if line_buffer.strip():
                result.append(" " * (indent * INDENT_SIZE) + line_buffer.rstrip())
            line_buffer = ""
            i += 1
        else:
            line_buffer += ch
            i += 1

    if line_buffer.strip():
        result.append(" " * (indent * INDENT_SIZE) + line_buffer.rstrip())
    return "\n".join(line for line in result if line is not None)


def artifact_to_dict(a: Artifact) -> dict[str, Any]:
    return {
        "id": a.id,
        "conversation_id": a.conversation_id,
        "parent_id": a.parent_id,
        "kind": a.kind,
        "title": a.title,
        "mime_type": a.mime_type,
        "file_name": a.file_name,
        "file_size": a.file_size,
        "storage_path": a.storage_path,
        "url": f"/api/artifacts/{a.id}/content",
        "preview_url": f"/preview/{a.id}",
        "source_message_id": a.source_message_id,
        "created_by": a.created_by,
        "meta": json.loads(a.meta) if isinstance(a.meta, str) else a.meta,
        "version": a.version,
        "created_at": a.created_at,
    }


async def create_artifact(
    s: AsyncSession,
    *,
    conversation_id: str,
    kind: str,
    title: str,
    mime_type: str,
    file_name: Optional[str] = None,
    content: str = "",
    source_message_id: Optional[str] = None,
    created_by: str = "system",
    parent_id: Optional[str] = None,
    meta: Optional[dict[str, Any]] = None,
) -> Artifact:
    """Create an artifact record + write content to disk.

    If ``parent_id`` is provided, this becomes a new version.
    """
    ts = now_ms()
    artifact_id = new_id("art")

    # Determine version and storage path
    version = 1
    if parent_id:
        parent = await s.get(Artifact, parent_id)
        if parent:
            version = parent.version + 1

    # Build storage path
    dir_path = _ensure_dir(conversation_id, artifact_id, version)
    if file_name:
        storage_file = dir_path / file_name
    else:
        storage_file = dir_path / "content"

    if "html" in (mime_type or "").lower() and content:
        content = content.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t").replace("\\\"", "\"").replace("\\'", "'")

    storage_file.write_text(content, encoding="utf-8")

    storage_path = f"{conversation_id}/{artifact_id}/v{version}/{storage_file.name}"

    a = Artifact(
        id=artifact_id,
        conversation_id=conversation_id,
        parent_id=parent_id,
        kind=kind,
        title=title,
        mime_type=mime_type,
        file_name=file_name,
        file_size=len(content.encode("utf-8")),
        storage_path=storage_path,
        source_message_id=source_message_id,
        created_by=created_by,
        meta=json.dumps(meta or {}, ensure_ascii=False),
        version=version,
        created_at=ts,
    )
    s.add(a)
    await s.commit()
    return artifact_to_dict(a)


async def get_artifact(
    s: AsyncSession, artifact_id: str
) -> Optional[dict[str, Any]]:
    a = await s.get(Artifact, artifact_id)
    return artifact_to_dict(a) if a else None


async def read_artifact_content(artifact_id: str) -> Optional[str]:
    """Read artifact content from disk."""
    stmt = select(Artifact).where(Artifact.id == artifact_id)
    # We need a session for this — callers should provide one
    raise NotImplementedError("Use read_artifact_content_with_session")


async def read_artifact_content_with_session(
    s: AsyncSession, artifact_id: str
) -> Optional[str]:
    """Read artifact content from disk using an existing session."""
    a = await s.get(Artifact, artifact_id)
    if a is None:
        return None
    p = ARTIFACTS_DIR / a.storage_path
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


async def artifact_has_child_version(s: AsyncSession, artifact_id: str) -> bool:
    """Return true when another artifact already uses this one as parent."""
    child = await s.scalar(
        select(Artifact.id).where(Artifact.parent_id == artifact_id).limit(1)
    )
    return child is not None


async def list_artifacts(
    s: AsyncSession,
    conversation_id: str,
    *,
    kind: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List artifacts for a conversation, newest first."""
    stmt = (
        select(Artifact)
        .where(Artifact.conversation_id == conversation_id)
        .order_by(desc(Artifact.created_at))
        .limit(limit)
    )
    if kind:
        stmt = stmt.where(Artifact.kind == kind)
    rows = (await s.scalars(stmt)).all()
    return [artifact_to_dict(a) for a in rows]


async def list_artifact_history(
    s: AsyncSession, artifact_id: str
) -> list[dict[str, Any]]:
    """沿 parent_id 返回完整版本链，从最旧到最新。"""
    target = await s.get(Artifact, artifact_id)
    if target is None:
        return []

    chain: list[Artifact] = []
    current = target
    while current is not None:
        chain.append(current)
        if current.parent_id is None:
            break
        current = await s.get(Artifact, current.parent_id)

    root = chain[-1]
    ordered: list[Artifact] = [root]
    current_id: Optional[str] = root.id
    visited = {root.id}

    while current_id:
        child = await s.scalar(
            select(Artifact)
            .where(Artifact.parent_id == current_id)
            .order_by(Artifact.created_at.asc(), Artifact.version.asc())
            .limit(1)
        )
        if child is None or child.id in visited:
            break
        ordered.append(child)
        visited.add(child.id)
        current_id = child.id

    return [artifact_to_dict(a) for a in ordered]


async def delete_artifact(s: AsyncSession, artifact_id: str) -> bool:
    """Delete artifact record (FS cleanup is best-effort)."""
    a = await s.get(Artifact, artifact_id)
    if a is None:
        return False
    # Best-effort FS cleanup
    p = ARTIFACTS_DIR / a.storage_path
    try:
        if p.exists():
            p.unlink()
    except OSError:
        pass
    await s.delete(a)
    await s.commit()
    return True
