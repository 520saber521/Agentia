"""DB 层 + services 层联合测试。

围绕 ``docs/ARCHITECTURE.md`` §6.2 的 schema 与 §5.3 的 Conversation Service 职责：

- ``init_db`` / ``seed_defaults`` 幂等
- ``create_message`` 顺手更新会话预览与 ``updated_at``
- ``list_messages`` 时间正序 + ``before_id`` 游标
- ``update_message_content`` 写回最终文本，会话预览同步
- ``list_conversations`` 按 ``pinned desc, updated_at desc`` 排序
"""

from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy import select

from db.engine import get_sessionmaker, init_db
from db.models import Agent, Conversation, ConversationMember, Message
from db.seed import (
    DEFAULT_AGENT_ID,
    DEFAULT_AGENT_ID_2,
    DEFAULT_CONV_ID,
    DEFAULT_USER_ID,
    seed_defaults,
)
from services.agent import list_agents
from services.conversation import list_conversations, list_messages
from services.message import create_message, update_message_content
from handlers.send_message import persist_artifact_chunk


async def test_init_db_is_idempotent(db_env) -> None:
    """``init_db`` 多次调用不报错也不破坏现有表。"""
    await init_db()  # 再来一次
    Session = get_sessionmaker()
    async with Session() as s:
        # 表存在但暂无数据
        assert (await s.scalar(select(Agent))) is None


async def test_seed_defaults_creates_baseline(db_env) -> None:
    await seed_defaults()
    Session = get_sessionmaker()
    async with Session() as s:
        agent = await s.scalar(select(Agent).where(Agent.id == DEFAULT_AGENT_ID))
        assert agent is not None
        assert agent.name == "MockAdapter"
        assert agent.adapter_type == "mock"
        assert agent.avatar == "🧪"
        caps = json.loads(agent.capabilities)
        assert isinstance(caps, list)
        assert "testing" in caps

        conv = await s.scalar(
            select(Conversation).where(Conversation.id == DEFAULT_CONV_ID)
        )
        assert conv is not None
        assert conv.owner_user_id == DEFAULT_USER_ID

        members = (
            await s.scalars(
                select(ConversationMember).where(
                    ConversationMember.conversation_id == DEFAULT_CONV_ID
                )
            )
        ).all()
        ids = {m.member_id for m in members}
        assert ids == {DEFAULT_USER_ID, DEFAULT_AGENT_ID}


async def test_seed_defaults_is_idempotent(db_env) -> None:
    """W2 F-W2-5：seed 现在落 2 个 Agent（``agent_mock`` + ``agent_mock_2``）。"""
    await seed_defaults()
    await seed_defaults()
    await seed_defaults()
    Session = get_sessionmaker()
    async with Session() as s:
        agents = (await s.scalars(select(Agent))).all()
        convs = (await s.scalars(select(Conversation))).all()
        members = (await s.scalars(select(ConversationMember))).all()
        agent_ids = {a.id for a in agents}
        assert {DEFAULT_AGENT_ID, DEFAULT_AGENT_ID_2}.issubset(agent_ids)
        assert len(agents) == len(agent_ids), "seed 应保持幂等不重复插入"
        assert len(convs) == 1
        # conv_demo 仅含 user + agent_mock 两个成员；agent_mock_2 不自动加入 demo 会话
        assert len(members) == 2


async def test_create_message_touches_conversation(db_env) -> None:
    await seed_defaults()
    Session = get_sessionmaker()
    async with Session() as s:
        m = await create_message(
            s,
            conversation_id=DEFAULT_CONV_ID,
            sender_id=DEFAULT_USER_ID,
            sender_type="user",
            content={"type": "text", "text": "hello world"},
        )
        conv = await s.get(Conversation, DEFAULT_CONV_ID)
        assert conv is not None
        assert conv.last_msg_preview == "hello world"
        assert conv.updated_at >= m.created_at


