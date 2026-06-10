import time
import uuid
from pathlib import Path
from typing import List, Optional, Union

from .jsonio import read_json, write_json_atomic
from .layout import StorageLayout


def init_or_load_session(
    layout: StorageLayout,
    workspace: Union[str, Path],
    roles: Optional[List[str]] = None,
) -> dict:
    layout.ensure()
    session_path = layout.session_path()
    existing = read_json(session_path)
    if existing is not None:
        return existing

    session = {
        "session_id": str(uuid.uuid4()),
        "created_at": int(time.time() * 1000),
        "workspace": str(Path(workspace)),
        "roles": roles or [],
    }
    write_json_atomic(session_path, session)
    return session
