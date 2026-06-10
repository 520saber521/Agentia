"""Workspace REST 端点 — 文件树浏览与工作区配置。

GET  /api/conversations/{id}/workspace/tree  — 递归文件树
GET  /api/conversations/{id}/workspace/file  — 读取文件内容
POST /api/conversations/{id}/workspace       — 设置 workspace 路径
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from db.engine import get_sessionmaker
from db.models import Conversation
from sqlalchemy import select

router = APIRouter(prefix="/api", tags=["workspace"])

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_WORKSPACES_DIR = _PROJECT_ROOT / "workspaces"

# Directories to skip during tree scan
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".agenthub", ".codex_team", ".idea", ".vscode", "__pycache__", ".pytest_cache", ".mypy_cache", ".tox", "dist", "build", ".next", ".nuxt", ".agent_runs"}

MAX_DEPTH = 4
MAX_CHILDREN = 200


def _resolve_workspace_root(conversation_id: str, workspace_path: str | None) -> Path:
    """Resolve a conversation's workspace root directory.

    Defaults to a per-conversation directory under workspaces/, so each
    conversation has its own isolated file area that all agents in that
    conversation can share.
    """
    if workspace_path:
        root = Path(workspace_path)
        if not root.is_absolute():
            root = _PROJECT_ROOT / root
    else:
        root = _WORKSPACES_DIR / conversation_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def _build_file_tree(
    root: Path,
    rel_path: str = "",
    depth: int = 0,
    entry_count: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Recursively build a file tree dict from a directory path."""
    if entry_count is None:
        entry_count = [0]
    if depth > MAX_DEPTH:
        return []

    full = root / rel_path if rel_path else root
    entries: list[dict[str, Any]] = []

    try:
        with os.scandir(full) as it:
            dirs: list[dict[str, Any]] = []
            files: list[dict[str, Any]] = []

            for entry in it:
                if entry_count[0] >= MAX_CHILDREN:
                    break
                if entry.name.startswith(".") and entry.name not in (".env", ".gitignore", ".env.example"):
                    continue
                if entry.is_dir():
                    if entry.name in _SKIP_DIRS:
                        continue
                    entry_count[0] += 1
                    child_rel = f"{rel_path}/{entry.name}" if rel_path else entry.name
                    children = _build_file_tree(root, child_rel, depth + 1, entry_count)
                    dirs.append({
                        "name": entry.name,
                        "type": "directory",
                        "path": child_rel,
                        "size": 0,
                        "children": children,
                        "modified_at": entry.stat().st_mtime,
                    })
                else:
                    try:
                        stat = entry.stat()
                    except OSError:
                        stat = None
                    entry_count[0] += 1
                    child_rel = f"{rel_path}/{entry.name}" if rel_path else entry.name
                    files.append({
                        "name": entry.name,
                        "type": "file",
                        "path": child_rel,
                        "size": stat.st_size if stat else 0,
                        "children": None,
                        "modified_at": stat.st_mtime if stat else None,
                    })

            dirs.sort(key=lambda d: d["name"].lower())
            files.sort(key=lambda f: f["name"].lower())
            entries = dirs + files

    except (PermissionError, OSError):
        pass
    except Exception:
        pass

    return entries


# ---------------------------------------------------------------------------
# GET /api/conversations/{conversation_id}/workspace/tree
# ---------------------------------------------------------------------------


class SetWorkspaceBody(BaseModel):
    path: str = ""


@router.get("/conversations/{conversation_id}/workspace/tree")
async def api_workspace_tree(
    conversation_id: str,
    path: str = Query(default=""),
) -> dict[str, Any]:
    Session = get_sessionmaker()
    async with Session() as s:
        conv = await s.scalar(select(Conversation).where(Conversation.id == conversation_id))
        if conv is None:
            raise HTTPException(404, "conversation not found")

    root = _resolve_workspace_root(conversation_id, conv.workspace_path)
    tree = _build_file_tree(root, path)
    return {
        "conversation_id": conversation_id,
        "root_path": str(root),
        "path": path,
        "tree": tree,
    }


