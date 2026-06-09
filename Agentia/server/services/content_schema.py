"""Message content schema validation — F-W4-1."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

VALID_CONTENT_TYPES = frozenset({
    "text",
    "code",
    "diff",
    "preview",
    "file",
    "task_status",
    "deploy_status",
})


def _require_str(content: dict[str, Any], key: str) -> str:
    value = content.get(key)
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail="invalid_content")
    return value


def _require_non_empty_str(content: dict[str, Any], key: str) -> str:
    value = _require_str(content, key)
    if not value.strip():
        raise HTTPException(status_code=422, detail="invalid_content")
    return value


def _optional_str(content: dict[str, Any], key: str) -> str | None:
    value = content.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail="invalid_content")
    return value


def _optional_number(content: dict[str, Any], key: str) -> int | float | None:
    value = content.get(key)
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise HTTPException(status_code=422, detail="invalid_content")
    return value


def _optional_tool_calls(content: dict[str, Any]) -> list[dict[str, Any]] | None:
    raw = content.get("toolCalls")
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise HTTPException(status_code=422, detail="invalid_content")
    calls: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        tool_name = item.get("toolName") or item.get("tool_name")
        status = item.get("status")
        if not isinstance(tool_name, str) or not isinstance(status, str):
            continue
        call: dict[str, Any] = {"toolName": tool_name, "status": status}
        result_summary = item.get("resultSummary") or item.get("result_summary")
        if isinstance(result_summary, str):
            call["resultSummary"] = result_summary
        step = item.get("step")
        if isinstance(step, int) and not isinstance(step, bool):
            call["step"] = step
        calls.append(call)
    return calls


def _with_tool_calls(normalized: dict[str, Any], content: dict[str, Any]) -> dict[str, Any]:
    tool_calls = _optional_tool_calls(content)
    if tool_calls:
        normalized["toolCalls"] = tool_calls
    return normalized


def validate_content(content: Any) -> dict[str, Any]:
    if not isinstance(content, dict):
        raise HTTPException(status_code=422, detail="invalid_content")

    ctype = content.get("type")
    if ctype not in VALID_CONTENT_TYPES:
        raise HTTPException(status_code=422, detail="invalid_content")

    if ctype == "text":
        return _with_tool_calls({"type": "text", "text": _require_str(content, "text")}, content)

    if ctype == "code":
        artifact_id = _optional_str(content, "artifact_id")
        code = content.get("code")
        if artifact_id is None and not isinstance(code, str):
            raise HTTPException(status_code=422, detail="invalid_content")
        normalized: dict[str, Any] = {
            "type": "code",
            "artifact_id": artifact_id,
            "code": code if isinstance(code, str) else None,
            "language": _optional_str(content, "language") or "plaintext",
            "title": _optional_str(content, "title"),
            "fileName": _optional_str(content, "fileName") or _optional_str(content, "file_name"),
            "mimeType": _optional_str(content, "mimeType") or _optional_str(content, "mime_type"),
            "fileSize": _optional_number(content, "fileSize") or _optional_number(content, "file_size") or 0,
            "url": _optional_str(content, "url"),
            "previewUrl": _optional_str(content, "previewUrl") or _optional_str(content, "preview_url"),
            "version": _optional_number(content, "version") or 1,
        }
        return {k: v for k, v in normalized.items() if v is not None}

    if ctype == "diff":
        artifact_id = _optional_str(content, "artifact_id")
        before = content.get("before")
        after = content.get("after")
        if artifact_id is None and (not isinstance(before, str) or not isinstance(after, str)):
            raise HTTPException(status_code=422, detail="invalid_content")
        normalized = {
            "type": "diff",
            "artifact_id": artifact_id,
            "before": before if isinstance(before, str) else None,
            "after": after if isinstance(after, str) else None,
            "diff": _optional_str(content, "diff"),
            "base_artifact_id": _optional_str(content, "base_artifact_id") or _optional_str(content, "baseArtifactId"),
            "summary": _optional_str(content, "summary"),
            "fileName": _optional_str(content, "fileName") or _optional_str(content, "file_name"),
            "mimeType": _optional_str(content, "mimeType") or _optional_str(content, "mime_type"),
            "fileSize": _optional_number(content, "fileSize") or _optional_number(content, "file_size") or 0,
            "applied_artifact_id": _optional_str(content, "applied_artifact_id"),
            "version": _optional_number(content, "version") or 1,
        }
        return {k: v for k, v in normalized.items() if v is not None}

    if ctype == "preview":
        artifact_id = _require_non_empty_str(content, "artifact_id")
        return {
            "type": "preview",
            "artifact_id": artifact_id,
            "title": _require_non_empty_str(content, "title"),
            "mimeType": _optional_str(content, "mimeType") or _optional_str(content, "mime_type") or "text/html",
            "fileSize": _optional_number(content, "fileSize") or _optional_number(content, "file_size") or 0,
            "url": _optional_str(content, "url"),
            "previewUrl": _optional_str(content, "previewUrl") or _optional_str(content, "preview_url"),
            "version": _optional_number(content, "version") or 1,
        }

    if ctype == "file":
        artifact_id = _require_non_empty_str(content, "artifact_id")
        return {
            "type": "file",
            "artifact_id": artifact_id,
            "fileName": _require_non_empty_str(content, "fileName"),
            "mimeType": _optional_str(content, "mimeType") or _optional_str(content, "mime_type") or "application/octet-stream",
            "fileSize": _optional_number(content, "fileSize") or _optional_number(content, "file_size") or 0,
            "url": _optional_str(content, "url"),
            "previewUrl": _optional_str(content, "previewUrl") or _optional_str(content, "preview_url"),
            "version": _optional_number(content, "version") or 1,
        }

    if ctype == "task_status":
        return {
            "type": "task_status",
            "task_id": _require_non_empty_str(content, "task_id"),
            "status": _require_non_empty_str(content, "status"),
            "title": _optional_str(content, "title") or "任务状态",
            "progress": _optional_number(content, "progress") or 0,
            "summary": _optional_str(content, "summary"),
        }

    return {
        "type": "deploy_status",
        "deploy_id": _require_non_empty_str(content, "deploy_id"),
        "status": _require_non_empty_str(content, "status"),
        "title": _optional_str(content, "title") or "部署状态",
        "url": _optional_str(content, "url"),
        "summary": _optional_str(content, "summary"),
    }
