from dataclasses import dataclass
from typing import Dict, Optional

from storage.jsonio import read_json, write_json_atomic
from storage.layout import StorageLayout


def load_tasks(layout: StorageLayout) -> Dict[str, dict]:
    data = read_json(layout.tasks_path())
    if not data:
        return {}
    if isinstance(data, dict):
        return data
    return {}


def save_tasks(layout: StorageLayout, tasks: Dict[str, dict]) -> None:
    write_json_atomic(layout.tasks_path(), tasks)


def get_task(tasks: Dict[str, dict], task_id: str) -> Optional[dict]:
    return tasks.get(task_id)


def update_task(
    tasks: Dict[str, dict],
    task_id: str,
    status: Optional[str] = None,
    owner: Optional[object] = None,
    deadline: Optional[object] = None,
    retries: Optional[int] = None,
    last_update_seq: Optional[int] = None,
) -> dict:
    entry = tasks.get(task_id)
    if entry is None:
        entry = {"retries": 0}
        tasks[task_id] = entry
    if status is not None:
        entry["status"] = status
    if owner is not None:
        entry["owner"] = owner
    if deadline is not None:
        entry["deadline"] = deadline
    if retries is not None:
        entry["retries"] = retries
    if last_update_seq is not None:
        entry["last_update_seq"] = last_update_seq
    return entry


def increment_task_retries(tasks: Dict[str, dict], task_id: str, amount: int = 1) -> dict:
    entry = tasks.get(task_id)
    if entry is None:
        entry = {"retries": 0}
        tasks[task_id] = entry
    current = entry.get("retries")
    try:
        current_int = int(current)
    except (TypeError, ValueError):
        current_int = 0
    entry["retries"] = current_int + amount
    return entry


def apply_message_to_tasks(tasks: Dict[str, dict], message: dict) -> None:
    task_id = message.get("task_id")
    if not task_id:
        return
    action = message.get("action")
    status = _status_for_action(action)
    if not status:
        return

    owner = message.get("owner")
    if owner is None and "to" in message:
        owner = message.get("to")
    update_task(
        tasks,
        task_id=task_id,
        status=status,
        owner=owner,
        deadline=message.get("deadline"),
        last_update_seq=message.get("seq"),
    )


def _status_for_action(action: Optional[str]) -> Optional[str]:
    if action == "assign":
        return "open"
    if action == "done":
        return "done"
    if action == "fail":
        return "failed"
    if action == "verify":
        return "verify_pending"
    if action == "verified":
        return "verified"
    return None


@dataclass
class TaskStore:
    layout: StorageLayout
    tasks: Dict[str, dict]

    @staticmethod
    def load(layout: StorageLayout) -> "TaskStore":
        return TaskStore(layout=layout, tasks=load_tasks(layout))

    def get(self, task_id: str) -> Optional[dict]:
        return self.tasks.get(task_id)

    def update(
        self,
        task_id: str,
        status: Optional[str] = None,
        owner: Optional[object] = None,
        deadline: Optional[object] = None,
        retries: Optional[int] = None,
        last_update_seq: Optional[int] = None,
    ) -> dict:
        return update_task(
            self.tasks,
            task_id=task_id,
            status=status,
            owner=owner,
            deadline=deadline,
            retries=retries,
            last_update_seq=last_update_seq,
        )

    def increment_retries(self, task_id: str, amount: int = 1) -> dict:
        return increment_task_retries(self.tasks, task_id, amount=amount)

    def apply_message(self, message: dict) -> None:
        apply_message_to_tasks(self.tasks, message)

    def save(self) -> None:
        save_tasks(self.layout, self.tasks)
