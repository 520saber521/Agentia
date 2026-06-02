"""Deploy preview serving — serves built project output via HTTP.

GET /deploy/preview/{conversation_id}/              → index.html
GET /deploy/preview/{conversation_id}/{path:path}   → static asset or SPA fallback
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/deploy", tags=["deploy"])

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_WORKSPACES_DIR = _PROJECT_ROOT / "workspaces"

_BUILD_DIRS = ("dist", "build", ".next", "out")


def _resolve_deploy_root(conversation_id: str) -> Path:
    ws_dir = _WORKSPACES_DIR / conversation_id
    if not ws_dir.is_dir():
        return ws_dir / "dist"

    for build_dir in _BUILD_DIRS:
        candidate = ws_dir / build_dir
        if candidate.is_dir():
            return candidate

    return ws_dir / "dist"


@router.get("/preview/{conversation_id}/{path:path}")
@router.get("/preview/{conversation_id}/")
@router.get("/preview/{conversation_id}")
async def deploy_preview(
    conversation_id: str,
    path: str = "index.html",
) -> FileResponse:
    deploy_root = _resolve_deploy_root(conversation_id)

    if not deploy_root.is_dir():
        raise HTTPException(
            404,
            f"No build output found for conversation {conversation_id}. Run a build first.",
        )

    file_path = (deploy_root / path).resolve()
    try:
        file_path.relative_to(deploy_root.resolve())
    except ValueError:
        raise HTTPException(403, "Path traversal not allowed")

    if not file_path.exists() or not file_path.is_file():
        index_path = deploy_root / "index.html"
        if index_path.is_file():
            file_path = index_path
        else:
            raise HTTPException(404, "File not found and no index.html fallback")

    media_type, _ = mimetypes.guess_type(str(file_path))
    if media_type is None:
        media_type = "application/octet-stream"

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        headers={
            "Cache-Control": "no-store",
            "X-Deploy-Conversation": conversation_id,
        },
    )
