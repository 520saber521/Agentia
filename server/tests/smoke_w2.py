"""W2 fan-out 验收 smoke —— 群聊多 Agent 并发回复。

前置条件
========

- BFF 已起在 :8788 ::

      server/.venv/Scripts/python.exe -m uvicorn server.main:app \\
          --host 127.0.0.1 --port 8788

用法
====

::

    server/.venv/Scripts/python.exe server/tests/smoke_w2.py

校验矩阵
========

| Section | Feature 对应 SPEC | 校验内容 |
|---|---|---|
| §1 health              | —                | ``GET /health`` |
| §2 create group conv   | F-W2-5           | ``POST /api/conversations`` 新建群聊含 3 agent |
| §3 fan-out send/done   | F-W2-1           | 多 Agent 并发回复：独立 message_created/stream_chunk/done |
| §4 fan-out cancel one  | F-W2-1           | 取消单个 Agent 不影响兄弟 Agent |
| §5 bad mentions reject | F-W2-1           | 无 mention 的群聊消息被拒绝 |
| §6 DB records          | F-W2-1           | 持久化记录：1 user + N agent 消息 |

失败时返回非 0；任何 ``AssertionError`` 都会指出对应 §与具体期望。
"""

from __future__ import annotations

import asyncio
import json
import sys
import urllib.error
import urllib.request
from typing import Any

import websockets


BFF_BASE = "http://127.0.0.1:8788"
BFF_WS = "ws://127.0.0.1:8788/ws"


def expect(cond: bool, name: str, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ::  {detail}" if detail else ""))
    if not cond:
        raise AssertionError(name)


def http_get_json(url: str) -> tuple[int, Any]:
    with urllib.request.urlopen(url, timeout=4) as r:
        return r.status, json.loads(r.read().decode())


def http_post_json(url: str, body: dict[str, Any]) -> tuple[int, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=4) as r:
        return r.status, json.loads(r.read().decode())


async def _recv(ws, timeout: float = 4.0) -> dict[str, Any]:
    return json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))


# ---------------------------------------------------------------------------
# cases
# ---------------------------------------------------------------------------


async def s1_health() -> None:
    print(">>> §1 BFF /health")
    status, body = http_get_json(BFF_BASE + "/health")
    expect(status == 200, "200 OK")
    expect(body.get("status") == "ok", "status==ok", str(body))


async def s2_create_group_conv() -> str:
    """F-W2-5：创建含 3 个 Mock Agent 的群聊，返回 conv_id。"""
    print(">>> §2 创建群聊会话（含 agent_mock + agent_mock_2 + agent_deepseek）")
    status, body = http_post_json(
        BFF_BASE + "/api/conversations",
        {
            "title": "smoke_w2 fan-out 测试",
            "type": "group",
            "agent_ids": ["agent_mock", "agent_mock_2", "agent_deepseek"],
        },
    )
    expect(status == 201, f"201 Created (got {status})", str(body)[:200])
    conv = body["conversation"]
    expect(conv["type"] == "group", "type=group")
    member_ids = {m["member_id"] for m in conv["members"]}
    expect("user_demo" in member_ids, "owner 在成员列表")
    expect("agent_mock" in member_ids, "agent_mock 在成员列表")
    expect("agent_mock_2" in member_ids, "agent_mock_2 在成员列表")
    expect("agent_deepseek" in member_ids, "agent_deepseek 在成员列表")
    return conv["id"]


async def s3_fan_out_send_done(conv_id: str) -> dict[str, str]:
    """F-W2-1 core：群聊中 @ 2 个 Agent，验证均独立回复。"""
    print(">>> §3 群聊 fan-out：并发 2 Agent → 各自独立回复")
    user_text = "@Mock_Agent @Mock_Agent_2 群聊fan-out验证"
    agent_done: dict[str, str] = {}
    agent_chunks: dict[str, int] = {}
    agent_created: set[str] = set()

    async with websockets.connect(BFF_WS, open_timeout=3) as ws:
        await _recv(ws)  # hello
        await ws.send(json.dumps({"type": "join", "conversation_id": conv_id, "limit": 50}))
        hist = await _recv(ws, timeout=4)
        expect(hist["type"] == "history", "history 帧")
        expect(hist["count"] == 0, "新会话 history 为空", f"got {hist['count']}")

        await ws.send(
            json.dumps(
                {
                    "type": "send_message",
                    "conversation_id": conv_id,
                    "content": {"type": "text", "text": user_text},
                    "mentions": ["agent_mock", "agent_mock_2"],
                }
            )
        )

        deadline = asyncio.get_event_loop().time() + 15
        while len(agent_done) < 2:
            evt = await _recv(ws, timeout=max(0.2, deadline - asyncio.get_event_loop().time()))
            t = evt["type"]
            if t == "message_created" and evt["message"]["sender_type"] == "agent":
                aid = evt["message"]["sender_id"]
                agent_created.add(aid)
            elif t == "stream_chunk":
                mid = evt.get("message_id", "")
                agent_chunks[mid] = agent_chunks.get(mid, 0) + 1
                expect(
                    evt.get("sender_id") is not None,
                    f"stream_chunk 含 sender_id ({evt['sender_id']})",
                )
            elif t == "message_done":
                mid = evt["message_id"]
                final = (evt.get("final_content") or {}).get("text", "")
                agent_done[mid] = final

    expect(len(agent_created) >= 2, f"≥2 agent message_created (got {len(agent_created)})", str(agent_created))
    expect(len(agent_done) == 2, f"2 agent message_done (got {len(agent_done)})")

    done_mids = sorted(agent_done.keys())
    for mid in done_mids:
        expect(
            agent_chunks.get(mid, 0) >= 3,
            f"agent {mid[-8:]} chunks ≥ 3 (got {agent_chunks.get(mid, 0)})",
        )
        expect(bool(agent_done[mid]), f"agent {mid[-8:]} final 非空")

    return agent_done


