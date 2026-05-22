"""AgentHub BFF · W2 Day1 (split from monolithic main.py).

Responsibilities retained:
- FastAPI ``app`` creation, middleware, route mounting
- ``lifespan`` for DB init / seed / dispose
- ``/health`` endpoint
- ``/ws`` WebSocket endpoint (delegates to :mod:`handlers` for dispatch)
- Static file serving for ``static/index.html``

Everything else moved to:
- :mod:`ws` — Connection, WSHub, event helpers
- :mod:`handlers` — event dispatch + per-type handlers
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure server/ is on sys.path BEFORE any other paths to avoid import conflicts with src/api
_HERE = Path(__file__).resolve().parent
# Remove any parent dirs that might shadow server/api
new_path = [p for p in sys.path if not (Path(p) / "api").exists() or str(_HERE) in p]
if str(_HERE) not in new_path:
    new_path.insert(0, str(_HERE))
sys.path[:] = new_path

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api import router as rest_router
from db import dispose, init_db, seed_defaults
from handlers import dispatch
from ws import Connection, event, hub

logger = logging.getLogger("agenthub.bff")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"

SERVER_NAME = "agenthub-bff"
SERVER_VERSION = "0.0.5"


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("%s/%s starting up …", SERVER_NAME, SERVER_VERSION)
    await init_db()
    await seed_defaults()
    logger.info("DB ready & defaults seeded.")
    try:
        yield
    finally:
        logger.info("%s/%s shutting down (ws_conns=%d)", SERVER_NAME, SERVER_VERSION, hub.size)
        await dispose()


app = FastAPI(
    title="AgentHub BFF",
    version=SERVER_VERSION,
    summary="W2 Day1: split architecture, WSHub + handlers/",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rest_router)


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "server": f"{SERVER_NAME}/{SERVER_VERSION}",
            "ws_conns": hub.size,
            "ts": int(__import__("time").time() * 1000),
        }
    )


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    conn = Connection(ws)
    await hub.add(conn)
    writer_task = asyncio.create_task(conn.writer(), name=f"ws-writer-{conn.conn_id}")
    logger.info("ws[%s] connected (total=%d)", conn.conn_id, hub.size)
    try:
        await conn.send(
            event("hello", conn_id=conn.conn_id, server=f"{SERVER_NAME}/{SERVER_VERSION}")
        )
        while True:
            raw = await ws.receive_text()
            await dispatch(conn, raw)
    except WebSocketDisconnect:
        logger.info("ws[%s] disconnected", conn.conn_id)
    except Exception:
        logger.exception("ws[%s] unexpected error", conn.conn_id)
    finally:
        await conn.close()
        await hub.remove(conn)
        try:
            await asyncio.wait_for(writer_task, timeout=2)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            writer_task.cancel()
        logger.info("ws[%s] cleanup done (total=%d)", conn.conn_id, hub.size)


if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
