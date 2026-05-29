import shlex
import subprocess
from typing import Any, Dict, List


def _build_command(workspace: str, session: str, epoch: int, codex_path: str, window: Dict[str, Any]) -> str:
    env_parts = [
        f"TEAM_ROLE={window['role']}",
        f"TEAM_AGENT_ID={window['agent_instance']}",
        f"TEAM_SESSION={session}",
        f"TEAM_EPOCH={epoch}",
        f"TEAM_WINDOW_NAME={window['window_name']}",
    ]
    command = " ".join(env_parts)
    command += " " + codex_path
    command += " --dangerously-bypass-approvals-and-sandbox"
    command += " -C " + shlex.quote(workspace)
    return command


def launch(
    workspace: str,
    session: str,
    epoch: int,
    codex_path: str,
    windows: List[Dict[str, Any]],
) -> None:
    if not windows:
        return

    session_name = f"team-{session}"
    first = windows[0]
    first_cmd = _build_command(workspace, session, epoch, codex_path, first)

    subprocess.run(
        ["tmux", "new-session", "-d", "-s", session_name, "-n", first["window_name"], first_cmd],
        check=True,
    )

    for window in windows[1:]:
        cmd = _build_command(workspace, session, epoch, codex_path, window)
        subprocess.run(
            ["tmux", "new-window", "-t", session_name, "-n", window["window_name"], cmd],
            check=True,
        )

    subprocess.run(["tmux", "attach", "-t", session_name], check=True)
