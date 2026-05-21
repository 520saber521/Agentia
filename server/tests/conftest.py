"""Day3 起共享的 DB 测试夹具。

每个用例都拿一个全新的、隔离在 ``tmp_path`` 下的 SQLite 文件，
避免污染真实的 ``server/.agenthub/bff.db``。
"""

from __future__ import annotations

import pytest


@pytest.fixture
async def db_env(tmp_path, monkeypatch):
    """临时 DB + 干净的 engine 缓存。"""
    db_path = tmp_path / "bff.db"
    monkeypatch.setenv(
        "AGENTHUB_BFF_DB_URL",
        f"sqlite+aiosqlite:///{db_path.as_posix()}",
    )

    from db.engine import dispose, init_db, reset_for_tests

    reset_for_tests()
    await init_db()
    try:
        yield db_path
    finally:
        await dispose()
        reset_for_tests()
