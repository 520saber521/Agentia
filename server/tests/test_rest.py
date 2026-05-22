"""REST 接口测试（用 httpx + ASGITransport 直接打 FastAPI app，无需起 server）。"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client(db_env):
    # ASGITransport 不会触发 FastAPI 的 lifespan，需要手动播一次 init + seed。
    from db import init_db, seed_defaults
    from main import app

    await init_db()
    await seed_defaults()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_health_ok(client) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["server"].startswith("agenthub-bff/")


async def test_list_conversations_returns_seeded(client) -> None:
    r = await client.get("/api/conversations")
    assert r.status_code == 200
    convs = r.json()["conversations"]
    assert any(c["id"] == "conv_demo" for c in convs)
    demo = next(c for c in convs if c["id"] == "conv_demo")
    assert demo["type"] == "single"
    member_types = {m["member_type"] for m in demo["members"]}
    assert member_types == {"user", "agent"}


async def test_get_conversation_ok_and_404(client) -> None:
    r = await client.get("/api/conversations/conv_demo")
    assert r.status_code == 200
    assert r.json()["conversation"]["id"] == "conv_demo"

    r2 = await client.get("/api/conversations/conv_does_not_exist")
    assert r2.status_code == 404


async def test_list_messages_empty_then_after_seed(client) -> None:
    r = await client.get("/api/conversations/conv_demo/messages")
    assert r.status_code == 200
    body = r.json()
    assert body["conversation_id"] == "conv_demo"
    assert body["messages"] == []
    assert body["limit"] == 50


async def test_list_messages_pagination_defaults(client) -> None:
    r = await client.get("/api/conversations/conv_demo/messages?limit=10")
    assert r.status_code == 200
    assert r.json()["limit"] == 10

    r2 = await client.get("/api/conversations/conv_demo/messages?limit=500")
    assert r2.status_code == 422  # FastAPI Query(le=200) 触发


async def test_list_messages_bad_limit(client) -> None:
    r = await client.get("/api/conversations/conv_demo/messages?limit=0")
    assert r.status_code == 422


async def test_create_conversation_ok(client) -> None:
    r = await client.post(
        "/api/conversations",
        json={"title": "Day5 新建", "type": "group", "agent_ids": ["agent_mock"]},
    )
    assert r.status_code == 201
    conv = r.json()["conversation"]
    assert conv["title"] == "Day5 新建"
    assert conv["type"] == "group"
    member_ids = {m["member_id"] for m in conv["members"]}
    assert "agent_mock" in member_ids
    assert "user_demo" in member_ids

    r2 = await client.get(f"/api/conversations/{conv['id']}")
    assert r2.status_code == 200


async def test_create_conversation_validation(client) -> None:
    """Pydantic 层校验：空 title / 非法 type 直接 422，不进 service。"""
    r = await client.post("/api/conversations", json={"title": ""})
    assert r.status_code == 422

    r2 = await client.post(
        "/api/conversations", json={"title": "ok", "type": "weird"}
    )
    assert r2.status_code == 422


# ---------------------------------------------------------------------------
# W2 F-W2-5 新增
# ---------------------------------------------------------------------------


async def test_list_agents_endpoint(client) -> None:
    """SPEC F-W2-5：``GET /api/agents`` 返回 ≥2 个 seeded agent，按 name 升序。"""
    r = await client.get("/api/agents")
    assert r.status_code == 200
    agents = r.json()["agents"]
    ids = {a["id"] for a in agents}
    assert "agent_mock" in ids
    assert "agent_mock_2" in ids

    names = [a["name"] for a in agents]
    assert names == sorted(names)

    sample = agents[0]
    assert {"id", "name", "adapter_type", "capabilities"} <= set(sample.keys())
    assert "config" not in sample, "敏感字段 config 不应通过 REST 暴露"


async def test_create_conversation_group_requires_agents_endpoint(client) -> None:
    """SPEC F-W2-5：type=group + agent_ids=[] 必须 422 detail=group_requires_agents。"""
    r = await client.post(
        "/api/conversations",
        json={"title": "空群", "type": "group", "agent_ids": []},
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "group_requires_agents"


async def test_create_conversation_unknown_agent_endpoint(client) -> None:
    """SPEC F-W2-5 反例 2：含未知 agent_id 必须 422 detail=unknown_agent，事务回滚。"""
    r = await client.post(
        "/api/conversations",
        json={
            "title": "坏 agent",
            "type": "group",
            "agent_ids": ["agent_mock", "agent_does_not_exist"],
        },
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "unknown_agent"

    r2 = await client.get("/api/conversations")
    titles = {c["title"] for c in r2.json()["conversations"]}
    assert "坏 agent" not in titles


async def test_create_conversation_dedupes_agent_ids_endpoint(client) -> None:
    """SPEC F-W2-5 反例 3：重复 agent_id 按集合去重，不报错。"""
    r = await client.post(
        "/api/conversations",
        json={
            "title": "去重",
            "type": "group",
            "agent_ids": ["agent_mock", "agent_mock", "agent_mock_2", "agent_mock"],
        },
    )
    assert r.status_code == 201
    conv = r.json()["conversation"]
    member_ids = [m["member_id"] for m in conv["members"]]
    # owner + 2 agents（去重后），共 3
    assert len(member_ids) == 3
    assert set(member_ids) == {"user_demo", "agent_mock", "agent_mock_2"}


async def test_create_conversation_single_with_agent_ok(client) -> None:
    """W2 F-W2-5：type=single 不强制 agent_ids 非空（兼容 W1 行为）。"""
    r = await client.post(
        "/api/conversations",
        json={"title": "单聊新建", "type": "single", "agent_ids": ["agent_mock"]},
    )
    assert r.status_code == 201
    conv = r.json()["conversation"]
    assert conv["type"] == "single"


# ---------------------------------------------------------------------------
# W4 F-W4-5 Diff apply
# ---------------------------------------------------------------------------


async def test_apply_diff_creates_artifact_version_and_message(client) -> None:
    created = await client.post(
        "/api/artifacts",
        json={
            "conversation_id": "conv_demo",
            "kind": "code",
            "title": "hello.py",
            "mime_type": "text/x-python",
            "file_name": "hello.py",
            "content": "print('old')\n",
            "meta": {"language": "python"},
        },
    )
    assert created.status_code == 201
    base = created.json()["artifact"]

    applied = await client.post(
        f"/api/artifacts/{base['id']}/apply-diff",
        json={
            "before": "print('old')\n",
            "after": "print('new')\n",
            "summary": "更新输出文本",
            "file_name": "hello.py",
        },
    )
    assert applied.status_code == 200
    body = applied.json()
    assert body["artifact"]["parent_id"] == base["id"]
    assert body["artifact"]["version"] == 2
    assert body["message"]["artifact_id"] == body["artifact"]["id"]
    assert body["message"]["content"]["type"] == "code"

    content = await client.get(f"/api/artifacts/{body['artifact']['id']}/content")
    assert content.status_code == 200
    assert content.json()["content"] == "print('new')\n"


async def test_create_artifact_version_inserts_diff_message(client) -> None:
    created = await client.post(
        "/api/artifacts",
        json={
            "conversation_id": "conv_demo",
            "kind": "code",
            "title": "hello.py",
            "mime_type": "text/x-python",
            "file_name": "hello.py",
            "content": "print('old')\n",
        },
    )
    assert created.status_code == 201
    base = created.json()["artifact"]

    saved = await client.post(
        "/api/artifacts",
        json={
            "conversation_id": "conv_demo",
            "kind": "code",
            "title": "hello.py",
            "mime_type": "text/x-python",
            "file_name": "hello.py",
            "content": "print('new')\n",
            "parent_id": base["id"],
        },
    )
    assert saved.status_code == 201
    body = saved.json()
    assert body["artifact"]["parent_id"] == base["id"]
    assert body["message"]["artifact_id"] == body["artifact"]["id"]
    assert body["message"]["content"]["type"] == "diff"
    assert body["message"]["content"]["before"] == "print('old')\n"
    assert body["message"]["content"]["after"] == "print('new')\n"


async def test_apply_diff_rejects_outdated_base_version(client) -> None:
    created = await client.post(
        "/api/artifacts",
        json={
            "conversation_id": "conv_demo",
            "kind": "code",
            "title": "hello.py",
            "mime_type": "text/x-python",
            "file_name": "hello.py",
            "content": "print('old')\n",
        },
    )
    base = created.json()["artifact"]

    first = await client.post(
        f"/api/artifacts/{base['id']}/apply-diff",
        json={"before": "print('old')\n", "after": "print('new')\n"},
    )
    assert first.status_code == 200

    second = await client.post(
        f"/api/artifacts/{base['id']}/apply-diff",
        json={"before": "print('old')\n", "after": "print('again')\n"},
    )
    assert second.status_code == 409
    assert second.json()["detail"] == "artifact_conflict"
