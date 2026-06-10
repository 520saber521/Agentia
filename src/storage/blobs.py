from typing import Optional

from .jsonio import read_json, write_json_atomic
from .layout import StorageLayout


def write_blob(layout: StorageLayout, blob_id: str, payload: dict) -> str:
    path = layout.blob_path(blob_id)
    write_json_atomic(path, payload)
    return str(path)


def read_blob(layout: StorageLayout, blob_id: str) -> Optional[dict]:
    return read_json(layout.blob_path(blob_id))
