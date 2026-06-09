"""W1 总验收 smoke —— 串联 Day1~Day5 的全部能力。

前置条件
========

- BFF 已起在 :8788 ::

      server/.venv/Scripts/python.exe -m uvicorn server.main:app \\
          --host 127.0.0.1 --port 8788

- （可选）Vite dev 已起在 :5173 ::

      cd web && npm run dev

  若 Vite 未启动，下面的 §6 步会跳过（仅打印 SKIP），不影响整体结果。

用法
====

::

    server/.venv/Scripts/python.exe server/tests/smoke_w1.py

校验矩阵
========

| Section | Feature 对应 SPEC | 校验内容 |
|---|---|---|
| §1 health           | —                | ``GET /health`` |
| §2 REST baseline    | F-W1-1 / F-W1-4  | ``GET /api/conversations`` 与 ``/messages`` |
| §3 create conv      | F-W1-5           | ``POST /api/conversations`` 新建一个 group |
| §4 ws send/done     | F-W1-1 / F-W1-2  | 端到端 send → stream → done |
| §5 ws cancel        | F-W1-2           | cancel 中途保留 partial 内容 |
| §6 vite proxy       | F-W1-3 + 部署    | 经 :5173 走完同样一次 send/done |

失败时返回非 0；任何 ``AssertionError`` 都会指出对应 §与具体期望。
"""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import urllib.error
import urllib.request
from typing import Any

import websockets


BFF_BASE = "http://127.0.0.1:8788"
BFF_WS = "ws://127.0.0.1:8788/ws"
VITE_BASE = "http://127.0.0.1:5173"
VITE_WS = "ws://127.0.0.1:5173/ws"

CONV_ID = "conv_demo"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


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
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=4) as r:
        return r.status, json.loads(r.read().decode())


def port_is_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


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


async def s2_rest_baseline() -> None:
    print(">>> §2 REST baseline (F-W1-1 / F-W1-4)")
    _, convs_body = http_get_json(BFF_BASE + "/api/conversations")
    convs = convs_body["conversations"]
    demo = next((c for c in convs if c["id"] == CONV_ID), None)
    expect(demo is not None, f"seed 含 {CONV_ID}")
    expect(demo["type"] == "single", "demo.type=single")

    _, msgs_body = http_get_json(BFF_BASE + f"/api/conversations/{CONV_ID}/messages?limit=200")
    expect(isinstance(msgs_body["messages"], list), "messages 是 list")
    expect(msgs_body["limit"] == 200, "limit 回显正确")


async def s3_create_conversation() -> str:
    """F-W1-5：POST 新建一个 single 会话，并返回 id。"""
    print(">>> §3 POST /api/conversations (F-W1-5)")
    status, body = http_post_json(
        BFF_BASE + "/api/conversations",
        {"title": "smoke_w1 临时会话", "type": "single", "agent_ids": ["agent_mock"]},
    )
    expect(status == 201, f"201 Created (got {status})")
    conv = body["conversation"]
    expect(conv["type"] == "single", "type=single")
    member_ids = {m["member_id"] for m in conv["members"]}
    expect("user_demo" in member_ids and "agent_mock" in member_ids, "members 含 owner+agent", str(member_ids))

    # 校验失败也应该被拦下来
    try:
        http_post_json(BFF_BASE + "/api/conversations", {"title": ""})
    except urllib.error.HTTPError as e:
        expect(e.code == 422, f"空 title 应 422 (got {e.code})")
    else:
        raise AssertionError("空 title 应该返回 4xx 但没有")

    return conv["id"]


async def s4_ws_send_done(new_conv_id: str) -> None:
    """F-W1-1 + F-W1-2：在【新建会话】里跑一次完整 send → done。"""
    print(">>> §4 WS send_message → message_done (F-W1-1 / F-W1-2)")
    async with websockets.connect(BFF_WS, open_timeout=3) as ws:
        await _recv(ws)  # hello
        await ws.send(json.dumps({"type": "join", "conversation_id": new_conv_id, "limit": 50}))
        hist = await _recv(ws, timeout=4)
        expect(hist["type"] == "history" and hist["conversation_id"] == new_conv_id, "history 帧")
        expect(hist["count"] == 0, "新会话 history 应为空", f"got {hist['count']}")

        user_text = "smoke_w1 §4 端到端验证"
        await ws.send(
            json.dumps(
                {
                    "type": "send_message",
                    "conversation_id": new_conv_id,
                    "content": {"type": "text", "text": user_text},
                }
            )
        )

        chunks = 0
        agent_msg_id: str | None = None
        final_text: str | None = None
        deadline = asyncio.get_event_loop().time() + 10
        while True:
            evt = await _recv(ws, timeout=max(0.1, deadline - asyncio.get_event_loop().time()))
            if evt["type"] == "message_created" and evt["message"]["sender_type"] == "agent":
                agent_msg_id = evt["message"]["id"]
            elif evt["type"] == "stream_chunk":
                chunks += 1
            elif evt["type"] == "message_done":
                final_text = (evt.get("final_content") or {}).get("text")
                break

        expect(agent_msg_id is not None, "拿到 agent message_id")
        expect(chunks >= 5, f"stream_chunk ≥ 5 (got {chunks})")
        expect(bool(final_text) and user_text in (final_text or ""), "final 含用户输入")

    # done 之后 DB 应该已有用户 + agent 2 条
    _, body = http_get_json(BFF_BASE + f"/api/conversations/{new_conv_id}/messages?limit=200")
    expect(len(body["messages"]) >= 2, f"新会话已写入 ≥ 2 条 (got {len(body['messages'])})")


