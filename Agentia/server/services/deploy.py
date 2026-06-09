"""Deploy service — project type detection, build commands, preview URL generation."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Agent, Artifact
from services.artifact import artifact_to_dict, read_artifact_content_with_session

logger = logging.getLogger("agenthub.services.deploy")

_BUILD_OUTPUT_DIRS = ("dist", "build", ".next", "out")

_BUILD_COMMANDS: dict[str, list[list[str]]] = {
    "react": [["npm", "install"], ["npm", "run", "build"]],
    "vue": [["npm", "install"], ["npm", "run", "build"]],
    "vite": [["npm", "install"], ["npm", "run", "build"]],
    "next": [["npm", "install"], ["npm", "run", "build"]],
    "angular": [["npm", "install"], ["npm", "run", "build"]],
    "static": [],
    "unknown": [["npm", "install"], ["npm", "run", "build"]],
}

_PROJECT_TYPE_MARKERS: dict[str, str] = {
    "react": "react",
    "react-dom": "react",
    "vue": "vue",
    "@angular/core": "angular",
    "next": "next",
    "nuxt": "vue",
    "@vitejs/plugin-react": "react",
    "@vitejs/plugin-vue": "vue",
    "vite": "vite",
}

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_WORKSPACES_DIR = _PROJECT_ROOT / "workspaces"


def _resolve_workspace_root(conversation_id: str) -> Path:
    return _WORKSPACES_DIR / conversation_id


def detect_project_type(conversation_id: str) -> str:
    """Detect project type by inspecting workspace files.

    Returns one of: "react", "vue", "vite", "next", "angular", "static", "unknown"
    """
    ws_root = _resolve_workspace_root(conversation_id)
    pkg_json = ws_root / "package.json"
    if not pkg_json.is_file():
        html_files = list(ws_root.glob("*.html"))
        return "static" if html_files else "unknown"

    try:
        pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "unknown"

    all_deps: dict[str, object] = {}
    all_deps.update(pkg.get("dependencies", {}))
    all_deps.update(pkg.get("devDependencies", {}))

    for dep, ptype in _PROJECT_TYPE_MARKERS.items():
        if dep in all_deps:
            return ptype

    scripts = pkg.get("scripts", {})
    if isinstance(scripts, dict) and "build" in scripts:
        return "unknown"

    return "static"


def get_build_commands(conversation_id: str) -> list[list[str]]:
    ptype = detect_project_type(conversation_id)
    commands = _BUILD_COMMANDS.get(ptype, _BUILD_COMMANDS["unknown"])
    logger.info("Detected project type=%s for conv=%s, commands=%s", ptype, conversation_id, commands)
    return commands


def get_build_output_dir(conversation_id: str) -> Path:
    ws_root = _resolve_workspace_root(conversation_id)
    ptype = detect_project_type(conversation_id)

    if ptype == "next":
        return ws_root / ".next"

    for dir_name in _BUILD_OUTPUT_DIRS:
        candidate = ws_root / dir_name
        if candidate.is_dir():
            return candidate

    return ws_root / "dist"


def generate_preview_url(conversation_id: str) -> str:
    return f"/deploy/preview/{conversation_id}/"


def _is_frontend_agent(agent: Agent | None) -> bool:
    if agent is None:
        return False
    text = " ".join([
        agent.id or "",
        agent.name or "",
        agent.adapter_type or "",
        agent.capabilities or "",
        agent.config or "",
    ]).lower()
    return any(k in text for k in ("frontend", "front-end", "前端", "html", "ui", "react", "web", "preview"))


def _is_html_artifact(artifact: dict[str, Any]) -> bool:
    mime = str(artifact.get("mime_type") or "").lower()
    name = str(artifact.get("file_name") or artifact.get("title") or "").lower()
    kind = str(artifact.get("kind") or "").lower()
    return kind == "preview" or mime == "text/html" or name.endswith(".html")


def _strip_markdown_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _is_complete_html(content: str) -> bool:
    lower = content.lower()
    return ("<html" in lower and "</html>" in lower) or ("<!doctype html" in lower and "</body>" in lower)


def _looks_like_css(content: str) -> bool:
    lower = content.lower()
    css_markers = ("{", "}", "color:", "background", "display:", "position:", "font-size", "@media", "--")
    html_markers = ("<div", "<section", "<main", "<body", "<html", "<script")
    return sum(1 for marker in css_markers if marker in lower) >= 3 and not any(marker in lower for marker in html_markers)


def _wrap_deployable_html(content: str, title: str) -> tuple[str, bool]:
    cleaned = _strip_markdown_fence(content)
    if _is_complete_html(cleaned):
        return cleaned, False
    safe_title = (title or "Agentia Preview").replace("<", "").replace(">", "")
    if _looks_like_css(cleaned):
        return f"""<!DOCTYPE html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{safe_title}</title>
  <style>{cleaned}</style>
