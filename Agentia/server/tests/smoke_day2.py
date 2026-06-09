"""W1 Day2 smoke —— 端到端校验 send_message 流式 + cancel。

用法（BFF 已启动在 :8788 时）::

    server/.venv/Scripts/python.exe server/tests/smoke_day2.py

要验证三件事：

1. Day1 行为不退化：``ping`` / ``echo`` 仍然有应答。
2. ``send_message`` 应触发完整事件序列
   ``message_created(user)`` → ``message_created(agent)`` →
   ``agent_typing`` → ``stream_chunk * N`` → ``message_done``，
   且 ``final_content.text`` 包含用户输入。
3. ``cancel`` 在流式过程中触发后应收到 ``message_cancelled``，
   后续不再有该 ``message_id`` 的 ``stream_chunk``。
"""

from __future__ import annotations

import asyncio
import json
import sys
import urllib.request
from typing import Any

import websockets


WS_URL = "ws://127.0.0.1:8788/ws"
HTTP_HEALTH = "http://127.0.0.1:8788/health"


def expect(cond: bool, name: str, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ::  {detail}" if detail else ""))
    if not cond:
        raise AssertionError(name)


async def _drain_until(ws, predicate, timeout: float = 5.0) -> list[dict[str, Any]]:
    """收事件直到 ``predicate(evt)`` 命中；返回包括命中事件在内的事件列表。"""
    deadline = asyncio.get_event_loop().time() + timeout
    events: list[dict[str, Any]] = []
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise AssertionError(
                f"timeout after collecting {len(events)} events; last={events[-3:] if events else 'none'}"
            )
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        evt = json.loads(raw)
        events.append(evt)
        if predicate(evt):
            return events


async def case_day1_compat() -> None:
    print(">>> 1) Day1 兼容：ping / echo 仍在")
    async with websockets.connect(WS_URL, open_timeout=3) as ws:
        hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
        expect(hello.get("type") == "hello", "hello frame", str(hello))

        await ws.send(json.dumps({"type": "ping"}))
        pong = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
        expect(pong.get("type") == "pong", "pong")

        await ws.send(json.dumps({"type": "echo", "payload": "hi"}))
        echo = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
        expect(echo.get("type") == "echo" and echo.get("payload") == "hi", "echo roundtrip", str(echo))


async def case_send_message_streaming() -> None:
    print(">>> 2) send_message 完整流式")
    user_text = "用 React 写一个登录页"
    async with websockets.connect(WS_URL, open_timeout=3) as ws:
        json.loads(await asyncio.wait_for(ws.recv(), timeout=3))  # drop hello

        await ws.send(
            json.dumps(
                {
                    "type": "send_message",
                    "conversation_id": "conv_smoke",
                    "content": {"type": "text", "text": user_text},
                }
            )
        )

        events = await _drain_until(ws, lambda e: e.get("type") == "message_done", timeout=10)

        types = [e["type"] for e in events]
        expect(types.count("message_created") == 2, "两个 message_created (user + agent)", str(types))
        expect("agent_typing" in types, "agent_typing 出现")
        chunks = [e for e in events if e["type"] == "stream_chunk"]
        expect(len(chunks) >= 5, f"stream_chunk 至少 5 条 (got {len(chunks)})")
        seqs = [c["seq"] for c in chunks]
        expect(seqs == sorted(seqs) and seqs[0] == 1, "stream_chunk.seq 单调从 1 起", str(seqs[:8]))

        done = events[-1]
        expect(done["type"] == "message_done", "最后一条是 message_done")
        final_text = (done.get("final_content") or {}).get("text") or ""
        expect(user_text in final_text, "final_content 回灌用户输入", final_text[:80])


async def case_cancel_midflight() -> None:
    print(">>> 3) cancel 中断流式")
    user_text = "请写一段长一点的解说，便于我在中途取消。" * 4
    async with websockets.connect(WS_URL, open_timeout=3) as ws:
        json.loads(await asyncio.wait_for(ws.recv(), timeout=3))  # drop hello

        await ws.send(
            json.dumps(
                {
                    "type": "send_message",
                    "conversation_id": "conv_smoke",
                    "content": {"type": "text", "text": user_text},
                }
            )
        )

        agent_msg_id: str | None = None
        received_chunks_before_cancel = 0
        cancel_sent = False
        events: list[dict[str, Any]] = []

        deadline = asyncio.get_event_loop().time() + 8.0
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise AssertionError("timeout waiting for message_cancelled")
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            evt = json.loads(raw)
            events.append(evt)

            if evt["type"] == "message_created" and evt.get("message", {}).get("sender_type") == "agent":
                agent_msg_id = evt["message"]["id"]
            elif evt["type"] == "stream_chunk":
                received_chunks_before_cancel += 1
                # 收到 ≥3 个 chunk 后取消，给"中途取消"留可见痕迹
                if not cancel_sent and agent_msg_id and received_chunks_before_cancel >= 3:
                    await ws.send(json.dumps({"type": "cancel", "message_id": agent_msg_id}))
                    cancel_sent = True
            elif evt["type"] == "message_cancelled":
                break
            elif evt["type"] == "message_done":
                raise AssertionError("expected message_cancelled, got message_done (cancel 来得太晚)")

        expect(cancel_sent, "cancel 已发出")
        expect(agent_msg_id is not None, "拿到 agent message_id")
        cancelled = events[-1]
        expect(cancelled["message_id"] == agent_msg_id, "message_cancelled.message_id 对得上")
        partial = (cancelled.get("final_content") or {}).get("text") or ""
        expect(len(partial) > 0, "cancelled.final_content 非空 (部分内容)")

        # 取消后短暂等待，确认不会再有该 message_id 的 stream_chunk
        try:
            extra = await asyncio.wait_for(ws.recv(), timeout=0.6)
            extra_evt = json.loads(extra)
            if (
                extra_evt.get("type") == "stream_chunk"
                and extra_evt.get("message_id") == agent_msg_id
            ):
                raise AssertionError(f"取消后仍收到 stream_chunk: {extra_evt}")
        except asyncio.TimeoutError:
            pass


async def main() -> int:
    with urllib.request.urlopen(HTTP_HEALTH, timeout=3) as r:
        body = json.loads(r.read().decode())
    expect(r.status == 200 and body.get("status") == "ok", "/health", str(body))

    await case_day1_compat()
    await case_send_message_streaming()
    await case_cancel_midflight()
    print("\nAll Day2 smoke checks passed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except AssertionError as e:
        print(f"\nSMOKE FAILED: {e}", file=sys.stderr)
        sys.exit(1)
