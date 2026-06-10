from pathlib import Path
import subprocess
from typing import Any, Dict, List


def launch(
    workspace: str,
    session: str,
    epoch: int,
    codex_path: str,
    windows: List[Dict[str, Any]],
) -> None:
    root = Path(__file__).resolve().parents[2]
    script_path = root / "scripts" / "iterm2" / "launch_iterm2.sh"
    if not script_path.exists():
        raise FileNotFoundError(f"missing iTerm2 launcher: {script_path}")

    cmd = [
        "/bin/sh",
        str(script_path),
        workspace,
        codex_path,
        session,
        str(epoch),
    ]
    for window in windows:
        cmd.extend([window["role"], window["agent_instance"], window["window_name"]])

    subprocess.run(cmd, check=True)