async def test_list_messages_time_order_and_pagination(db_env) -> None:
    await seed_defaults()
    Session = get_sessionmaker()
    async with Session() as s:
        m1 = await create_message(
            s,
            conversation_id=DEFAULT_CONV_ID,
            sender_id=DEFAULT_USER_ID,
            sender_type="user",
            content={"type": "text", "text": "one"},
        )
        await asyncio.sleep(0.01)
        m2 = await create_message(
            s,
            conversation_id=DEFAULT_CONV_ID,
            sender_id=DEFAULT_USER_ID,
            sender_type="user",
            content={"type": "text", "text": "two"},
        )
        await asyncio.sleep(0.01)
        m3 = await create_message(
            s,
            conversation_id=DEFAULT_CONV_ID,
            sender_id=DEFAULT_USER_ID,
            sender_type="user",
            content={"type": "text", "text": "three"},
        )

        msgs = await list_messages(s, DEFAULT_CONV_ID, limit=10)
        assert [m["id"] for m in msgs] == [m1.id, m2.id, m3.id]

        # 游标：before=m3 → 更早的 m1, m2（仍为时间正序）
        earlier = await list_messages(s, DEFAULT_CONV_ID, before_id=m3.id, limit=10)
        assert [m["id"] for m in earlier] == [m1.id, m2.id]


async def test_update_message_content_writes_back(db_env) -> None:
    await seed_defaults()
    Session = get_sessionmaker()
    async with Session() as s:
        m = await create_message(
            s,
            conversation_id=DEFAULT_CONV_ID,
            sender_id=DEFAULT_AGENT_ID,
            sender_type="agent",
            content={"type": "text", "text": ""},
        )
    async with Session() as s:
        updated = await update_message_content(
            s, m.id, {"type": "text", "text": "final answer"}
        )
        assert updated is not None
    async with Session() as s:
        m2 = await s.get(Message, m.id)
        assert m2 is not None
        assert json.loads(m2.content)["text"] == "final answer"
        conv = await s.get(Conversation, DEFAULT_CONV_ID)
        assert conv is not None
        assert conv.last_msg_preview == "final answer"


async def test_list_conversations_returns_members(db_env) -> None:
    await seed_defaults()
    Session = get_sessionmaker()
    async with Session() as s:
        await create_message(
            s,
            conversation_id=DEFAULT_CONV_ID,
            sender_id=DEFAULT_USER_ID,
            sender_type="user",
            content={"type": "text", "text": "hey"},
        )
        out = await list_conversations(s)
    assert len(out) == 1
    c = out[0]
    assert c["id"] == DEFAULT_CONV_ID
    assert c["last_msg_preview"] == "hey"
    member_ids = {m["member_id"] for m in c["members"]}
    assert member_ids == {DEFAULT_USER_ID, DEFAULT_AGENT_ID}


async def test_update_message_for_unknown_id_returns_none(db_env) -> None:
    await seed_defaults()
    Session = get_sessionmaker()
    async with Session() as s:
        result = await update_message_content(s, "msg_nope", {"type": "text", "text": "x"})
        assert result is None


async def test_artifact_chunk_persists_metadata_only(db_env) -> None:
    await seed_defaults()
    Session = get_sessionmaker()
    async with Session() as s:
        msg = await create_message(
            s,
            conversation_id=DEFAULT_CONV_ID,
            sender_id=DEFAULT_AGENT_ID,
            sender_type="agent",
            content={"type": "text", "text": ""},
        )

    result = await persist_artifact_chunk(
        Session,
        msg.id,
        DEFAULT_CONV_ID,
        DEFAULT_AGENT_ID,
        {
            "kind": "code",
            "title": "hello.py",
            "mime_type": "text/x-python",
            "file_name": "hello.py",
            "content": "print('hello')\n",
            "meta": {"language": "python"},
        },
    )
    assert result is not None
    assert result["content"]["type"] == "code"
    assert result["content"]["artifact_id"] == result["artifact"]["id"]
    assert "code" not in result["content"]

    async with Session() as s:
        stored = await s.get(Message, msg.id)
        assert stored is not None
        assert stored.artifact_id == result["artifact"]["id"]
        content = json.loads(stored.content)
        assert content["artifact_id"] == result["artifact"]["id"]
        assert "code" not in content