# ---------------------------------------------------------------------------
# GET /api/conversations/{conversation_id}/workspace/file
# ---------------------------------------------------------------------------


@router.get("/conversations/{conversation_id}/workspace/file")
async def api_workspace_file(
    conversation_id: str,
    path: str = Query(min_length=1),
    encoding: str = Query(default="utf-8"),
) -> dict[str, Any]:
    Session = get_sessionmaker()
    async with Session() as s:
        conv = await s.scalar(select(Conversation).where(Conversation.id == conversation_id))
        if conv is None:
            raise HTTPException(404, "conversation not found")

    root = _resolve_workspace_root(conversation_id, conv.workspace_path)
    full_path = (root / path).resolve()

    # Security: ensure path is within workspace root
    try:
        full_path.relative_to(root.resolve())
    except ValueError:
        raise HTTPException(403, "path outside workspace")

    if not full_path.exists():
        raise HTTPException(404, "file not found")
    if full_path.is_dir():
        raise HTTPException(400, "path is a directory")

    size = full_path.stat().st_size
    if size > 1_048_576:  # 1MB limit
        raise HTTPException(413, "file too large (>1MB)")

    try:
        content = full_path.read_text(encoding=encoding)
    except UnicodeDecodeError:
        # Try reading as binary and return base64 indicator
        raise HTTPException(415, "binary file — preview not supported")

    # Guess mime type from extension
    ext = full_path.suffix.lower()
    MIME_MAP = {
        ".py": "text/x-python",
        ".js": "application/javascript",
        ".ts": "application/typescript",
        ".tsx": "application/typescript",
        ".jsx": "application/javascript",
        ".html": "text/html",
        ".css": "text/css",
        ".json": "application/json",
        ".md": "text/markdown",
        ".txt": "text/plain",
        ".yaml": "text/yaml",
        ".yml": "text/yaml",
        ".xml": "text/xml",
        ".sql": "text/x-sql",
        ".sh": "text/x-shellscript",
        ".bat": "text/x-batch",
        ".ps1": "text/x-powershell",
        ".toml": "text/toml",
        ".ini": "text/plain",
        ".cfg": "text/plain",
        ".env": "text/plain",
        ".gitignore": "text/plain",
        ".dockerfile": "text/plain",
        ".dockerignore": "text/plain",
        ".csv": "text/csv",
        ".log": "text/plain",
    }
    mime = MIME_MAP.get(ext, "text/plain")

    return {
        "path": path,
        "content": content,
        "size": size,
        "mime_type": mime,
    }


# ---------------------------------------------------------------------------
# POST /api/conversations/{conversation_id}/workspace
# ---------------------------------------------------------------------------


@router.post("/conversations/{conversation_id}/workspace")
async def api_set_workspace(
    conversation_id: str,
    body: SetWorkspaceBody,
) -> dict[str, Any]:
    """Set or change the workspace path for a conversation."""
    new_path = body.path.strip()
    Session = get_sessionmaker()
    async with Session() as s:
        conv = await s.scalar(select(Conversation).where(Conversation.id == conversation_id))
        if conv is None:
            raise HTTPException(404, "conversation not found")

        if new_path:
            # Validate the path exists and is a directory
            target = Path(new_path)
            if not target.is_absolute():
                target = _PROJECT_ROOT / target
            target = target.resolve()
            if not target.exists():
                raise HTTPException(400, f"path does not exist: {target}")
            if not target.is_dir():
                raise HTTPException(400, f"path is not a directory: {target}")
            conv.workspace_path = str(target)
        else:
            conv.workspace_path = None

        conv.updated_at = int(time.time() * 1000)
        await s.commit()

        root = _resolve_workspace_root(conversation_id, conv.workspace_path)
        tree = _build_file_tree(root)

    return {
        "conversation_id": conversation_id,
        "workspace_path": str(root),
        "tree": tree,
    }
