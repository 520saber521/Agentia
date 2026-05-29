"""Async SQLAlchemy engine + session factory。

- 默认存储路径：``<server>/.agenthub/bff.db``
- 可通过环境变量 ``AGENTHUB_BFF_DB_URL`` 覆盖（例如 PostgreSQL）。
- 单例缓存，``init_db()`` / ``dispose()`` 之间可重复调用。

测试时建议 ``monkeypatch.setenv("AGENTHUB_BFF_DB_URL", ...)`` + ``reset()`` 强制重建。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_HERE = Path(__file__).resolve().parent
_SERVER_DIR = _HERE.parent
DEFAULT_DB_PATH = _SERVER_DIR / ".agenthub" / "bff.db"

_state: dict[str, Any] = {"engine": None, "session_maker": None}


def _build_url() -> str:
    env = os.getenv("AGENTHUB_BFF_DB_URL")
    if env:
        return env
    DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{DEFAULT_DB_PATH.as_posix()}"


def get_engine() -> AsyncEngine:
    if _state["engine"] is None:
        url = _build_url()
        engine = create_async_engine(url, echo=False, future=True)
        _state["engine"] = engine
        _state["session_maker"] = async_sessionmaker(engine, expire_on_commit=False)
    return _state["engine"]  # type: ignore[return-value]


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _state["session_maker"] is None:
        get_engine()
    return _state["session_maker"]  # type: ignore[return-value]


async def _ensure_sqlite_schema(conn: Any) -> None:
    rows = await conn.execute(text("PRAGMA table_info(conversation)"))
    conv_columns = {str(row[1]) for row in rows.fetchall()}
    if conv_columns and "workspace_path" not in conv_columns:
        await conn.execute(text("ALTER TABLE conversation ADD COLUMN workspace_path VARCHAR(1024)"))

    rows = await conn.execute(text("PRAGMA table_info(task)"))
    task_columns = {str(row[1]) for row in rows.fetchall()}
    if task_columns and "agent_name" not in task_columns:
        await conn.execute(text("ALTER TABLE task ADD COLUMN agent_name VARCHAR"))

    rows = await conn.execute(text("PRAGMA table_info(agent)"))
    agent_columns = {str(row[1]) for row in rows.fetchall()}
    if agent_columns and "is_system" not in agent_columns:
        await conn.execute(text("ALTER TABLE agent ADD COLUMN is_system INTEGER NOT NULL DEFAULT 0"))
    if agent_columns and "locked_prompt" not in agent_columns:
        await conn.execute(text("ALTER TABLE agent ADD COLUMN locked_prompt INTEGER NOT NULL DEFAULT 0"))
    if agent_columns and "updated_at" not in agent_columns:
        await conn.execute(text("ALTER TABLE agent ADD COLUMN updated_at INTEGER NOT NULL DEFAULT 0"))


async def init_db() -> None:
    """建表（幂等）。Day3 暂用 ``create_all``，Alembic 留到 schema 真正演进时再上。"""
    from .models import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.url.get_backend_name() == "sqlite":
            await _ensure_sqlite_schema(conn)


async def dispose() -> None:
    engine = _state.get("engine")
    if engine is not None:
        await engine.dispose()
    _state["engine"] = None
    _state["session_maker"] = None


def reset_for_tests() -> None:
    """仅供测试：丢弃缓存（不关闭，需要先 ``await dispose()``）。"""
    _state["engine"] = None
    _state["session_maker"] = None