async def test_create_conversation_with_members(db_env) -> None:
    """W2 F-W2-5：用真实存在的两个 seeded agent 建群。"""
    from services.conversation import create_conversation

    await seed_defaults()
    Session = get_sessionmaker()
    async with Session() as s:
        conv = await create_conversation(
            s,
            title="测试群聊",
            type_="group",
            owner_user_id=DEFAULT_USER_ID,
            agent_ids=[DEFAULT_AGENT_ID, DEFAULT_AGENT_ID_2],
        )
    assert conv["title"] == "测试群聊"
    assert conv["type"] == "group"
    assert conv["owner_user_id"] == DEFAULT_USER_ID
    member_ids = {m["member_id"] for m in conv["members"]}
    assert member_ids == {DEFAULT_USER_ID, DEFAULT_AGENT_ID, DEFAULT_AGENT_ID_2}

    Session = get_sessionmaker()
    async with Session() as s:
        listed = await list_conversations(s)
    assert any(c["id"] == conv["id"] for c in listed)


async def test_create_conversation_rejects_bad_input(db_env) -> None:
    """W2 F-W2-5：错误码用稳定枚举（``title required`` / ``invalid_type``）。"""
    from services.conversation import create_conversation

    await seed_defaults()
    Session = get_sessionmaker()
    async with Session() as s:
        with pytest.raises(ValueError, match="title required"):
            await create_conversation(s, title="   ", owner_user_id=DEFAULT_USER_ID)

        with pytest.raises(ValueError, match="invalid_type"):
            await create_conversation(
                s, title="ok", type_="weird", owner_user_id=DEFAULT_USER_ID
            )


# ---------------------------------------------------------------------------
# W2 F-W2-5 新增
# ---------------------------------------------------------------------------


async def test_list_agents_returns_seeded(db_env) -> None:
    """SPEC F-W2-5 数据源：``GET /api/agents`` 至少能拉到两个 seeded agent。"""
    await seed_defaults()
    Session = get_sessionmaker()
    async with Session() as s:
        agents = await list_agents(s)
    ids = [a["id"] for a in agents]
    assert DEFAULT_AGENT_ID in ids
    assert DEFAULT_AGENT_ID_2 in ids
    # name 升序：检查 sorted 一致
    names = [a["name"] for a in agents]
    assert names == sorted(names), "list_agents 必须按 name 升序"
    # 不应在出参里泄漏 ``config`` 等敏感字段（W5 起承载 api_key）
    assert "config" not in agents[0]


async def test_create_conversation_group_requires_agents(db_env) -> None:
    """SPEC F-W2-5：type=group 但 agent_ids=[] 必须 ValueError(group_requires_agents)。"""
    from services.conversation import create_conversation

    await seed_defaults()
    Session = get_sessionmaker()
    async with Session() as s:
        with pytest.raises(ValueError, match="group_requires_agents"):
            await create_conversation(
                s,
                title="空群聊",
                type_="group",
                owner_user_id=DEFAULT_USER_ID,
                agent_ids=[],
            )


async def test_create_conversation_rejects_unknown_agent(db_env) -> None:
    """SPEC F-W2-5 反例 2：含未知 agent_id 必须整体回滚、不创建会话。"""
    from services.conversation import create_conversation

    await seed_defaults()
    Session = get_sessionmaker()
    async with Session() as s:
        with pytest.raises(ValueError, match="unknown_agent"):
            await create_conversation(
                s,
                title="坏 agent",
                type_="group",
                owner_user_id=DEFAULT_USER_ID,
                agent_ids=[DEFAULT_AGENT_ID, "agent_does_not_exist"],
            )

    # 二次 list_conversations 不应看到这条"坏 agent"
    Session = get_sessionmaker()
    async with Session() as s:
        listed = await list_conversations(s)
    titles = {c["title"] for c in listed}
    assert "坏 agent" not in titles


async def test_create_conversation_dedupes_agent_ids(db_env) -> None:
    """SPEC F-W2-5 反例 3：重复 agent_id 按集合去重，不报错。"""
    from services.conversation import create_conversation

    await seed_defaults()
    Session = get_sessionmaker()
    async with Session() as s:
        conv = await create_conversation(
            s,
            title="去重测试",
            type_="group",
            owner_user_id=DEFAULT_USER_ID,
            agent_ids=[
                DEFAULT_AGENT_ID,
                DEFAULT_AGENT_ID,
                DEFAULT_AGENT_ID_2,
                DEFAULT_AGENT_ID,
            ],
        )
    member_ids = [m["member_id"] for m in conv["members"]]
    # owner + 2 agents（去重后），共 3 条
    assert len(member_ids) == 3
    assert set(member_ids) == {DEFAULT_USER_ID, DEFAULT_AGENT_ID, DEFAULT_AGENT_ID_2}
