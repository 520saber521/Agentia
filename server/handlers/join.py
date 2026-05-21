"""``join`` handler — subscribe to a conversation and replay recent history.

Extracted from ``main.py`` during W2-D1 split.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from db.engine import get_sessionmaker
from db.models import Conversation
from services import list_agents, list_messages, message_to_dict
from ws import Connection, event


async def handle(conn: Connection, evt: dict[str, Any]) -> None:
    cid = evt.get("conversation_id")
    if not isinstance(cid, str) or not cid:
        await conn.send(event("error", code="bad_join", message="conversation_id required"))
        return
    limit = int(evt.get("limit") or 50)
    conn.joined_conversations.add(cid)

    Session = get_sessionmaker()
    async with Session() as s:
        msgs = await list_messages(s, cid, limit=limit)
        agents = await list_agents(s)

    await conn.send(event("history", conversation_id=cid, messages=msgs, count=len(msgs)))
    await conn.send(event("agents", agents=agents))
