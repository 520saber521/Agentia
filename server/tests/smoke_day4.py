"""W1 Day4 smoke —— 前端 Vite dev server + proxy + WS 全链路。

前置条件：

- BFF 已起在 :8788
- ``cd web && npm run dev`` 已起在 :5173

用法::

    server/.venv/Scripts/python.exe server/tests/smoke_day4.py

校验项：

1. ``GET http://localhost:5173/`` 返回 SPA HTML（含 ``<div id="root">``）
2. ``GET http://localhost:5173/api/conversations`` 经 vite proxy 到 BFF，含 ``conv_demo``
3. ``ws://localhost:5173/ws`` 经 vite proxy 升级到 BFF，能收到 ``hello`` 帧
4. 通过 vite proxy 的 WS 完成一次 ``send_message`` → ``message_done`` 全流程
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import urllib.request
from typing import Any

import websockets


VITE_BASE = "http://127.0.0.1:5173"
VITE_WS = "ws://127.0.0.1:5173/ws"
CONV_ID = "conv_demo"


def expect(cond: bool, name: str, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ::  {detail}" if detail else ""))
    if not cond:
        raise AssertionError(name)


async def case_index_html() -> None:
    print(">>> 1) GET / (SPA index.html)")
    req = urllib.request.Request(VITE_BASE + "/", headers={"Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=4) as r:
        body = r.read().decode("utf-8", errors="replace")
        expect(r.status == 200, "200 OK")
    expect('<div id="root">' in body, "html 含 #root", body[:120])
    expect(re.search(r"<script.+/src/main\.tsx", body) is not None, "html 注入 main.tsx", body[:200])


async def case_api_proxy() -> None:
    print(">>> 2) /api/conversations 经 vite proxy")
    with urllib.request.urlopen(VITE_BASE + "/api/conversations", timeout=4) as r:
        body = json.loads(r.read().decode())
        expect(r.status == 200, "200 OK")
    convs = body["conversations"]
    expect(any(c["id"] == CONV_ID for c in convs), f"含 {CONV_ID}", str([c["id"] for c in convs]))


async def case_ws_proxy_hello() -> None:
    print(">>> 3) WS 经 vite proxy 升级 + hello 帧")
    async with websockets.connect(VITE_WS, open_timeout=5) as ws:
        raw = await asyncio.wait_for(ws.recv(), timeout=4)
        hello = json.loads(raw)
        expect(hello["type"] == "hello", "hello frame", str(hello))
        expect(hello["server"].startswith("agenthub-bff/"), "server 头部", hello["server"])


async def case_ws_proxy_send_done() -> None:
    print(">>> 4) WS 经 vite proxy 跑一次 send_message → message_done")
    async with websockets.connect(VITE_WS, open_timeout=5) as ws:
        await asyncio.wait_for(ws.recv(), timeout=3)  # drop hello

        await ws.send(
            json.dumps(
                {
                    "type": "send_message",
                    "conversation_id": CONV_ID,
                    "content": {"type": "text", "text": "smoke_day4 经 proxy 走一遭"},
                }
            )
        )

        chunks = 0
        done_text: str | None = None
        deadline = asyncio.get_event_loop().time() + 10
        while True:
            evt = json.loads(
                await asyncio.wait_for(
                    ws.recv(), timeout=max(0.1, deadline - asyncio.get_event_loop().time())
                )
            )
            if evt["type"] == "stream_chunk":
                chunks += 1
            elif evt["type"] == "message_done":
                done_text = (evt.get("final_content") or {}).get("text") or ""
                break

        expect(chunks >= 5, f"stream_chunk ≥ 5 (got {chunks})")
        expect(bool(done_text) and "smoke_day4" in (done_text or ""), "final_content 回灌输入")


async def main() -> int:
    await case_index_html()
    await case_api_proxy()
    await case_ws_proxy_hello()
    await case_ws_proxy_send_done()
    print("\nAll Day4 smoke checks passed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except AssertionError as e:
        print(f"\nSMOKE FAILED: {e}", file=sys.stderr)
        sys.exit(1)
