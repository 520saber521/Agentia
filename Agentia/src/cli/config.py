import json
import os
from typing import Any, Dict, Optional

DEFAULTS = {
    "router_host": "127.0.0.1",
    "router_port": 8765,
    "terminal_adapter": "terminal",
    "codex_path": "codex",
    "roles": ["MAIN", "A", "B", "C", "D"],
    "window_name_format": "team-<session>-<role>",
    "default_review_deadline_s": 3600,
}


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    if not path or not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("config must be a JSON object")
    return data


def _parse_roles(value: Any) -> Optional[list]:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        roles = [item.strip() for item in value.split(",") if item.strip()]
        return roles or None
    return None


def load_config(config_path: Optional[str], workspace: Optional[str]) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(DEFAULTS)

    candidates = []
    if config_path:
        candidates.append(config_path)
    env_path = os.environ.get("CODEX_TEAM_CONFIG")
    if env_path:
        candidates.append(env_path)
    if workspace:
        candidates.append(os.path.join(workspace, ".codex_team", "config.json"))
    candidates.append(os.path.expanduser("~/.codex_team/config.json"))

    for path in candidates:
        data = _read_json(path)
        if data is None:
            continue
        config.update(data)
        break

    env_overrides = {
        "CODEX_TEAM_WORKSPACE": "workspace",
        "CODEX_TEAM_ROUTER_URL": "router_url",
        "CODEX_TEAM_ROUTER_HOST": "router_host",
        "CODEX_TEAM_ROUTER_PORT": "router_port",
        "CODEX_TEAM_TERMINAL_ADAPTER": "terminal_adapter",
        "CODEX_TEAM_CODEX_PATH": "codex_path",
        "CODEX_TEAM_ROLES": "roles",
        "CODEX_TEAM_WINDOW_NAME_FORMAT": "window_name_format",
        "CODEX_TEAM_DEFAULT_REVIEW_DEADLINE_S": "default_review_deadline_s",
    }
    for env_key, key in env_overrides.items():
        value = os.environ.get(env_key)
        if value is None or value == "":
            continue
        if key in ("router_port", "default_review_deadline_s"):
            config[key] = int(value)
        elif key == "roles":
            roles = _parse_roles(value)
            if roles:
                config[key] = roles
        else:
            config[key] = value

    roles = _parse_roles(config.get("roles"))
    if roles:
        config["roles"] = roles

    if config.get("workspace"):
        config["workspace"] = os.path.abspath(str(config["workspace"]))
    return config


def resolve_workspace(config: Dict[str, Any], workspace: Optional[str]) -> str:
    if workspace:
        return os.path.abspath(workspace)
    if config.get("workspace"):
        return os.path.abspath(str(config["workspace"]))
    return os.getcwd()


def resolve_router_url(config: Dict[str, Any], router_url: Optional[str], host: Optional[str], port: Optional[int]) -> str:
    if router_url:
        return router_url
    if config.get("router_url"):
        return str(config["router_url"])
    router_host = host or config.get("router_host", DEFAULTS["router_host"])
    router_port = port or config.get("router_port", DEFAULTS["router_port"])
    return f"http://{router_host}:{int(router_port)}"
