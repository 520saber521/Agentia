from dataclasses import dataclass
from pathlib import Path
from typing import Union


@dataclass(frozen=True)
class StorageLayout:
    root: Path

    @staticmethod
    def for_workspace(workspace: Union[str, Path]) -> "StorageLayout":
        return StorageLayout(Path(workspace) / ".codex_team")

    def ensure(self) -> None:
        self.meta_dir().mkdir(parents=True, exist_ok=True)
        self.state_dir().mkdir(parents=True, exist_ok=True)
        self.inbox_dir().mkdir(parents=True, exist_ok=True)
        self.logs_dir().mkdir(parents=True, exist_ok=True)
        self.blobs_dir().mkdir(parents=True, exist_ok=True)

    def meta_dir(self) -> Path:
        return self.root / "meta"

    def state_dir(self) -> Path:
        return self.root / "state"

    def inbox_dir(self) -> Path:
        return self.root / "inbox"

    def logs_dir(self) -> Path:
        return self.root / "logs"

    def blobs_dir(self) -> Path:
        return self.root / "blobs"

    def session_path(self) -> Path:
        return self.meta_dir() / "session.json"

    def router_state_path(self) -> Path:
        return self.state_dir() / "router.json"

    def tasks_path(self) -> Path:
        return self.state_dir() / "tasks.json"

    def inbox_path(self, agent: str) -> Path:
        return self.inbox_dir() / f"{agent}.jsonl"

    def messages_log_path(self, epoch: int) -> Path:
        return self.logs_dir() / f"messages-{epoch}.jsonl"

    def acks_log_path(self, epoch: int) -> Path:
        return self.logs_dir() / f"acks-{epoch}.jsonl"

    def blob_path(self, blob_id: str) -> Path:
        return self.blobs_dir() / f"{blob_id}.json"
