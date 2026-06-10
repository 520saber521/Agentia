from typing import Any, Dict, List

from .terminal import launch as launch_terminal
from .tmux import launch as launch_tmux

try:
    from .iterm2 import launch as launch_iterm2
except Exception:  # pragma: no cover - optional dependency
    launch_iterm2 = None


def launch(
    *,
    adapter: str,
    workspace: str,
    session: str,
    epoch: int,
    codex_path: str,
    windows: List[Dict[str, Any]],
) -> None:
    if adapter == "terminal":
        launch_terminal(workspace, session, epoch, codex_path, windows)
        return
    if adapter == "tmux":
        launch_tmux(workspace, session, epoch, codex_path, windows)
        return
    if adapter == "iterm2":
        if not launch_iterm2:
            raise RuntimeError("iTerm2 launcher not configured")
        launch_iterm2(workspace, session, epoch, codex_path, windows)
        return
    raise ValueError(f"unknown terminal adapter: {adapter}")