async def s5_ws_cancel(new_conv_id: str) -> None:
    """F-W1-2：cancel 必须保留 partial 文本到 DB。"""
    print(">>> §5 WS cancel keeps partial (F-W1-2)")
    user_text = "请写一段长的内容，便于我在中途取消。" * 4
    agent_msg_id: str | None = None
    partial_text = ""

    async with websockets.connect(BFF_WS, open_timeout=3) as ws:
        await _recv(ws)  # hello
        await ws.send(json.dumps({"type": "join", "conversation_id": new_conv_id, "limit": 50}))
        await _recv(ws)  # history

        await ws.send(
            json.dumps(
                {
                    "type": "send_message",
                    "conversation_id": new_conv_id,
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
                raise AssertionError("§5 expected message_cancelled, got message_done")

    expect(cancel_sent, "cancel 已发出")
    expect(len(partial_text) > 0, "partial_text 非空")

    _, body = http_get_json(BFF_BASE + f"/api/conversations/{new_conv_id}/messages?limit=200")
    target = next((m for m in body["messages"] if m["id"] == agent_msg_id), None)
    expect(target is not None, "cancelled 消息已入库")
    persisted = (target["content"] or {}).get("text") or ""
    expect(persisted == partial_text, "DB partial 与 WS 一致", f"db={persisted!r} ws={partial_text!r}")


async def s6_vite_proxy(new_conv_id: str) -> None:
    """F-W1-3 + 部署：Vite proxy 跑一次同样的 send/done。Vite 未启动则 SKIP。"""
    print(">>> §6 Vite proxy end-to-end (optional)")
    if not port_is_open("127.0.0.1", 5173):
        print("  [SKIP] :5173 未启动，跳过 vite proxy 校验")
        return

    # 6a) SPA index
    with urllib.request.urlopen(VITE_BASE + "/", timeout=4) as r:
        html = r.read().decode("utf-8", errors="replace")
    expect("<div id=\"root\">" in html, "spa index 含 #root")

    # 6b) WS via proxy 跑一次 send_message
    async with websockets.connect(VITE_WS, open_timeout=5) as ws:
        await _recv(ws)  # hello
        await ws.send(json.dumps({"type": "join", "conversation_id": new_conv_id, "limit": 50}))
        await _recv(ws)  # history

        await ws.send(
            json.dumps(
                {
                    "type": "send_message",
                    "conversation_id": new_conv_id,
                    "content": {"type": "text", "text": "smoke_w1 §6 经 vite proxy"},
                }
            )
        )

        chunks = 0
        done_text: str | None = None
        deadline = asyncio.get_event_loop().time() + 10
        while True:
            evt = await _recv(ws, timeout=max(0.1, deadline - asyncio.get_event_loop().time()))
            if evt["type"] == "stream_chunk":
                chunks += 1
            elif evt["type"] == "message_done":
                done_text = (evt.get("final_content") or {}).get("text")
                break

        expect(chunks >= 5, f"proxy stream_chunk ≥ 5 (got {chunks})")
        expect(bool(done_text) and "§6" in (done_text or ""), "proxy final 含用户输入")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def main() -> int:
    print("== AgentHub v2 · W1 总验收 smoke ==")
    await s1_health()
    await s2_rest_baseline()
    new_conv_id = await s3_create_conversation()
    await s4_ws_send_done(new_conv_id)
    await s5_ws_cancel(new_conv_id)
    await s6_vite_proxy(new_conv_id)
    print("\nAll W1 smoke checks passed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except AssertionError as e:
        print(f"\nSMOKE FAILED: {e}", file=sys.stderr)
        sys.exit(1)