</head>
<body>
  <main class=\"agentia-deploy-placeholder\">
    <h1>{safe_title}</h1>
    <p>该产物只包含样式代码，已自动包装为可打开的静态网页。请重新让 Frontend Agent 生成完整 HTML，可获得完整页面效果。</p>
  </main>
</body>
</html>""", True
    return f"""<!DOCTYPE html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{safe_title}</title>
</head>
<body>
{cleaned}
</body>
</html>""", True


async def _find_best_deployable_artifact(
    s: AsyncSession,
    conversation_id: str,
) -> tuple[dict[str, Any], str, bool] | None:
    stmt = (
        select(Artifact)
        .where(
            Artifact.conversation_id == conversation_id,
            or_(Artifact.kind == "preview", Artifact.mime_type == "text/html", Artifact.file_name.ilike("%.html")),
        )
        .order_by(desc(Artifact.created_at))
        .limit(50)
    )
    artifacts = (await s.scalars(stmt)).all()
    if not artifacts:
        return None

    agent_ids = {a.created_by for a in artifacts if a.created_by}
    agents: dict[str, Agent] = {}
    if agent_ids:
        rows = (await s.scalars(select(Agent).where(Agent.id.in_(list(agent_ids))))).all()
        agents = {a.id: a for a in rows}

    ordered = [a for a in artifacts if _is_frontend_agent(agents.get(a.created_by))]
    ordered.extend(a for a in artifacts if a not in ordered)
    fallback: tuple[dict[str, Any], str, bool] | None = None
    for artifact_row in ordered:
        artifact = artifact_to_dict(artifact_row)
        if not _is_html_artifact(artifact):
            continue
        raw = await read_artifact_content_with_session(s, artifact["id"])
        if not raw or not raw.strip():
            continue
        html, wrapped = _wrap_deployable_html(raw, str(artifact.get("title") or artifact.get("file_name") or "Agentia Preview"))
        if _is_complete_html(_strip_markdown_fence(raw)):
            return artifact, html, False
        if fallback is None:
            fallback = (artifact, html, wrapped)
    return fallback


async def find_latest_frontend_html_artifact(
    s: AsyncSession,
    conversation_id: str,
) -> dict[str, Any] | None:
    stmt = (
        select(Artifact)
        .where(
            Artifact.conversation_id == conversation_id,
            or_(Artifact.kind == "preview", Artifact.mime_type == "text/html", Artifact.file_name.ilike("%.html")),
        )
        .order_by(desc(Artifact.created_at))
        .limit(50)
    )
    artifacts = (await s.scalars(stmt)).all()
    if not artifacts:
        return None

    agent_ids = {a.created_by for a in artifacts if a.created_by}
    agents: dict[str, Agent] = {}
    if agent_ids:
        rows = (await s.scalars(select(Agent).where(Agent.id.in_(list(agent_ids))))).all()
        agents = {a.id: a for a in rows}

    frontend_items = [a for a in artifacts if _is_frontend_agent(agents.get(a.created_by))]
    chosen = frontend_items[0] if frontend_items else artifacts[0]
    data = artifact_to_dict(chosen)
    return data if _is_html_artifact(data) else None


async def deploy_frontend_html_to_netlify(
    s: AsyncSession,
    conversation_id: str,
) -> dict[str, Any]:
    deployable = await _find_best_deployable_artifact(s, conversation_id)
    if deployable is None:
        return {
            "ok": False,
            "status": "failed",
            "summary": "当前对话没有找到前端 Agent 生成的可部署 HTML / preview 产物，无法部署到 Netlify。",
        }
    artifact, content, wrapped = deployable

    token = os.environ.get("NETLIFY_AUTH_TOKEN", "").strip()
    if not token:
        return {
            "ok": False,
            "status": "failed",
            "summary": "缺少 NETLIFY_AUTH_TOKEN，无法部署到 Netlify。请在 server/.env 配置 Netlify Personal Access Token 后重试。",
            "artifact": artifact,
        }

    if not content or not content.strip():
        return {
            "ok": False,
            "status": "failed",
            "summary": f"HTML 产物内容为空：{artifact.get('title') or artifact['id']}。",
            "artifact": artifact,
        }

    site_id = os.environ.get("NETLIFY_SITE_ID", "").strip()
    site_name = os.environ.get("NETLIFY_SITE_NAME", "").strip()
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=60, headers=headers) as client:
        if not site_id:
            payload: dict[str, Any] = {}
            if site_name:
                payload["name"] = site_name
            create_resp = await client.post("https://api.netlify.com/api/v1/sites", json=payload)
            if create_resp.status_code >= 400:
                return {
                    "ok": False,
                    "status": "failed",
                    "summary": f"Netlify 创建站点失败：HTTP {create_resp.status_code} {create_resp.text[:300]}",
                    "artifact": artifact,
                }
            site_id = str(create_resp.json().get("id") or "")
            if not site_id:
                return {
                    "ok": False,
                    "status": "failed",
                    "summary": "Netlify 创建站点成功但未返回 site id。",
                    "artifact": artifact,
                }

        html_bytes = content.encode("utf-8")
        html_sha1 = hashlib.sha1(html_bytes).hexdigest()
        deploy_resp = await client.post(
            f"https://api.netlify.com/api/v1/sites/{site_id}/deploys",
            json={"files": {"/index.html": html_sha1}},
        )
        if deploy_resp.status_code >= 400:
            return {
                "ok": False,
                "status": "failed",
                "summary": f"Netlify 创建部署失败：HTTP {deploy_resp.status_code} {deploy_resp.text[:300]}",
                "artifact": artifact,
            }
        body = deploy_resp.json()
        deploy_id = str(body.get("id") or "")
        required = body.get("required") or body.get("required_functions") or []
        if not deploy_id:
            return {
                "ok": False,
                "status": "failed",
                "summary": "Netlify 创建部署成功但未返回 deploy id。",
                "artifact": artifact,
            }
        if not isinstance(required, list) or html_sha1 in required:
            upload_resp = await client.put(
                f"https://api.netlify.com/api/v1/deploys/{deploy_id}/files/index.html",
                content=html_bytes,
                headers={**headers, "Content-Type": "text/html; charset=utf-8"},
            )
            if upload_resp.status_code >= 400:
                return {
                    "ok": False,
                    "status": "failed",
                    "summary": f"Netlify 上传 index.html 失败：HTTP {upload_resp.status_code} {upload_resp.text[:300]}",
                    "artifact": artifact,
                }
        url = body.get("deploy_ssl_url") or body.get("ssl_url") or body.get("deploy_url") or body.get("url") or ""
        note = "（原产物不是完整 HTML，已自动包装为可打开网页）" if wrapped else ""
        return {
            "ok": True,
            "status": "deployed",
            "url": url,
            "site_id": site_id,
            "deploy_id": deploy_id,
            "summary": f"已将前端 HTML 产物《{artifact.get('title') or artifact.get('file_name') or artifact['id']}》以静态网页方式部署到 Netlify。{note}",
            "artifact": artifact,
        }


def is_deploy_request(user_text: str) -> bool:
    lower = user_text.strip().lower()
    if lower in ("部署", "deploy", "/部署", "/deploy"):
        return True
    return any(k in lower for k in ["部署", "deploy", "build and preview", "build & preview", "构建并预览"])
