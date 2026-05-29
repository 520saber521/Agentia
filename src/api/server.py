import argparse
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse


def _ensure_src_on_path() -> None:
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if base not in sys.path:
        sys.path.insert(0, base)


def _read_json_body(handler: BaseHTTPRequestHandler) -> Dict[str, Any]:
    length = int(handler.headers.get("Content-Length", 0))
    if length <= 0:
        return {}
    data = handler.rfile.read(length)
    return json.loads(data.decode("utf-8"))


def _send_json(handler: BaseHTTPRequestHandler, status: int, payload: Dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


_ensure_src_on_path()
from router import Router, RouterConfig  # noqa: E402


# 全局活动状态存储
_agent_activities: Dict[str, Dict[str, Any]] = {}


class RouterHandler(BaseHTTPRequestHandler):
    router: Router

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = _read_json_body(self)
            if parsed.path == "/messages":
                if not payload:
                    _send_json(self, 400, {"error": "message body required"})
                    return
                result = self.router.receive_message(payload)
                _send_json(self, 200, result)
                return
            if parsed.path == "/acks":
                if not payload:
                    _send_json(self, 400, {"error": "ack body required"})
                    return
                result = self.router.receive_ack(payload)
                _send_json(self, 200, result)
                return
            if parsed.path == "/presence/register":
                if not payload:
                    _send_json(self, 400, {"error": "agent required"})
                    return
                agent = payload.get("agent")
                meta = payload.get("meta")
                result = self.router.register_presence(agent, meta=meta)
                _send_json(self, 200, result)
                return
            if parsed.path == "/presence/heartbeat":
                if not payload:
                    _send_json(self, 400, {"error": "agent required"})
                    return
                agent = payload.get("agent")
                result = self.router.heartbeat(agent)
                _send_json(self, 200, result)
                return
            if parsed.path == "/activity":
                if not payload:
                    _send_json(self, 400, {"error": "agent required"})
                    return
                agent = payload.get("agent")
                status = payload.get("status", "")
                task = payload.get("task", "")
                ts = payload.get("ts", int(time.time() * 1000))
                _agent_activities[agent] = {
                    "status": status,
                    "task": task,
                    "ts": ts,
                }
                _send_json(self, 200, {"agent": agent, "status": status, "recorded": True})
                return
        except ValueError as exc:
            _send_json(self, 400, {"error": str(exc)})
            return
        except json.JSONDecodeError:
            _send_json(self, 400, {"error": "invalid json"})
            return
        except Exception:
            _send_json(self, 500, {"error": "internal error"})
            return
        _send_json(self, 404, {"error": "not found"})

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/status":
            include_tasks = query.get("tasks", ["0"])[0] in ("1", "true")
            filter_task = query.get("filter_task", [None])[0]
            result = self.router.status(include_tasks=include_tasks, filter_task=filter_task)
            _send_json(self, 200, result)
            return
        if parsed.path == "/trace":
            task_id = query.get("task", [None])[0]
            message_id = query.get("id", [None])[0]
            try:
                result = self.router.trace(task_id=task_id, message_id=message_id)
                _send_json(self, 200, result)
            except ValueError as exc:
                _send_json(self, 400, {"error": str(exc)})
            return
        if parsed.path == "/inbox":
            agent = query.get("agent", [None])[0]
            if not agent:
                _send_json(self, 400, {"error": "agent required"})
                return
            try:
                limit = int(query.get("limit", ["1"])[0])
            except ValueError:
                _send_json(self, 400, {"error": "limit must be int"})
                return
            messages = self.router.pop_inbox(agent, limit=limit)
            _send_json(self, 200, {"agent": agent, "messages": messages})
            return
        if parsed.path == "/presence":
            agent = query.get("agent", [None])[0]
            try:
                result = self.router.presence_status(agent=agent)
            except ValueError as exc:
                _send_json(self, 400, {"error": str(exc)})
                return
            _send_json(self, 200, result)
            return
        if parsed.path == "/health":
            _send_json(self, 200, {"status": "ok"})
            return
        if parsed.path == "/activity":
            _send_json(self, 200, {"activities": _agent_activities})
            return
        _send_json(self, 404, {"error": "not found"})

    def log_message(self, format: str, *args: Any) -> None:
        return


def serve(workspace_dir: str, host: str = "127.0.0.1", port: int = 8765) -> None:
    router = Router(workspace_dir, config=RouterConfig())
    router.start()
    RouterHandler.router = router
    server = ThreadingHTTPServer((host, port), RouterHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        router.stop(timeout=2)
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Local Router service")
    parser.add_argument("workspace", help="workspace directory")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve(args.workspace, host=args.host, port=args.port)
