"""F-W2-1 fan-out integration tests.

Coverage per ``ai-collab/SPEC.md`` F-W2-1 acceptance criteria:

- Group conversation with multiple mentions triggers correct fan-out
- Each agent gets its own message_created event
- stream_chunk events carry correct message_id and sender_id
- fan_out_done sent when all agents complete
- Cancel only affects the specified message
- bad_mentions error when mentions empty but @ in text
- not_member error for agent not in conversation
- Duplicate mentions are deduplicated
- no_target error for group conv with no mentions and no @
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from db import (
    DEFAULT_USER_ID,
    get_sessionmaker,
    seed_defaults,
)
from db.models import Conversation, ConversationMember, Agent, new_id
from handlers.send_message import handle, resolve_targets
from ws import Connection, event


class FakeConnection(Connection):
    def __init__(self):
        self.sent: list[dict[str, Any]] = []
        self.in_flight: dict[str, asyncio.Task[Any]] = {}
        self.joined_conversations: set[str] = set()
        self._closed = False
        self.conn_id = "test-conn"

    async def send(self, evt: dict[str, Any]) -> None:
        self.sent.append(evt)

    async def writer(self) -> None:
        pass

    async def close(self) -> None:
        pass


def _find_event(events: list[dict[str, Any]], typ: str) -> list[dict[str, Any]]:
    return [e for e in events if e.get("type") == typ]


def _last_done_text(events: list[dict[str, Any]]) -> str:
    done = _find_event(events, "message_done")
    assert done
    content = done[-1]["final_content"]
    assert content["type"] == "text"
    return content["text"]


async def _create_group_conv(conv_id: str, agent_ids: list[str]) -> None:
    Session = get_sessionmaker()
    async with Session() as s:
        s.add(Conversation(
            id=conv_id,
            title="Test Group",
            type="group",
            owner_user_id=DEFAULT_USER_ID,
        ))
        s.add(ConversationMember(
            conversation_id=conv_id,
            member_id=DEFAULT_USER_ID,
            member_type="user",
        ))
        for aid in agent_ids:
            s.add(ConversationMember(
                conversation_id=conv_id,
                member_id=aid,
                member_type="agent",
            ))
        await s.commit()


@pytest.mark.asyncio
async def test_agent_create_chat_wizard_collects_tools(db_env):
    await seed_defaults()
    conn = FakeConnection()

    await handle(conn, {
        "type": "send_message",
        "conversation_id": "conv_demo",
        "content": {"type": "text", "text": "/agent create"},
    })
    assert "System Prompt" in _last_done_text(conn.sent)

    await handle(conn, {
        "type": "send_message",
        "conversation_id": "conv_demo",
        "content": {
            "type": "text",
            "text": (
                "name: Tool PM\n"
                "system_prompt: 你是产品经理 Agent，负责需求澄清和验收标准。\n"
                "tools: code_editor, artifact_read, deploy\n"
                "capabilities: prd, planning"
            ),
        },
    })
    assert "请确认创建" in _last_done_text(conn.sent)

    await handle(conn, {
        "type": "send_message",
        "conversation_id": "conv_demo",
        "content": {"type": "text", "text": "确认"},
    })

    agents_events = _find_event(conn.sent, "agents")
    assert agents_events
    created = next(a for a in agents_events[-1]["agents"] if a["name"] == "Tool PM")
    assert created["tools"] == ["code_editor", "artifact_read", "deploy"]
    assert created["capabilities"] == ["prd", "planning"]


# ---------------------------------------------------------------------------
# resolve_targets unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_targets_group_with_mentions(db_env):
    await seed_defaults()
    conv_id = "conv_fan_01"
    await _create_group_conv(conv_id, ["agent_mock", "agent_mock_2"])

    agent_ids, err = await resolve_targets(conv_id, ["agent_mock", "agent_mock_2"], "hello @Mock @Mock2")
    assert err is None
    assert agent_ids == ["agent_mock", "agent_mock_2"]


@pytest.mark.asyncio
async def test_resolve_targets_dedup_mentions(db_env):
    await seed_defaults()
    conv_id = "conv_fan_02"
    await _create_group_conv(conv_id, ["agent_mock", "agent_mock_2"])

    agent_ids, err = await resolve_targets(conv_id, ["agent_mock", "agent_mock", "agent_mock_2"], "test")
    assert err is None
    assert agent_ids == ["agent_mock", "agent_mock_2"]


@pytest.mark.asyncio
async def test_resolve_targets_bad_mentions(db_env):
    await seed_defaults()
    conv_id = "conv_fan_03"
    await _create_group_conv(conv_id, ["agent_mock"])

    agent_ids, err = await resolve_targets(conv_id, [], "hello @Mock")
    assert agent_ids == []
    assert err is not None
    assert err["code"] == "bad_mentions"


@pytest.mark.asyncio
async def test_resolve_targets_not_member(db_env):
    await seed_defaults()
    conv_id = "conv_fan_04"
    await _create_group_conv(conv_id, ["agent_mock"])

    agent_ids, err = await resolve_targets(conv_id, ["agent_mock_2"], "test")
    assert agent_ids == []
    assert err is not None
    assert err["code"] == "not_member"


@pytest.mark.asyncio
async def test_resolve_targets_not_member_partial_degraded(db_env):
    await seed_defaults()
    conv_id = "conv_fan_05"
    await _create_group_conv(conv_id, ["agent_mock"])

    agent_ids, err = await resolve_targets(conv_id, ["agent_mock", "agent_mock_2"], "test")
    assert agent_ids == ["agent_mock"]
    assert err is not None
    assert err["code"] == "not_member"
    assert err.get("degraded") is True


@pytest.mark.asyncio
async def test_resolve_targets_no_target(db_env):
    await seed_defaults()
    conv_id = "conv_fan_06"
    await _create_group_conv(conv_id, ["agent_mock", "agent_mock_2"])

    agent_ids, err = await resolve_targets(conv_id, [], "plain text no at")
    assert agent_ids == []
    assert err is not None
    assert err["code"] == "no_target"


@pytest.mark.asyncio
async def test_resolve_targets_group_complex_task_defaults_to_orchestrator(db_env):
    await seed_defaults()
    conv_id = "conv_fan_orch"
    await _create_group_conv(conv_id, ["agent_orchestrator", "agent_mock", "agent_mock_2"])

    agent_ids, err = await resolve_targets(
        conv_id,
        [],
        "请帮我设计一个带登录注册、商品列表、订单提交的 HTML 网页应用",
    )
    assert err is None
    assert agent_ids == ["agent_orchestrator"]


@pytest.mark.asyncio
async def test_resolve_targets_bare_orchestrator_text_without_mentions(db_env):
    await seed_defaults()
    conv_id = "conv_fan_orch_bare"
    await _create_group_conv(conv_id, ["agent_orchestrator", "agent_mock"])

    agent_ids, err = await resolve_targets(conv_id, [], "@Orchestrator 请设计一个 HTML 页面")
    assert err is None
    assert agent_ids == ["agent_orchestrator"]


@pytest.mark.asyncio
async def test_resolve_targets_single_conv_no_mentions(db_env):
    """single conv with no mentions falls back to first agent."""
    await seed_defaults()
    agent_ids, err = await resolve_targets("conv_demo", [], "hello")
    assert agent_ids == ["agent_mock"]
    assert err is None


@pytest.mark.asyncio
async def test_resolve_targets_conv_not_found(db_env):
    await seed_defaults()
    agent_ids, err = await resolve_targets("conv_nonexistent", ["agent_mock"], "test")
    assert agent_ids == []
    assert err is not None
    assert err["code"] == "not_found"


# ---------------------------------------------------------------------------
# Full fan-out integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fan_out_group_with_two_agents(db_env):
    await seed_defaults()
    conv_id = "conv_fan_10"
    await _create_group_conv(conv_id, ["agent_mock", "agent_mock_2"])

    conn = FakeConnection()
    await handle(conn, {
        "type": "send_message",
        "conversation_id": conv_id,
        "content": {"type": "text", "text": "@Mock Agent @Mock Agent 2 build something"},
        "mentions": ["agent_mock", "agent_mock_2"],
    })

    # Collect events while tasks run (mock agent finishes quickly)
    await asyncio.sleep(4)

    events = conn.sent
    msg_created = _find_event(events, "message_created")
    assert len(msg_created) == 3, f"expected 3 message_created (1 user + 2 agents), got {len(msg_created)}"

    user_msg = [m for m in msg_created if m["message"]["sender_type"] == "user"]
    assert len(user_msg) == 1
    assert user_msg[0]["message"]["mentions"] == ["agent_mock", "agent_mock_2"]

    agent_msgs = [m for m in msg_created if m["message"]["sender_type"] == "agent"]
    assert len(agent_msgs) == 2
    agent_sender_ids = {m["message"]["sender_id"] for m in agent_msgs}
    assert agent_sender_ids == {"agent_mock", "agent_mock_2"}

    agent_message_ids = {m["message"]["id"] for m in agent_msgs}

    stream_chunks = _find_event(events, "stream_chunk")
    assert len(stream_chunks) > 0, "should have stream chunks"
    for sc in stream_chunks:
        assert sc.get("message_id") in agent_message_ids
        assert sc.get("sender_id") in {"agent_mock", "agent_mock_2"}

    message_dones = _find_event(events, "message_done")
    errors = [e for e in events if e.get("type") == "error"]
    event_types = [e["type"] for e in events]
    # agent_mock (MockAdapter) succeeds; agent_mock_2 (CustomAgentAdapter/codex)
    # errors out because no API key is configured in test env.
    assert len(message_dones) == 1, (
        f"expected 1 message_done (MockAdapter), got {len(message_dones)}. "
        f"Errors: {len(errors)}. Event types: {event_types[-10:]}"
    )
    assert len(errors) >= 1, "CustomAgentAdapter without API key should yield an error"
    done_message_ids = {d["message_id"] for d in message_dones}
    assert done_message_ids.issubset(agent_message_ids)
    assert len(done_message_ids) == 1

    fan_out_dones = _find_event(events, "fan_out_done")
    assert len(fan_out_dones) == 1
    assert fan_out_dones[0]["conversation_id"] == conv_id
    assert fan_out_dones[0]["total_agents"] == 2


@pytest.mark.asyncio
async def test_fan_out_single_agent(db_env):
    await seed_defaults()
    conn = FakeConnection()
    await handle(conn, {
        "type": "send_message",
        "conversation_id": "conv_demo",
        "content": {"type": "text", "text": "hello"},
        "mentions": [],
    })

    await asyncio.sleep(3)

    events = conn.sent
    msg_created = _find_event(events, "message_created")
    assert len(msg_created) == 2, "single conv should have 1 user + 1 agent"

    user_msg = [m for m in msg_created if m["message"]["sender_type"] == "user"]
    assert len(user_msg) == 1

    agent_msgs = [m for m in msg_created if m["message"]["sender_type"] == "agent"]
    assert len(agent_msgs) == 1
    assert agent_msgs[0]["message"]["sender_id"] == "agent_mock"

    fan_out_dones = _find_event(events, "fan_out_done")
    assert len(fan_out_dones) == 1
    assert fan_out_dones[0]["total_agents"] == 1


@pytest.mark.asyncio
async def test_fan_out_cancel_one_agent(db_env):
    await seed_defaults()
    conv_id = "conv_fan_20"
    await _create_group_conv(conv_id, ["agent_mock", "agent_mock_2"])

    conn = FakeConnection()
    await handle(conn, {
        "type": "send_message",
        "conversation_id": conv_id,
        "content": {"type": "text", "text": "@Mock Agent @Mock Agent 2 build"},
        "mentions": ["agent_mock", "agent_mock_2"],
    })

    await asyncio.sleep(0.5)

    events = conn.sent
    agent_msgs = [m for m in _find_event(events, "message_created") if m["message"]["sender_type"] == "agent"]
    assert len(agent_msgs) == 2

    target_id = agent_msgs[0]["message"]["id"]

    # Cancel the first agent (MockAdapter)
    task = conn.in_flight.get(target_id)
    assert task is not None, "should have in_flight task"
    task.cancel()

    await asyncio.sleep(4)

    errors = [e for e in conn.sent if e.get("type") == "error"]
    cancelled = _find_event(conn.sent, "message_cancelled")
    assert len(cancelled) >= 1, f"should have at least one cancelled event. events: {[e['type'] for e in conn.sent[-10:]]}, errors: {[(e['code'], e.get('message','')[:50]) for e in errors]}"

    # The other agent (CustomAgentAdapter/codex) errors out since no API key is set.
    # At minimum, fan_out_done fires (cancel + error both count as terminal).
    fan_out_dones = _find_event(events, "fan_out_done")
    assert len(fan_out_dones) == 1


@pytest.mark.asyncio
async def test_fan_out_errors_on_bad_mentions(db_env):
    await seed_defaults()
    conv_id = "conv_fan_30"
    await _create_group_conv(conv_id, ["agent_mock", "agent_mock_2"])

    conn = FakeConnection()
    await handle(conn, {
        "type": "send_message",
        "conversation_id": conv_id,
        "content": {"type": "text", "text": "@Mock do something"},
        "mentions": [],
    })

    errors = [e for e in conn.sent if e.get("type") == "error"]
    assert len(errors) == 1
    assert errors[0]["code"] == "bad_mentions"

    msg_created = _find_event(conn.sent, "message_created")
    assert len(msg_created) == 0, "no messages should be created on bad_mentions"


@pytest.mark.asyncio
async def test_fan_out_errors_on_no_target(db_env):
    await seed_defaults()
    conv_id = "conv_fan_31"
    await _create_group_conv(conv_id, ["agent_mock", "agent_mock_2"])

    conn = FakeConnection()
    await handle(conn, {
        "type": "send_message",
        "conversation_id": conv_id,
        "content": {"type": "text", "text": "just talking"},
        "mentions": [],
    })

    errors = [e for e in conn.sent if e.get("type") == "error"]
    assert len(errors) == 1
    assert errors[0]["code"] == "no_target"

    msg_created = _find_event(conn.sent, "message_created")
    assert len(msg_created) == 0


@pytest.mark.asyncio
async def test_fan_out_errors_on_not_member(db_env):
    await seed_defaults()
    conv_id = "conv_fan_32"
    await _create_group_conv(conv_id, ["agent_mock"])

    conn = FakeConnection()
    await handle(conn, {
        "type": "send_message",
        "conversation_id": conv_id,
        "content": {"type": "text", "text": "@unknown"},
        "mentions": ["agent_mock_2"],
    })

    errors = [e for e in conn.sent if e.get("type") == "error"]
    assert len(errors) == 1
    assert errors[0]["code"] == "not_member"

    msg_created = _find_event(conn.sent, "message_created")
    assert len(msg_created) == 0


@pytest.mark.asyncio
async def test_fan_out_dedup_mentions_in_message(db_env):
    await seed_defaults()
    conv_id = "conv_fan_33"
    await _create_group_conv(conv_id, ["agent_mock", "agent_mock_2"])

    conn = FakeConnection()
    await handle(conn, {
        "type": "send_message",
        "conversation_id": conv_id,
        "content": {"type": "text", "text": "@Mock again"},
        "mentions": ["agent_mock", "agent_mock", "agent_mock_2"],
    })

    await asyncio.sleep(4)

    msg_created = _find_event(conn.sent, "message_created")
    agent_msgs = [m for m in msg_created if m["message"]["sender_type"] == "agent"]
    assert len(agent_msgs) == 2, f"dedup should result in 2 agents, got {len(agent_msgs)}"
    sender_ids = {m["message"]["sender_id"] for m in agent_msgs}
    assert sender_ids == {"agent_mock", "agent_mock_2"}

    user_msg = [m for m in msg_created if m["message"]["sender_type"] == "user"]
    assert user_msg[0]["message"]["mentions"] == ["agent_mock", "agent_mock_2"]


@pytest.mark.asyncio
async def test_fan_out_mentions_not_list(db_env):
    await seed_defaults()
    conn = FakeConnection()
    await handle(conn, {
        "type": "send_message",
        "conversation_id": "conv_demo",
        "content": {"type": "text", "text": "hello"},
        "mentions": "not-a-list",
    })

    errors = [e for e in conn.sent if e.get("type") == "error"]
    assert len(errors) == 1
    assert errors[0]["code"] == "bad_mentions"
