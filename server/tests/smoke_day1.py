"""W1 Day1 smoke test —— 直接跑，不依赖 pytest。

用法（BFF 已启动在 :8788 时）::

    server/.venv/Scripts/python.exe server/tests/smoke_day1.py

校验五件事，全部通过即 Day1 契约不退化：

1. ``GET /health`` 返回 200 + ``status=ok``
2. WS 连上后立即收到 ``hello`` 帧（含 ``conn_id`` / ``server``）
3. ``{type:ping}`` → ``pong``
4. ``{type:echo, payload:...}`` → ``echo``，payload 原样回显
5. 非 JSON 文本 → ``error / bad_json``

``send_message`` 的契约自 Day2 起从"占位 not_implemented"切换为"流式应答"，
由 ``smoke_day2.py`` 覆盖。
"""

from __future__ import annotations

import asyncio
import json
import sys
import urllib.request

import websockets


HTTP_HEALTH = "http://127.0.0.1:8788/health"
WS_URL = "ws://127.0.0.1:8788/ws"


def expect(cond: bool, name: str, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ::  {detail}" if detail else ""))
    if not cond:
        raise AssertionError(name)


async def recv_json(ws) -> dict:
    return json.loads(await asyncio.wait_for(ws.recv(), timeout=3))


async def main() -> int:
    print(">>> 1) GET /health")
    with urllib.request.urlopen(HTTP_HEALTH, timeout=3) as r:
        body = json.loads(r.read().decode())
    expect(r.status == 200, "http 200", f"status={r.status}")
    expect(body.get("status") == "ok", "status=ok", f"body={body}")

    print(">>> 2) WS connect & hello frame")
    async with websockets.connect(WS_URL, open_timeout=3) as ws:
        hello = await recv_json(ws)
        expect(hello.get("type") == "hello", "hello frame", str(hello))
        expect(bool(hello.get("conn_id")), "hello.conn_id present")
        expect(str(hello.get("server", "")).startswith("agenthub-bff/"), "hello.server name")

        print(">>> 3) ping / pong")
        await ws.send(json.dumps({"type": "ping"}))
        pong = await recv_json(ws)
        expect(pong.get("type") == "pong", "pong frame", str(pong))

        print(">>> 4) echo payload")
        await ws.send(json.dumps({"type": "echo", "payload": "hello agenthub"}))
        echo = await recv_json(ws)
        expect(echo.get("type") == "echo", "echo.type")
        expect(echo.get("payload") == "hello agenthub", "echo.payload roundtrip", str(echo))
        expect(str(echo.get("message_id", "")).startswith("msg_"), "echo.message_id")

        print(">>> 5) bad_json")
        await ws.send("this is not json")
        err = await recv_json(ws)
        expect(err.get("type") == "error", "error.type")
        expect(err.get("code") == "bad_json", "error.code=bad_json", str(err))

    print("\nAll Day1 smoke checks passed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except AssertionError as e:
        print(f"\nSMOKE FAILED: {e}", file=sys.stderr)
        sys.exit(1)
