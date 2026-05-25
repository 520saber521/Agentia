"""Message 业务封装。

约定：

- 所有写库方法都在内部 ``commit``。
- ``message_to_dict`` 把 ORM 对象转成"前端可消费"的 JSON 形（``content`` 解析为 dict）。
- 入库时会顺手维护 ``conversation.last_msg_preview`` / ``updated_at``，
  避免每次写完 message 都得到上层重复维护。
"""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Conversation, Message, new_id, now_ms
from services.content_schema import validate_content


def message_to_dict(m: Message) -> dict[str, Any]:
    """把 ORM 对象映射为 ``ChatMessage``（见 ``docs/ARCHITECTURE.md`` §7.3）。"""
    return {
        "id": m.id,
        "conversation_id": m.conversation_id,
        "sender_id": m.sender_id,
        "sender_type": m.sender_type,
        "content_type": m.content_type,
        "content": _safe_loads(m.content),
        "reply_to": m.reply_to,
        "mentions": _safe_loads(m.mentions) if m.mentions else [],
        "pinned": bool(m.pinned),
        "artifact_id": m.artifact_id,
        "agenthub_msg_id": m.agenthub_msg_id,
        "created_at": m.created_at,
    }


async def create_message(
    s: AsyncSession,
    *,
    conversation_id: str,
    sender_id: str,
    sender_type: str,
    content: dict[str, Any],
    content_type: Optional[str] = None,
    reply_to: Optional[str] = None,
    mentions: Optional[list[str]] = None,
    message_id: Optional[str] = None,
    artifact_id: Optional[str] = None,
) -> Message:
    normalized_content = validate_content(content)
    ts = now_ms()
    m = Message(
        id=message_id or new_id("msg"),
        conversation_id=conversation_id,
        sender_id=sender_id,
        sender_type=sender_type,
        content_type=content_type or normalized_content.get("type") or "text",
        content=json.dumps(normalized_content, ensure_ascii=False),
        reply_to=reply_to,
        mentions=json.dumps(mentions or [], ensure_ascii=False),
        artifact_id=artifact_id,
        created_at=ts,
    )
    s.add(m)
    await _touch_conversation(s, conversation_id, normalized_content, ts=ts)
    await s.commit()
    return m


async def update_message_content(
    s: AsyncSession,
    message_id: str,
    content: dict[str, Any],
) -> Optional[Message]:
    """把已落库的消息 content 改写为最新内容（典型场景：流式结束后回写完整文本）。"""
    m = await s.get(Message, message_id)
    if m is None:
        return None
    normalized_content = validate_content(content)
    m.content = json.dumps(normalized_content, ensure_ascii=False)
    if isinstance(normalized_content.get("type"), str):
        m.content_type = normalized_content["type"]
    await _touch_conversation(s, m.conversation_id, normalized_content, ts=now_ms())
    await s.commit()
    return m


async def _touch_conversation(
    s: AsyncSession,
    conversation_id: str,
    content: dict[str, Any],
    *,
    ts: int,
) -> None:
    conv = await s.get(Conversation, conversation_id)
    if conv is None:
        return
    preview = content.get("text") if isinstance(content, dict) else None
    if isinstance(preview, str) and preview.strip():
        conv.last_msg_preview = preview[:80]
    current_updated = conv.updated_at or 0
    if isinstance(ts, int) and ts > current_updated:
        conv.updated_at = ts


async def pin_message(
    s: AsyncSession,
    message_id: str,
    pinned: bool = True,
) -> Optional[Message]:
    m = await s.get(Message, message_id)
    if m is None:
        return None
    m.pinned = 1 if pinned else 0
    await s.commit()
    return m


def _safe_loads(raw: Optional[str]) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw
