"""Conversation 业务封装。"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import asc, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Conversation, ConversationMember, Message, new_id, now_ms
from services.agent import get_existing_agent_ids
from services.message import message_to_dict


def conv_to_dict(
    c: Conversation,
    members: Optional[list[ConversationMember]] = None,
) -> dict[str, Any]:
    return {
        "id": c.id,
        "title": c.title,
        "type": c.type,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
        "pinned": bool(c.pinned),
        "archived": bool(c.archived),
        "last_msg_preview": c.last_msg_preview,
        "owner_user_id": c.owner_user_id,
        "members": [
            {
                "member_id": m.member_id,
                "member_type": m.member_type,
                "role": m.role,
                "joined_at": m.joined_at,
            }
            for m in (members or [])
        ],
    }


async def list_conversations(
    s: AsyncSession,
    *,
    include_archived: bool = False,
    query: Optional[str] = None,
) -> list[dict[str, Any]]:
    stmt = select(Conversation).order_by(
        desc(Conversation.pinned), desc(Conversation.updated_at)
    )
    if not include_archived:
        stmt = stmt.where(Conversation.archived == 0)
    if query:
        stmt = stmt.where(Conversation.title.contains(query))
    convs = (await s.scalars(stmt)).all()
    out: list[dict[str, Any]] = []
    for c in convs:
        members = (
            await s.scalars(
                select(ConversationMember).where(
                    ConversationMember.conversation_id == c.id
                )
            )
        ).all()
        out.append(conv_to_dict(c, list(members)))
    return out


async def list_messages(
    s: AsyncSession,
    conversation_id: str,
    *,
    before_id: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """游标分页拉取消息。

    返回结果按 ``created_at`` **升序**（"时间正序"），方便前端直接 append。
    `before_id` 为锚点：只返回 ``created_at < anchor.created_at`` 的更早消息。
    """
    limit = max(1, min(int(limit), 200))
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(desc(Message.created_at))
        .limit(limit)
    )
    if before_id:
        anchor = await s.scalar(select(Message).where(Message.id == before_id))
        if anchor is not None:
            stmt = stmt.where(Message.created_at < anchor.created_at)

    msgs = (await s.scalars(stmt)).all()
    return [message_to_dict(m) for m in sorted(msgs, key=lambda x: x.created_at)]


async def get_conversation(
    s: AsyncSession, conversation_id: str
) -> Optional[dict[str, Any]]:
    c = await s.get(Conversation, conversation_id)
    if c is None:
        return None
    members = (
        await s.scalars(
            select(ConversationMember).where(
                ConversationMember.conversation_id == conversation_id
            )
        )
    ).all()
    return conv_to_dict(c, list(members))


async def delete_conversation(
    s: AsyncSession,
    conversation_id: str,
) -> bool:
    c = await s.get(Conversation, conversation_id)
    if c is None:
        return False
    await s.delete(c)
    await s.commit()
    return True


async def update_conversation(
    s: AsyncSession,
    conversation_id: str,
    *,
    title: Optional[str] = None,
    pinned: Optional[bool] = None,
    archived: Optional[bool] = None,
) -> Optional[dict[str, Any]]:
    """更新会话的 title / pinned / archived 字段。"""
    c = await s.get(Conversation, conversation_id)
    if c is None:
        return None
    if title is not None:
        title = title.strip()
        if not title:
            raise ValueError("title required")
        c.title = title
    if pinned is not None:
        c.pinned = 1 if pinned else 0
    if archived is not None:
        c.archived = 1 if archived else 0
    c.updated_at = now_ms()
    await s.commit()
    members = (
        await s.scalars(
            select(ConversationMember).where(
                ConversationMember.conversation_id == conversation_id
            )
        )
    ).all()
    return conv_to_dict(c, list(members))


async def create_conversation(
    s: AsyncSession,
    *,
    title: str,
    type_: str = "single",
    owner_user_id: str,
    agent_ids: Optional[list[str]] = None,
    conversation_id: Optional[str] = None,
) -> dict[str, Any]:
    """新建一个会话；自动落 owner + 一组 agent 成员。

    业务约束（与 SPEC F-W2-5 对齐）：

    - ``title`` 必填、非空；
    - ``type_`` ∈ ``{'single','group'}``；
    - ``type_ == 'group'`` 时 **必须** 至少 1 个 ``agent_id``；
    - 所有 ``agent_id`` 必须存在于 ``agent`` 表；任意一个未知就整体回滚；
    - 重复的 ``agent_id`` 按集合去重后写入（保持出现顺序）。

    抛 ``ValueError`` 时 message 是稳定的小写枚举（``title required`` /
    ``invalid_type`` / ``group_requires_agents`` / ``unknown_agent``），
    交给上层 ``api/rest.py`` 映射为 HTTP status code + 文案。
    """
    title = (title or "").strip()
    if not title:
        raise ValueError("title required")
    if type_ not in ("single", "group"):
        raise ValueError("invalid_type")

    # 去重，保留首次出现顺序，避免 ConversationMember 主键冲突
    raw_agent_ids = list(agent_ids or [])
    deduped_agent_ids: list[str] = []
    seen: set[str] = set()
    for aid in raw_agent_ids:
        if aid and aid not in seen:
            seen.add(aid)
            deduped_agent_ids.append(aid)

    if type_ == "group" and not deduped_agent_ids:
        raise ValueError("group_requires_agents")

    from orchestrator import ORCHESTRATOR_AGENT_ID

    if type_ == "group" and ORCHESTRATOR_AGENT_ID not in deduped_agent_ids:
        deduped_agent_ids.insert(0, ORCHESTRATOR_AGENT_ID)

    if deduped_agent_ids:
        existing = await get_existing_agent_ids(s, deduped_agent_ids)
        if existing != set(deduped_agent_ids):
            # SPEC F-W2-5 反例 2：含未知 agent_id 时整体回滚、不创建会话
            raise ValueError("unknown_agent")

    ts = now_ms()
    cid = conversation_id or new_id("conv")
    c = Conversation(
        id=cid,
        title=title,
        type=type_,
        owner_user_id=owner_user_id,
        created_at=ts,
        updated_at=ts,
    )
    s.add(c)
    s.add(
        ConversationMember(
            conversation_id=cid,
            member_id=owner_user_id,
            member_type="user",
            role="owner",
            joined_at=ts,
        )
    )
    for aid in deduped_agent_ids:
        s.add(
            ConversationMember(
                conversation_id=cid,
                member_id=aid,
                member_type="agent",
                role="worker",
                joined_at=ts,
            )
        )
    await s.commit()

    # 重新 load 以 attach 完整成员关系
    members = (
        await s.scalars(
            select(ConversationMember).where(ConversationMember.conversation_id == cid)
        )
    ).all()
    return conv_to_dict(c, list(members))