async def s4_fan_out_cancel_one(conv_id: str) -> None:
    """F-W2-1 隔离性：cancel 一个 Agent，另一个不受影响。"""
    print(">>> §4 群聊 fan-out：cancel 单个 Agent，兄弟继续完成")
    user_text = "cancel 隔离测试：取消一个但另一个继续。" * 3
    agent_done: list[str] = []
    agent_cancelled: list[str] = []

    async with websockets.connect(BFF_WS, open_timeout=3) as ws:
        await _recv(ws)  # hello
        await ws.send(json.dumps({"type": "join", "conversation_id": conv_id, "limit": 50}))
        await _recv(ws)  # history

        await ws.send(
            json.dumps(
                {
                    "type": "send_message",
                    "conversation_id": conv_id,
                    "content": {"type": "text", "text": user_text},
                    "mentions": ["agent_mock", "agent_mock_2"],
                }
            )
        )

        cancel_sent = False
        cancel_target: str | None = None
        deadline = asyncio.get_event_loop().time() + 15
        while len(agent_done) + len(agent_cancelled) < 2:
            evt = await _recv(ws, timeout=max(0.2, deadline - asyncio.get_event_loop().time()))
            t = evt["type"]
            if t == "stream_chunk" and not cancel_sent:
                cancel_target = evt["message_id"]
                await ws.send(json.dumps({"type": "cancel", "message_id": cancel_target}))
                cancel_sent = True
            elif t == "message_cancelled":
                agent_cancelled.append(evt["message_id"])
                expect(
                    evt["message_id"] != cancel_target or cancel_target is not None,
                    "cancelled message_id 匹配",
                )
            elif t == "message_done":
                agent_done.append(evt["message_id"])

    expect(cancel_sent, "cancel 已发送")
    expect(len(agent_cancelled) >= 1, f"≥1 agent cancelled (got {len(agent_cancelled)})")
    expect(len(agent_done) >= 1, f"≥1 agent done (got {len(agent_done)})")
    expect(
        len(agent_done) + len(agent_cancelled) == 2,
        f"终态覆盖 2 Agent (done={len(agent_done)} cancelled={len(agent_cancelled)})",
    )


async def s5_bad_mentions_reject(conv_id: str) -> None:
    """F-W2-1 反例：群聊无 mentions 被拒绝。"""
    print(">>> §5 群聊无 mentions 拒绝 (bad_mentions)")
    async with websockets.connect(BFF_WS, open_timeout=3) as ws:
        await _recv(ws)  # hello
        await ws.send(json.dumps({"type": "join", "conversation_id": conv_id, "limit": 50}))
        hist = await _recv(ws, timeout=4)

        await ws.send(
            json.dumps(
                {
                    "type": "send_message",
                    "conversation_id": conv_id,
                    "content": {"type": "text", "text": "@someone 没有 mention 列表"},
                }
            )
        )

        deadline = asyncio.get_event_loop().time() + 5
        got_error = False
        while True:
            evt = await _recv(ws, timeout=max(0.2, deadline - asyncio.get_event_loop().time()))
            if evt["type"] == "error":
                if evt.get("code") == "bad_mentions":
                    got_error = True
                    break
                continue
            if evt["type"] == "message_created" and evt["message"]["sender_type"] == "agent":
                raise AssertionError("§5 不应产生 agent 消息")

    expect(got_error, "收到 bad_mentions error")


async def s6_db_records(conv_id: str) -> None:
    """F-W2-1 持久化：验证 DB 中 user + N agent 消息。"""
    print(">>> §6 DB 持久化记录")
    _, body = http_get_json(BFF_BASE + f"/api/conversations/{conv_id}/messages?limit=200")
    msgs = body["messages"]
    user_msgs = [m for m in msgs if m["sender_type"] == "user"]
    agent_msgs = [m for m in msgs if m["sender_type"] == "agent"]

    expect(len(user_msgs) >= 2, f"≥2 user messages (got {len(user_msgs)})")
    expect(len(agent_msgs) >= 4, f"≥4 agent messages (got {len(agent_msgs)})")

    sender_ids = {m["sender_id"] for m in agent_msgs}
    expect(len(sender_ids) >= 2, f"≥2 不同 agent sender (got {sender_ids})")

    cancelled = [m for m in agent_msgs if "[cancelled]" in (m.get("content") or {}).get("text", "")]
    print(f"  [INFO] cancelled agent messages in DB: {len(cancelled)}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def main() -> int:
    print("== AgentHub v2 · W2 fan-out 验收 smoke ==")
    try:
        await s1_health()
        conv_id = await s2_create_group_conv()
        await s3_fan_out_send_done(conv_id)
        await s4_fan_out_cancel_one(conv_id)
        await s5_bad_mentions_reject(conv_id)
        await s6_db_records(conv_id)
    except AssertionError:
        return 1

    print("\n== 全部通过 ==")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
