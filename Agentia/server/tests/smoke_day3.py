"""W1 Day3 smoke —— REST + WS + DB 端到端校验。

前置条件：

- BFF 已起在 :8788。
- ``server/.agenthub/bff.db`` 最好是干净的（验收脚本会更直观）；
  非空也能跑通，只是计数会差异。

用法::

    server/.venv/Scripts/python.exe server/tests/smoke_day3.py

校验项：

1. ``GET /health`` → ok
2. ``GET /api/conversations`` 至少含 ``conv_demo`` 且成员数 = 2
3. WS ``join conv_demo`` → 收 ``history``
4. ``send_message`` 触发完整流式应答；之后 ``messages`` 表应多两条
5. 第二次 ``send_message`` + 中途 ``cancel`` → ``message_cancelled``，
   会话的 ``last_msg_preview`` 更新为已收到的部分
6. 关闭后重新连一条新 WS，``join`` 应回放之前所有消息
"""

from __future__ import annotations

import asyncio
import json
import sys
import urllib.request
from typing import Any

import websockets


HTTP_BASE = "http://127.0.0.1:8788"
WS_URL = "ws://127.0.0.1:8788/ws"
CONV_ID = "conv_demo"


def expect(cond: bool, name: str, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ::  {detail}" if detail else ""))
    if not cond:
        raise AssertionError(name)


def http_get_json(path: str) -> Any:
    with urllib.request.urlopen(HTTP_BASE + path, timeout=4) as r:
        return r.status, json.loads(r.read().decode())


async def _recv(ws, timeout: float = 4.0) -> dict[str, Any]:
    return json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))


async def case_health() -> None:
    print(">>> 1) /health")
    status, body = http_get_json("/health")
    expect(status == 200 and body["status"] == "ok", "/health ok", str(body))


async def case_rest_seed() -> None:
    print(">>> 2) /api/conversations 含 conv_demo")
    status, body = http_get_json("/api/conversations")
    expect(status == 200, "http 200")
    convs = body["conversations"]
    demo = next((c for c in convs if c["id"] == CONV_ID), None)
    expect(demo is not None, f"含 {CONV_ID}", str([c["id"] for c in convs]))
    expect(demo["type"] == "single", "type=single")
    expect(len(demo["members"]) == 2, f"成员数=2 (got {len(demo['members'])})")


async def case_ws_join_and_send() -> tuple[int, str | None]:
    """返回 (发送后的 stream_chunk 数, 拿到的 agent message_id)。"""
    print(">>> 3) WS join + send_message 流式")
    async with websockets.connect(WS_URL, open_timeout=3) as ws:
        await _recv(ws)  # drop hello

        await ws.send(json.dumps({"type": "join", "conversation_id": CONV_ID, "limit": 50}))
        hist = await _recv(ws, timeout=4)
        expect(hist["type"] == "history" and hist["conversation_id"] == CONV_ID, "history 回放", str(hist)[:160])
        history_count = hist["count"]
        print(f"     history.count = {history_count}")

        user_text = "smoke_day3 第一条消息：写一个 React 登录页"
        await ws.send(
            json.dumps(
                {
                    "type": "send_message",
                    "conversation_id": CONV_ID,
                    "content": {"type": "text", "text": user_text},
                }
            )
        )

        agent_msg_id: str | None = None
        chunk_count = 0
        done_seen = False
        deadline = asyncio.get_event_loop().time() + 10
        while not done_seen:
            evt = await _recv(ws, timeout=max(0.1, deadline - asyncio.get_event_loop().time()))
            if evt["type"] == "message_created" and evt["message"]["sender_type"] == "agent":
                agent_msg_id = evt["message"]["id"]
            elif evt["type"] == "stream_chunk":
                chunk_count += 1
            elif evt["type"] == "message_done":
                done_seen = True
                final = (evt.get("final_content") or {}).get("text") or ""
                expect(user_text in final, "final_content 回灌用户输入")

        expect(agent_msg_id is not None, "拿到 agent message_id")
        expect(chunk_count >= 5, f"stream_chunk 至少 5 条 (got {chunk_count})")
        return chunk_count, agent_msg_id


