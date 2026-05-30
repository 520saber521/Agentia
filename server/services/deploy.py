"""Deploy service — project type detection, build commands, preview URL generation."""

from __future__ import annotations

import json
import logging
from pathlib import Path

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


def is_deploy_request(user_text: str) -> bool:
    lower = user_text.strip().lower()
    if lower in ("部署", "deploy", "/部署", "/deploy"):
        return True
    return any(k in lower for k in ["部署", "deploy", "build and preview", "build & preview", "构建并预览"])