async def case_db_after_send() -> None:
    print(">>> 4) 写库验证：messages 表 + last_msg_preview")
    _, body = http_get_json(f"/api/conversations/{CONV_ID}/messages?limit=200")
    msgs = body["messages"]
    expect(len(msgs) >= 2, f"消息表至少 2 条 (got {len(msgs)})")

    _, convs_body = http_get_json("/api/conversations")
    demo = next(c for c in convs_body["conversations"] if c["id"] == CONV_ID)
    expect(
        isinstance(demo["last_msg_preview"], str) and len(demo["last_msg_preview"]) > 0,
        "last_msg_preview 非空",
        repr(demo["last_msg_preview"]),
    )


async def case_cancel_persists_partial() -> str | None:
    print(">>> 5) cancel 中途中断 + partial 写库")
    user_text = "请写一段长一点的解说，便于我在中途取消。" * 4
    agent_msg_id: str | None = None
    partial_text: str = ""

    async with websockets.connect(WS_URL, open_timeout=3) as ws:
        await _recv(ws)  # hello
        await ws.send(json.dumps({"type": "join", "conversation_id": CONV_ID}))
        await _recv(ws)  # history

        await ws.send(
            json.dumps(
                {
                    "type": "send_message",
                    "conversation_id": CONV_ID,
                    "content": {"type": "text", "text": user_text},
                }
            )
        )

        cancel_sent = False
        got_chunks = 0
        deadline = asyncio.get_event_loop().time() + 8
        while True:
            evt = await _recv(ws, timeout=max(0.1, deadline - asyncio.get_event_loop().time()))
            if evt["type"] == "message_created" and evt["message"]["sender_type"] == "agent":
                agent_msg_id = evt["message"]["id"]
            elif evt["type"] == "stream_chunk":
                got_chunks += 1
                if not cancel_sent and got_chunks >= 3 and agent_msg_id:
                    await ws.send(json.dumps({"type": "cancel", "message_id": agent_msg_id}))
                    cancel_sent = True
            elif evt["type"] == "message_cancelled":
                partial_text = (evt.get("final_content") or {}).get("text") or ""
                break
            elif evt["type"] == "message_done":
                raise AssertionError("expected message_cancelled, got message_done")

    expect(cancel_sent, "cancel 已发出")
    expect(agent_msg_id is not None, "拿到 agent message_id")
    expect(len(partial_text) > 0, "partial_text 非空")

    # 重新拉 messages，确认该 message_id 的 content.text 就是 partial_text
    _, body = http_get_json(f"/api/conversations/{CONV_ID}/messages?limit=200")
    target = next((m for m in body["messages"] if m["id"] == agent_msg_id), None)
    expect(target is not None, "新 agent 消息已入库", str(agent_msg_id))
    persisted = (target["content"] or {}).get("text") or ""
    expect(persisted == partial_text, "partial 与 DB 内容一致", f"db={persisted!r} ws={partial_text!r}")
    return agent_msg_id


async def case_replay_history() -> None:
    print(">>> 6) 新连接 + join → 历史回放")
    async with websockets.connect(WS_URL, open_timeout=3) as ws:
        await _recv(ws)  # hello
        await ws.send(json.dumps({"type": "join", "conversation_id": CONV_ID, "limit": 200}))
        hist = await _recv(ws, timeout=4)
        expect(hist["type"] == "history", "history 帧")
        expect(hist["count"] >= 4, f"history.count ≥ 4 (got {hist['count']})")


async def main() -> int:
    await case_health()
    await case_rest_seed()
    await case_ws_join_and_send()
    await case_db_after_send()
    await case_cancel_persists_partial()
    await case_replay_history()
    print("\nAll Day3 smoke checks passed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except AssertionError as e:
        print(f"\nSMOKE FAILED: {e}", file=sys.stderr)
        sys.exit(1)
