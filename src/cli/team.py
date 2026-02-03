import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def _ensure_src_on_path() -> None:
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if base not in sys.path:
        sys.path.insert(0, base)


_ensure_src_on_path()

from api.client import RouterClient  # noqa: E402
from protocol import builders  # noqa: E402
from validation.validator import ValidationError, validate_message  # noqa: E402

from cli.config import load_config, resolve_router_url, resolve_workspace  # noqa: E402
from launcher import launch as launch_windows  # noqa: E402
from scheduler import (  # noqa: E402
    TaskScheduler,
    ResultAggregator,
    judge_complexity,
    SPECIALIZED_AGENTS,
)
from scheduler.complexity import TaskInput  # noqa: E402
from scheduler.design import (  # noqa: E402
    analyze_and_design,
    print_design_for_review,
    DesignStatus,
    ProjectType,
)
from scheduler.analyzer import (  # noqa: E402
    analyze_project,
    analyze_impact,
    format_project_analysis,
    format_impact_analysis,
)
from scheduler.collaboration import (  # noqa: E402
    create_collaboration_hub,
    CollaborationHub,
)

# 全局协作中心（在启动时初始化）
_collaboration_hub: Optional[CollaborationHub] = None


def _get_collaboration_hub(client=None) -> CollaborationHub:
    """获取或创建协作中心"""
    global _collaboration_hub
    if _collaboration_hub is None:
        send_fn = client.send_message if client else None
        _collaboration_hub = create_collaboration_hub(send_fn)
    return _collaboration_hub


def _now_ms() -> int:
    return int(time.time() * 1000)


def _now_s() -> int:
    return int(time.time())


def _parse_csv(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_json_body(value: Optional[str], name: str) -> Dict[str, Any]:
    if not value:
        raise ValueError(f"{name} requires --body JSON")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON for {name} body: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{name} body must be a JSON object")
    return parsed


def _parse_deadline(value: Optional[str], now_ms: int) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        raw = value
    else:
        text = str(value).strip()
        if not text.isdigit():
            raise ValueError("deadline must be an integer timestamp or seconds")
        raw = int(text)
    if raw < 0:
        raise ValueError("deadline must be positive")

    # Heuristic:
    # - small values (< 1e8) are relative seconds
    # - 10-digit values are absolute seconds
    # - 13-digit values are absolute milliseconds
    if raw < 100000000:
        return now_ms + raw * 1000
    if raw < 100000000000:
        return raw * 1000
    return raw


def _normalize_role(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return str(value).strip()


def _resolve_agent_instance(from_role: str, agent_instance: Optional[str]) -> str:
    if agent_instance:
        return agent_instance
    env_instance = os.environ.get("TEAM_AGENT_ID")
    if env_instance:
        return env_instance
    return f"{from_role}-cli"


def _resolve_from_role(value: Optional[str]) -> str:
    role = value or os.environ.get("TEAM_ROLE")
    if not role:
        raise ValueError("--from or TEAM_ROLE is required")
    return role


def _parse_wait(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    if value not in ("delivered", "accepted", "done"):
        raise ValueError("--wait must be delivered, accepted, or done")
    return value


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _pending_path(agent_id: str) -> str:
    base = os.path.join(os.path.expanduser("~"), ".codex_team")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, f"pending-{agent_id}.json")


def _load_pending(agent_id: str) -> Dict[str, Any]:
    path = _pending_path(agent_id)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _save_pending(agent_id: str, pending: Dict[str, Any]) -> None:
    path = _pending_path(agent_id)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(pending, handle, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def _should_track_pending(message: Dict[str, Any]) -> bool:
    return message.get("type") == "ask"


def _pending_entry(message: Dict[str, Any], now_ms: int) -> Dict[str, Any]:
    raw_ts = message.get("ts")
    ts_value = now_ms
    if isinstance(raw_ts, (int, float)):
        ts_value = int(raw_ts)
    elif isinstance(raw_ts, str) and raw_ts.isdigit():
        ts_value = int(raw_ts)
    return {
        "id": message.get("id"),
        "from": message.get("from"),
        "task_id": message.get("task_id"),
        "action": message.get("action"),
        "type": message.get("type"),
        "summary": _summarize_body(message),
        "ts": ts_value,
        "last_remind": 0,
        "remind_count": 0,
    }


def _mark_pending_resolved(agent_id: str, corr_id: Optional[str]) -> None:
    if not agent_id or not corr_id:
        return
    pending = _load_pending(agent_id)
    if corr_id in pending:
        pending.pop(corr_id, None)
        _save_pending(agent_id, pending)

def _post_json(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def _wait_for_ack(client: RouterClient, message_id: str, stage: str, timeout_s: int, poll_s: float) -> Dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        trace = client.trace(message_id=message_id)
        for ack in trace.get("acks", []):
            if ack.get("ack") == stage:
                return {"status": "ok", "ack": ack}
        time.sleep(poll_s)
    return {"status": "timeout", "ack_stage": stage, "id": message_id}


def _wait_for_done(client: RouterClient, task_id: str, timeout_s: int, poll_s: float) -> Dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        trace = client.trace(task_id=task_id)
        for message in trace.get("messages", []):
            if message.get("type") in ("done", "fail"):
                return {"status": "ok", "message": message}
        time.sleep(poll_s)
    return {"status": "timeout", "task_id": task_id}


def _validate_or_raise(message: Dict[str, Any]) -> None:
    errors = validate_message(message, allow_missing_generated=True)
    if errors:
        raise ValidationError(errors)


def _router_health(base_url: str) -> bool:
    try:
        request = Request(f"{base_url}/health", method="GET")
        with urlopen(request) as response:
            return response.status == 200
    except (HTTPError, URLError):
        return False


def _start_router(workspace: str, host: str, port: int, log_path: Optional[str]) -> subprocess.Popen:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    server_path = os.path.join(root, "src", "api", "server.py")
    cmd = [sys.executable, server_path, workspace, "--host", host, "--port", str(port)]

    stdout = None
    stderr = None
    if log_path:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        handle = open(log_path, "a", encoding="utf-8")
        stdout = handle
        stderr = handle

    return subprocess.Popen(cmd, stdout=stdout, stderr=stderr, start_new_session=True)


def _wait_for_router(base_url: str, timeout_s: int) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _router_health(base_url):
            return
        time.sleep(0.2)
    raise RuntimeError("router not ready")


def _presence_register(client: RouterClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    agent = payload.get("agent")
    if not agent:
        raise ValueError("presence payload missing agent")
    return client.register_presence(agent, meta=payload.get("meta"))


def _build_presence_payload(
    role: str, agent_instance: str, session: str, epoch: int, window_name: str
) -> Dict[str, Any]:
    return {
        "agent": agent_instance,
        "meta": {
            "role": role,
            "session": session,
            "epoch": epoch,
            "window_name": window_name,
            "ts": _now_ms(),
        },
    }


def _create_window_name(format_str: str, session: str, role: str, agent_instance: str) -> str:
    name = format_str.replace("<session>", session)
    name = name.replace("<role>", role)
    name = name.replace("<agent>", agent_instance)
    return name


def _prepare_message_context(client: RouterClient, from_role: str, agent_instance: str) -> Dict[str, Any]:
    status = client.status()
    return {
        "session": status.get("session"),
        "epoch": status.get("epoch"),
        "agent_instance": agent_instance,
        "from_role": from_role,
    }


def _auto_task_id(prefix: str, from_role: str) -> str:
    ts = time.strftime("%Y%m%d-%H%M%S")
    return f"{prefix}-{from_role}-{ts}"


def _extract_task_id_from_trace(trace: Dict[str, Any]) -> Optional[str]:
    message = trace.get("message")
    if isinstance(message, dict):
        return message.get("task_id")
    return None


def _format_message_line(message: Dict[str, Any]) -> str:
    msg_id = message.get("id", "-")
    msg_type = message.get("type", "-")
    action = message.get("action", "-")
    task_id = message.get("task_id", "-")
    from_role = message.get("from", "-")

    body = message.get("body")
    body_data = None
    if isinstance(body, str) and body:
        try:
            body_data = json.loads(body)
        except json.JSONDecodeError:
            body_data = None

    if action == "clarify" and isinstance(body_data, dict):
        question = body_data.get("question", "-")
        doc_path = body_data.get("doc_path", "-")
        code_path = body_data.get("code_path", "-")
        return f"窗口:{from_role} | 问题:{question} | 文档路径:{doc_path} | 代码路径:{code_path} | id:{msg_id}"

    if action == "review_feedback" and isinstance(body_data, dict):
        summary = body_data.get("summary") or body_data.get("issue_count", "-")
        doc_path = body_data.get("doc_path", "-")
        return f"窗口:{from_role} | 反馈:{summary} | 文档路径:{doc_path} | 任务:{task_id} | id:{msg_id}"

    return f"窗口:{from_role} | 类型:{msg_type}/{action} | 任务:{task_id} | id:{msg_id}"


def _notify(title: str, text: str) -> None:
    if sys.platform != "darwin":
        return
    safe_title = title.replace('"', "'")
    safe_text = text.replace('"', "'")
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification "{safe_text}" with title "{safe_title}"'],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return


def _autotype_terminal(window_name: str, text: str) -> bool:
    if sys.platform != "darwin":
        return False
    script = r'''
on run argv
  set targetName to item 1 of argv
  set msg to item 2 of argv
  tell application "Terminal"
    repeat with w in windows
      try
        if (name of w) contains targetName then
          set index of w to 1
          delay 0.1
          tell application "System Events"
            tell process "Terminal"
              keystroke msg
              key code 36
            end tell
          end tell
          return "true"
        end if
      end try
    end repeat
  end tell
  return "false"
end run
'''
    try:
        result = subprocess.run(
            ["osascript", "-e", script, window_name, text],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return False
    return "true" in (result.stdout or "").lower()


def _autotype_iterm2(window_name: str, text: str) -> bool:
    if sys.platform != "darwin":
        return False
    script = r'''
on run argv
  set targetName to item 1 of argv
  set msg to item 2 of argv
  tell application "iTerm2"
    repeat with w in windows
      repeat with s in sessions of w
        try
          if (name of s) contains targetName then
            tell s to write text msg
            return "true"
          end if
        end try
      end repeat
    end repeat
  end tell
  return "false"
end run
'''
    try:
        result = subprocess.run(
            ["osascript", "-e", script, window_name, text],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return False
    return "true" in (result.stdout or "").lower()


def _autotype_to_window(window_name: str, text: str) -> bool:
    if not window_name:
        return False
    if _autotype_terminal(window_name, text):
        return True
    return _autotype_iterm2(window_name, text)


def _default_agent_prompt(role: str, message: Dict[str, Any]) -> str:
    return (
        f"You are Agent {role} in a Codex team.\n"
        "Reply in plain text. Be concise, specific, and helpful.\n"
        "If asked to review, summarize issues or say no issues.\n"
        "If asked to implement, outline steps or ask clarifying questions.\n"
        "Incoming message JSON:\n"
        f"{json.dumps(message, ensure_ascii=False)}\n"
    )


def _flatten_prompt(text: str) -> str:
    return " ".join(text.splitlines()).strip()


def _summarize_body(message: Dict[str, Any], limit: int = 400) -> str:
    body = message.get("body")
    if body is None:
        summary = ""
    elif isinstance(body, str):
        summary = body
    else:
        summary = json.dumps(body, ensure_ascii=False)
    summary = _flatten_prompt(str(summary))
    if len(summary) > limit:
        summary = summary[:limit] + "...(+truncated)"
    return summary


def _auto_input_prompt(role: str, message: Dict[str, Any]) -> str:
    from_role = message.get("from", "MAIN")
    msg_type = message.get("type", "")
    action = message.get("action", "")
    corr_id = message.get("id", "")
    task_id = message.get("task_id") or "TASK_ID"
    body_summary = _summarize_body(message)

    base = (
        f"[TEAM] from={from_role} to={role} type={msg_type} action={action} "
        f"corr={corr_id} task={task_id} body={body_summary}. "
    )
    if action == "review":
        reply_hint = (
            "Review then reply to MAIN via CLI. Example: "
            f"python3 src/cli/team.py report --from {role} --to MAIN "
            f"--task {task_id} --corr {corr_id} "
            "--body \"<json with doc_path/has_issues/issue_count>\" "
            "or team done for no-issue."
        )
    elif action == "assign":
        reply_hint = (
            "Execute then reply via CLI. Example: "
            f"python3 src/cli/team.py done --from {role} --to MAIN "
            f"--task {task_id} --corr {corr_id} --body \"<json with status>\"."
        )
    else:
        reply_hint = (
            "Reply to MAIN via CLI. Example: "
            f"python3 src/cli/team.py reply --from {role} --to MAIN "
            f"--corr {corr_id} --task {task_id} --text \"...\"."
        )
    return base + reply_hint


def _reminder_prompt(role: str, entry: Dict[str, Any]) -> str:
    from_role = entry.get("from", "MAIN")
    msg_type = entry.get("type", "")
    action = entry.get("action", "")
    corr_id = entry.get("id", "")
    task_id = entry.get("task_id") or "TASK_ID"
    summary = entry.get("summary") or ""
    return (
        f"[REMIND] Pending from={from_role} to={role} type={msg_type} action={action} "
        f"corr={corr_id} task={task_id} summary={summary}. "
        "Please respond via CLI if not handled."
    )


def _run_codex_exec(codex_cmd: str, prompt: str) -> str:
    cmd = [codex_cmd, "exec", "--dangerously-bypass-approvals-and-sandbox", prompt]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return ""
    output = (result.stdout or "").strip()
    if output:
        return output
    return (result.stderr or "").strip()


def _send_and_wait(client: RouterClient, message: Dict[str, Any], wait: Optional[str], timeout_s: int, poll_s: float) -> Dict[str, Any]:
    response = client.send_message(message)
    if not wait or wait == "delivered":
        return response
    message_id = response.get("id")
    if not message_id:
        return response
    if wait == "accepted":
        return _wait_for_ack(client, message_id, "accepted", timeout_s, poll_s)
    if wait == "done":
        task_id = message.get("task_id")
        if not task_id:
            return {"status": "error", "error": "task_id required for --wait done"}
        return _wait_for_done(client, task_id, timeout_s, poll_s)
    return response


def handle_start(args: argparse.Namespace) -> None:
    config = load_config(args.config, args.workspace)
    workspace = resolve_workspace(config, args.workspace)
    router_url = resolve_router_url(config, args.router_url, args.router_host, args.router_port)
    parsed = urlparse(router_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8765

    if not _router_health(router_url):
        log_path = args.router_log
        _start_router(workspace, host, port, log_path)
        _wait_for_router(router_url, args.router_wait)

    client = RouterClient(router_url)
    status = client.status()
    session = status.get("session")
    epoch = status.get("epoch")

    roles = _parse_csv(args.roles) or config.get("roles")
    if not roles:
        roles = ["MAIN", "A", "B", "C", "D"]

    codex_path = args.codex_path or config.get("codex_path", "codex")
    window_format = args.window_name_format or config.get("window_name_format")
    if not window_format:
        window_format = "team-<session>-<role>"

    adapter = args.terminal_adapter or config.get("terminal_adapter", "terminal")

    windows = []
    for role in roles:
        agent_instance = f"{role}-{os.urandom(3).hex()}"
        window_name = _create_window_name(window_format, session, role, agent_instance)
        windows.append(
            {
                "role": role,
                "agent_instance": agent_instance,
                "window_name": window_name,
            }
        )

    launch_windows(
        adapter=adapter,
        workspace=workspace,
        session=session,
        epoch=epoch,
        codex_path=codex_path,
        windows=windows,
    )

    if not args.no_presence:
        for window in windows:
            payload = _build_presence_payload(
                window["role"],
                window["agent_instance"],
                session,
                epoch,
                window["window_name"],
            )
            try:
                result = _presence_register(client, payload)
            except HTTPError as exc:
                result = {"status": "error", "error": f"{exc.code} {exc.reason}"}
            except URLError as exc:
                result = {"status": "error", "error": str(exc)}
            _print_json({"presence": payload, "result": result})


def handle_review(args: argparse.Namespace) -> None:
    from_role = _resolve_from_role(args.from_role)
    agent_instance = _resolve_agent_instance(from_role, args.agent_instance)
    client = RouterClient(args.router_url)
    context = _prepare_message_context(client, from_role, agent_instance)

    doc_path = args.file
    if not doc_path:
        raise ValueError("review requires --file")

    review_deadline = _parse_deadline(args.review_deadline or args.deadline, _now_ms())
    if review_deadline is None:
        default_seconds = args.default_review_deadline_s
        review_deadline = _now_ms() + default_seconds * 1000

    message = builders.build_review(
        session=context["session"],
        epoch=context["epoch"],
        agent_instance=context["agent_instance"],
        from_role=context["from_role"],
        to=args.to,
        task_id=args.task,
        owner=args.owner or from_role,
        doc_path=doc_path,
        focus=_parse_csv(args.focus),
        review_deadline=review_deadline,
        reviewers=None,
    )
    _validate_or_raise(message)

    wait = _parse_wait(args.wait)
    result = _send_and_wait(client, message, wait, args.wait_timeout, args.wait_poll)
    _print_json(result)


def handle_assign(args: argparse.Namespace) -> None:
    from_role = _resolve_from_role(args.from_role)
    agent_instance = _resolve_agent_instance(from_role, args.agent_instance)
    client = RouterClient(args.router_url)
    context = _prepare_message_context(client, from_role, agent_instance)

    deadline = _parse_deadline(args.deadline, _now_ms())
    if deadline is None:
        raise ValueError("assign requires --deadline")

    files = _parse_csv(args.files)
    if not files:
        raise ValueError("assign requires --files")

    success_criteria = _parse_csv(args.success_criteria)
    if not success_criteria:
        raise ValueError("assign requires --success-criteria")

    message = builders.build_assign(
        session=context["session"],
        epoch=context["epoch"],
        agent_instance=context["agent_instance"],
        from_role=context["from_role"],
        to=args.to,
        task_id=args.task,
        owner=args.owner or from_role,
        deadline=deadline,
        task_type=args.action or "implement",
        files=files,
        success_criteria=success_criteria,
        dependencies=_parse_csv(args.dependencies),
    )
    _validate_or_raise(message)

    wait = _parse_wait(args.wait)
    result = _send_and_wait(client, message, wait, args.wait_timeout, args.wait_poll)
    _print_json(result)


def handle_ask(args: argparse.Namespace) -> None:
    from_role = _resolve_from_role(args.from_role)
    agent_instance = _resolve_agent_instance(from_role, args.agent_instance)
    client = RouterClient(args.router_url)
    context = _prepare_message_context(client, from_role, agent_instance)

    action = args.action
    if action not in ("clarify", "verify"):
        raise ValueError("ask requires --action clarify or verify")

    body: Dict[str, Any]
    if action == "clarify":
        if not args.code_path or not args.question or not args.context:
            raise ValueError("clarify requires --code-path, --question, and --context")
        body = {
            "code_path": args.code_path,
            "question": args.question,
            "context": args.context,
        }
        if args.expected:
            body["expected"] = args.expected
        if args.doc_path:
            body["doc_path"] = args.doc_path
    else:
        if not args.doc_path or not args.changes_summary or not args.question:
            raise ValueError("verify requires --doc-path, --changes-summary, and --question")
        body = {
            "doc_path": args.doc_path,
            "changes_summary": args.changes_summary,
            "question": args.question,
        }

    message = builders.build_ask(
        session=context["session"],
        epoch=context["epoch"],
        agent_instance=context["agent_instance"],
        from_role=context["from_role"],
        to=args.to,
        action=action,
        task_id=args.task,
        owner=args.owner or from_role,
        body=body,
    )
    _validate_or_raise(message)

    wait = _parse_wait(args.wait)
    result = _send_and_wait(client, message, wait, args.wait_timeout, args.wait_poll)
    _print_json(result)


def handle_send(args: argparse.Namespace) -> None:
    from_role = _resolve_from_role(args.from_role)
    agent_instance = _resolve_agent_instance(from_role, args.agent_instance)
    client = RouterClient(args.router_url)
    context = _prepare_message_context(client, from_role, agent_instance)

    if not args.corr:
        raise ValueError("send requires --corr")

    body = _parse_json_body(args.body, "send")

    message = builders.build_send(
        session=context["session"],
        epoch=context["epoch"],
        agent_instance=context["agent_instance"],
        from_role=context["from_role"],
        to=args.to,
        task_id=args.task,
        corr=args.corr,
        body=body,
        action="answer",
        owner=args.owner,
    )
    _validate_or_raise(message)

    wait = _parse_wait(args.wait)
    result = _send_and_wait(client, message, wait, args.wait_timeout, args.wait_poll)
    _mark_pending_resolved(context["agent_instance"], args.corr)
    _print_json(result)


def handle_done(args: argparse.Namespace) -> None:
    from_role = _resolve_from_role(args.from_role)
    agent_instance = _resolve_agent_instance(from_role, args.agent_instance)
    client = RouterClient(args.router_url)
    context = _prepare_message_context(client, from_role, agent_instance)

    if not args.corr:
        raise ValueError("done requires --corr")

    if args.body:
        body = _parse_json_body(args.body, "done")
    elif args.action == "verified":
        body = {"has_new_issues": False}
    else:
        body = {"status": "done"}

    message = builders.build_done(
        session=context["session"],
        epoch=context["epoch"],
        agent_instance=context["agent_instance"],
        from_role=context["from_role"],
        to=args.to,
        task_id=args.task,
        corr=args.corr,
        body=body,
        action=args.action,
    )
    _validate_or_raise(message)

    wait = _parse_wait(args.wait)
    result = _send_and_wait(client, message, wait, args.wait_timeout, args.wait_poll)
    _mark_pending_resolved(context["agent_instance"], args.corr)
    _print_json(result)


def handle_fail(args: argparse.Namespace) -> None:
    from_role = _resolve_from_role(args.from_role)
    agent_instance = _resolve_agent_instance(from_role, args.agent_instance)
    client = RouterClient(args.router_url)
    context = _prepare_message_context(client, from_role, agent_instance)

    if not args.corr:
        raise ValueError("fail requires --corr")

    message = builders.build_fail(
        session=context["session"],
        epoch=context["epoch"],
        agent_instance=context["agent_instance"],
        from_role=context["from_role"],
        to=args.to,
        task_id=args.task,
        corr=args.corr,
        reason=args.reason,
        blocked_by=_parse_csv(args.blocked_by),
    )
    _validate_or_raise(message)

    wait = _parse_wait(args.wait)
    result = _send_and_wait(client, message, wait, args.wait_timeout, args.wait_poll)
    _mark_pending_resolved(context["agent_instance"], args.corr)
    _print_json(result)


def handle_report(args: argparse.Namespace) -> None:
    from_role = _resolve_from_role(args.from_role)
    agent_instance = _resolve_agent_instance(from_role, args.agent_instance)
    client = RouterClient(args.router_url)
    context = _prepare_message_context(client, from_role, agent_instance)

    if not args.corr:
        raise ValueError("report requires --corr")

    body = _parse_json_body(args.body, "report")

    message = builders.build_message(
        session=context["session"],
        epoch=context["epoch"],
        agent_instance=context["agent_instance"],
        from_role=context["from_role"],
        to=args.to,
        msg_type="report",
        action="review_feedback",
        task_id=args.task,
        owner=args.owner,
        corr=args.corr,
        body=body,
    )
    _validate_or_raise(message)

    wait = _parse_wait(args.wait)
    result = _send_and_wait(client, message, wait, args.wait_timeout, args.wait_poll)
    _mark_pending_resolved(context["agent_instance"], args.corr)
    _print_json(result)


def handle_status(args: argparse.Namespace) -> None:
    client = RouterClient(args.router_url)
    result = client.status(include_tasks=args.tasks, filter_task=args.filter_task)
    _print_json(result)


def handle_trace(args: argparse.Namespace) -> None:
    client = RouterClient(args.router_url)
    result = client.trace(task_id=args.task, message_id=args.id)
    _print_json(result)


def handle_inbox(args: argparse.Namespace) -> None:
    client = RouterClient(args.router_url)
    agent = args.agent or os.environ.get("TEAM_AGENT_ID")
    if not agent:
        raise ValueError("--agent or TEAM_AGENT_ID is required")

    def pull_once() -> None:
        result = client.inbox(agent, limit=args.limit)
        messages = result.get("messages", [])
        if args.ack and messages:
            for message in messages:
                message_id = message.get("id")
                if not message_id:
                    continue
                client.send_ack({"ack_stage": "accepted", "corr": message_id, "agent": agent})
        _print_json(result)

    if not args.follow:
        pull_once()
        return

    try:
        while True:
            pull_once()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return


def handle_say(args: argparse.Namespace) -> None:
    from_role = _resolve_from_role(args.from_role)
    agent_instance = _resolve_agent_instance(from_role, args.agent_instance)
    client = RouterClient(args.router_url)
    context = _prepare_message_context(client, from_role, agent_instance)

    task_id = args.task or _auto_task_id("CHAT", from_role)
    owner = args.owner or from_role
    code_path = args.code_path or "n/a"
    context_text = args.context or "general"

    body = {
        "code_path": code_path,
        "question": args.text,
        "context": context_text,
    }
    if args.doc_path:
        body["doc_path"] = args.doc_path
    if args.expected:
        body["expected"] = args.expected

    message = builders.build_ask(
        session=context["session"],
        epoch=context["epoch"],
        agent_instance=context["agent_instance"],
        from_role=context["from_role"],
        to=args.to,
        action="clarify",
        task_id=task_id,
        owner=owner,
        body=body,
    )
    _validate_or_raise(message)

    wait = _parse_wait(args.wait)
    result = _send_and_wait(client, message, wait, args.wait_timeout, args.wait_poll)
    _print_json(result)


def handle_reply(args: argparse.Namespace) -> None:
    from_role = _resolve_from_role(args.from_role)
    agent_instance = _resolve_agent_instance(from_role, args.agent_instance)
    client = RouterClient(args.router_url)
    context = _prepare_message_context(client, from_role, agent_instance)

    task_id = args.task
    if not task_id:
        trace = client.trace(message_id=args.corr)
        task_id = _extract_task_id_from_trace(trace)
    if not task_id:
        raise ValueError("--task required when corr has no task_id")

    body: Dict[str, Any] = {"message": args.text}
    if args.doc_path:
        body["doc_path"] = args.doc_path
    if args.code_path:
        body["code_path"] = args.code_path
    if args.doc_updated:
        body["doc_updated"] = True

    message = builders.build_send(
        session=context["session"],
        epoch=context["epoch"],
        agent_instance=context["agent_instance"],
        from_role=context["from_role"],
        to=args.to,
        task_id=task_id,
        corr=args.corr,
        body=body,
        action="answer",
        owner=args.owner,
    )
    _validate_or_raise(message)

    wait = _parse_wait(args.wait)
    result = _send_and_wait(client, message, wait, args.wait_timeout, args.wait_poll)
    _mark_pending_resolved(context["agent_instance"], args.corr)
    _print_json(result)


def handle_listen(args: argparse.Namespace) -> None:
    client = RouterClient(args.router_url)
    agent = args.agent or os.environ.get("TEAM_AGENT_ID")
    if not agent:
        raise ValueError("--agent or TEAM_AGENT_ID is required")
    role = args.role or os.environ.get("TEAM_ROLE") or "AGENT"
    context = _prepare_message_context(client, role, agent)
    codex_cmd = args.codex_cmd or os.environ.get("CODEX_TEAM_CODEX_PATH") or "codex"
    window_name = args.window_name or os.environ.get("TEAM_WINDOW_NAME") or ""
    prompt_template = None
    if args.prompt_path:
        with open(os.path.abspath(args.prompt_path), "r", encoding="utf-8") as handle:
            prompt_template = handle.read()

    log_handle = None
    if args.log:
        log_path = os.path.abspath(args.log)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        log_handle = open(log_path, "a", encoding="utf-8")

    pending = _load_pending(agent)
    pending_dirty = False
    remind_after_ms = max(0, int(args.remind_after * 1000))
    remind_interval_ms = max(0, int(args.remind_interval * 1000))
    remind_max = max(0, int(args.remind_max))
    pending_max_age_ms = max(0, int(args.pending_max_age * 1000))

    def track_pending(message: Dict[str, Any]) -> None:
        nonlocal pending_dirty
        if not _should_track_pending(message):
            return
        if message.get("from") == role:
            return
        message_id = message.get("id")
        if not message_id:
            return
        if message_id not in pending:
            pending[message_id] = _pending_entry(message, _now_ms())
            pending_dirty = True

    def run_reminders() -> None:
        nonlocal pending_dirty
        if remind_interval_ms <= 0:
            return
        now_ms = _now_ms()
        for message_id, entry in list(pending.items()):
            ts = entry.get("ts") or now_ms
            age = now_ms - int(ts)
            if pending_max_age_ms and age >= pending_max_age_ms:
                pending.pop(message_id, None)
                pending_dirty = True
                continue
            if age < remind_after_ms:
                continue
            last_remind = int(entry.get("last_remind") or 0)
            if last_remind and now_ms - last_remind < remind_interval_ms:
                continue
            if remind_max and int(entry.get("remind_count") or 0) >= remind_max:
                continue
            line = f"pending reply: from={entry.get('from')} task={entry.get('task_id')} id={message_id}"
            if args.notify:
                _notify("Codex Team Reminder", line)
            if not args.quiet:
                print(line)
            if args.auto_input and window_name:
                prompt = _reminder_prompt(role, entry)
                _autotype_to_window(window_name, _flatten_prompt(prompt))
            entry["last_remind"] = now_ms
            entry["remind_count"] = int(entry.get("remind_count") or 0) + 1
            pending_dirty = True

    def pull_once() -> None:
        result = client.inbox(agent, limit=args.limit)
        messages = result.get("messages", [])
        for message in messages:
            line = _format_message_line(message)
            if log_handle:
                log_handle.write(line + "\n")
                log_handle.flush()
            if args.notify:
                _notify("Codex Team", line)
            if not args.quiet:
                print(line)
            if args.ack:
                message_id = message.get("id")
                if message_id:
                    client.send_ack({"ack_stage": "accepted", "corr": message_id, "agent": agent})
            track_pending(message)
            if args.auto_input:
                from_role = message.get("from") or "MAIN"
                if from_role == role:
                    continue
                if prompt_template:
                    prompt = prompt_template.replace("{{ROLE}}", role).replace(
                        "{{MESSAGE}}", json.dumps(message, ensure_ascii=False)
                    )
                else:
                    prompt = _auto_input_prompt(role, message)
                prompt = _flatten_prompt(prompt)
                if not window_name:
                    if not args.quiet:
                        print("auto-input skipped: TEAM_WINDOW_NAME missing")
                else:
                    ok = _autotype_to_window(window_name, prompt)
                    if not ok:
                        if not args.quiet:
                            print(f"auto-input failed for window {window_name}")
                        if log_handle:
                            log_handle.write("auto-input: failed\n")
                            log_handle.flush()
                        corr_id = message.get("id")
                        task_id = message.get("task_id") or _auto_task_id("CHAT", role)
                        fallback_text = "AUTO-INPUT FAILED: check macOS Accessibility permissions or window name."
                        if corr_id:
                            reply = builders.build_send(
                                session=context["session"],
                                epoch=context["epoch"],
                                agent_instance=context["agent_instance"],
                                from_role=context["from_role"],
                                to=[from_role],
                                task_id=task_id,
                                corr=corr_id,
                                body={"message": fallback_text},
                                action="answer",
                            )
                            _validate_or_raise(reply)
                            client.send_message(reply)
                            _mark_pending_resolved(agent, corr_id)
                    else:
                        if log_handle:
                            log_handle.write("auto-input: ok\n")
                            log_handle.flush()
            elif args.auto_reply and role != "MAIN":
                from_role = message.get("from") or "MAIN"
                if from_role == role:
                    continue
                corr_id = message.get("id")
                task_id = message.get("task_id") or _auto_task_id("CHAT", role)
                action = message.get("action")

                if action == "verify":
                    reply = builders.build_done(
                        session=context["session"],
                        epoch=context["epoch"],
                        agent_instance=context["agent_instance"],
                        from_role=context["from_role"],
                        to=[from_role],
                        task_id=task_id,
                        corr=corr_id,
                        body={"has_new_issues": False},
                        action="verified",
                    )
                else:
                    if prompt_template:
                        prompt = prompt_template.replace("{{ROLE}}", role).replace(
                            "{{MESSAGE}}", json.dumps(message, ensure_ascii=False)
                        )
                    else:
                        prompt = _default_agent_prompt(role, message)
                    reply_text = _run_codex_exec(codex_cmd, prompt) or "收到，正在处理。"
                    reply = builders.build_send(
                        session=context["session"],
                        epoch=context["epoch"],
                        agent_instance=context["agent_instance"],
                        from_role=context["from_role"],
                        to=[from_role],
                        task_id=task_id,
                        corr=corr_id,
                        body={"message": reply_text},
                        action="answer",
                    )
                _validate_or_raise(reply)
                client.send_message(reply)
                _mark_pending_resolved(agent, corr_id)
        if not messages and not args.follow and not args.quiet:
            print("（暂无消息）")
        if args.follow:
            run_reminders()
        if pending_dirty:
            _save_pending(agent, pending)
            pending_dirty = False

    if not args.follow:
        pull_once()
        return

    try:
        while True:
            pull_once()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        if log_handle:
            log_handle.close()
        return


def handle_run(args: argparse.Namespace) -> None:
    """
    智能任务入口

    自动判断任务复杂度，简单任务单Agent处理，复杂任务多Agent并行协作。
    """
    client = RouterClient(args.router_url)

    # 1. 解析任务输入
    files = _parse_csv(args.files) if args.files else []
    task = TaskInput(
        description=args.task,
        files=files,
        context=args.context,
    )

    # 2. 创建调度器并调度任务
    scheduler = TaskScheduler(router_client=client)
    schedule_result = scheduler.schedule(task)

    # 3. 输出调度结果
    print(schedule_result.summary)
    print()

    # 4. 如果是 dry-run 模式，只输出计划
    if args.dry_run:
        _print_json({
            "status": "dry_run",
            "mode": schedule_result.mode,
            "task_id": schedule_result.task_id,
            "complexity": {
                "level": schedule_result.complexity.level,
                "score": schedule_result.complexity.score,
                "reasons": schedule_result.complexity.reasons,
                "domains": list(schedule_result.complexity.domains),
            },
            "assignments": [
                {
                    "agent": a.agent,
                    "task_id": a.task_id,
                    "domain": a.subtask.domain,
                    "description": a.subtask.description[:100],
                }
                for a in schedule_result.assignments
            ],
        })
        return

    # 5. 执行调度
    exec_result = scheduler.execute(schedule_result)

    # 6. 如果需要等待结果
    if args.wait and exec_result.get("status") == "executed":
        task_ids = [t["task_id"] for t in exec_result.get("sent_tasks", [])]
        if task_ids:
            print(f"\n等待 {len(task_ids)} 个子任务完成...")
            aggregator = ResultAggregator(router_client=client)
            results = aggregator.wait_for_results(
                task_ids,
                timeout=args.wait_timeout,
                trace_fn=lambda tid: client.trace(task_id=tid),
            )
            final = aggregator.aggregate(results, schedule_result.task_id)
            print(final.summary)
            exec_result["final_result"] = {
                "status": final.status,
                "success_count": final.success_count,
                "fail_count": final.fail_count,
                "timeout_count": final.timeout_count,
            }

    _print_json(exec_result)


def handle_analyze(args: argparse.Namespace) -> None:
    """
    分析现有项目

    在加新功能前，先搞清楚：
    1. 项目结构是什么样的
    2. 有哪些组件、API、数据模型
    3. 新功能会影响哪些地方
    4. 风险有多大
    """
    project_path = args.path or os.getcwd()

    # 1. 分析项目结构
    print("正在分析项目结构...")
    structure = analyze_project(project_path)

    print("=" * 60)
    print(format_project_analysis(structure))
    print("=" * 60)

    # 2. 如果指定了新功能，进行影响分析
    if args.feature:
        print()
        print("正在分析新功能影响...")
        impact = analyze_impact(structure, args.feature)

        print("=" * 60)
        print(format_impact_analysis(impact))
        print("=" * 60)

        # 风险提示
        if impact.overall_risk.value in ["high", "critical"]:
            print()
            print("⚠️  风险较高！建议：")
            print("   1. 仔细审阅上述分析报告")
            print("   2. 与团队讨论实现方案")
            print("   3. 分阶段实现，先做核心功能")
            print("   4. 编写测试用例保护现有功能")
        else:
            print()
            print("✅ 风险可控，可以继续：")
            print(f"   team design --requirement \"{args.feature}\" --existing")

    # 3. JSON 输出
    if args.json:
        _print_json({
            "project_type": structure.project_type,
            "total_files": structure.total_files,
            "files_by_language": structure.files_by_language,
            "components_count": len(structure.components),
            "apis_count": len(structure.apis),
            "models_count": len(structure.models),
        })


def handle_design(args: argparse.Namespace) -> None:
    """
    需求分析与设计

    这是最关键的一步！新项目必须先设计，确认后才能实现。
    流程：用户需求 → 生成设计 → 用户确认 → 开始实现
    """
    # 1. 分析需求并生成设计
    project_type = ProjectType.NEW
    if args.existing:
        project_type = ProjectType.EXISTING
    elif args.refactor:
        project_type = ProjectType.REFACTOR

    design_doc = analyze_and_design(
        user_input=args.requirement,
        project_name=args.name or "新项目",
    )
    design_doc.project_type = project_type

    # 2. 输出设计文档
    print("=" * 60)
    print(print_design_for_review(design_doc))
    print("=" * 60)

    # 3. 输出 JSON 格式（可保存）
    if args.json:
        _print_json({
            "status": "design_generated",
            "project_name": design_doc.project_name,
            "project_type": design_doc.project_type.value,
            "design_status": design_doc.status.value,
            "requirements_count": len(design_doc.requirements),
            "entities_count": len(design_doc.entities),
            "api_count": len(design_doc.api_endpoints),
            "screens_count": len(design_doc.screens),
            "clarification_questions": design_doc.clarification_questions,
        })

    # 4. 提示用户
    print()
    print("⚠️  请审阅以上设计文档！")
    print("   如果设计符合预期，使用以下命令继续：")
    print(f"   team run --task \"{args.requirement}\" --design-approved")
    print()
    print("   如果需要修改，请重新描述需求或回答上述问题。")


def handle_board(args: argparse.Namespace) -> None:
    """
    查看进度看板

    显示所有 Agent 的实时进度
    """
    client = RouterClient(args.router_url)
    hub = _get_collaboration_hub(client)
    
    task_id = args.task if hasattr(args, 'task') else None
    
    # 输出进度看板
    print(hub.progress_board.format_board(task_id))
    
    # 显示被阻塞的 Agent
    blocked = hub.progress_board.get_blocked_agents()
    if blocked:
        print()
        print("⚠️ 阻塞情况:")
        for b in blocked:
            print(f"  - {b.agent} 被阻塞: {b.blocked_reason or '未知原因'}")
    
    # JSON 输出
    if args.json:
        board = hub.progress_board.get_board(task_id)
        _print_json({
            "task_id": task_id,
            "agents": {
                a: {
                    "status": p.status,
                    "progress": p.progress,
                    "current_step": p.current_step,
                    "blocked_by": p.blocked_by,
                }
                for a, p in board.items()
            },
            "blocked_count": len(blocked),
        })


def handle_progress(args: argparse.Namespace) -> None:
    """
    报告进度

    Agent 报告自己的当前进度
    """
    client = RouterClient(args.router_url)
    hub = _get_collaboration_hub(client)
    
    agent = args.agent or os.environ.get("TEAM_ROLE") or "A"
    
    hub.report_progress(
        agent=agent,
        task_id=args.task,
        subtask_id=args.subtask or args.task,
        progress=args.percent,
        status=args.status,
        current_step=args.step,
    )
    
    print(f"✅ 进度已更新: {agent} - {args.percent}% - {args.step}")


def handle_lock(args: argparse.Namespace) -> None:
    """
    文件锁定

    锁定或解锁文件，防止冲突
    """
    client = RouterClient(args.router_url)
    hub = _get_collaboration_hub(client)
    
    agent = args.agent or os.environ.get("TEAM_ROLE") or "A"
    
    if args.unlock:
        # 解锁
        for file_path in _parse_csv(args.files):
            success = hub.file_lock_manager.unlock(file_path, agent)
            if success:
                print(f"🔓 已解锁: {file_path}")
            else:
                print(f"❌ 解锁失败: {file_path}（可能不是你锁定的）")
    else:
        # 锁定
        for file_path in _parse_csv(args.files):
            success, result = hub.file_lock_manager.try_lock(
                file_path=file_path,
                agent=agent,
                task_id=args.task,
                reason=args.reason or "开发中",
            )
            if success:
                print(f"🔒 已锁定: {file_path}")
            else:
                print(f"❌ 锁定失败: {file_path} - {result}")
    
    # 显示当前锁定状态
    if args.list:
        locks = hub.file_lock_manager.get_agent_locks(agent)
        if locks:
            print(f"\n{agent} 当前锁定的文件:")
            for lock in locks:
                print(f"  - {lock.file_path} ({lock.reason})")
        else:
            print(f"\n{agent} 没有锁定任何文件")


def handle_notify(args: argparse.Namespace) -> None:
    """
    发送变更通知

    通知其他 Agent 接口或代码发生了变更
    """
    client = RouterClient(args.router_url)
    hub = _get_collaboration_hub(client)
    
    agent = args.agent or os.environ.get("TEAM_ROLE") or "A"
    
    recipients = hub.broadcaster.broadcast_interface_change(
        from_agent=agent,
        task_id=args.task,
        change_type=args.change_type,
        interface_name=args.interface,
        old_value=args.old_value,
        new_value=args.new_value,
        reason=args.reason or "",
    )
    
    print(f"📢 已通知接口变更: {args.interface}")
    if recipients:
        print(f"   接收者: {', '.join(recipients)}")
    else:
        print("   （暂无订阅者）")


def handle_watch(args: argparse.Namespace) -> None:
    """
    实时监控所有 Agent 状态
    
    持续显示所有 Agent 的在线状态和活动信息
    """
    import signal
    
    client = RouterClient(args.router_url)
    running = True
    
    def signal_handler(sig, frame):
        nonlocal running
        running = False
        print("\n👋 停止监控")
    
    signal.signal(signal.SIGINT, signal_handler)
    
    role_names = {
        "MAIN": "协调者",
        "A": "前端专家",
        "B": "后端专家", 
        "C": "数据专家",
        "D": "辅助专家",
    }
    
    status_icons = {
        "online": "🟢",
        "offline": "⚫",
        "busy": "🟡",
    }
    
    print("📊 Agent 状态监控 (Ctrl+C 退出)")
    print("=" * 60)
    
    while running:
        try:
            # 获取 presence 数据
            response = client.presence()
            agents = response.get("agents", {})
            
            # 获取活动状态
            try:
                with urlopen(f"{args.router_url}/activity", timeout=5) as resp:
                    activity_response = json.loads(resp.read().decode("utf-8"))
                activities = activity_response.get("activities", {})
            except Exception:
                activities = {}
            
            # 清屏并显示
            print("\033[H\033[J", end="")  # 清屏
            print("📊 Agent 状态监控 (Ctrl+C 退出)")
            print("=" * 60)
            print(f"时间: {time.strftime('%H:%M:%S')}")
            print()
            
            for agent_id, info in agents.items():
                role = info.get("meta", {}).get("role", "?")
                role_name = role_names.get(role, role)
                status = info.get("status", "offline")
                icon = status_icons.get(status, "❓")
                
                # 计算离线时间
                last_seen = info.get("last_seen", 0)
                now = response.get("now", int(time.time() * 1000))
                offline_sec = (now - last_seen) // 1000
                
                # 获取活动状态
                activity = activities.get(agent_id, {})
                activity_text = activity.get("status", "")
                activity_task = activity.get("task", "")
                
                print(f"{icon} {role} ({role_name})")
                if status == "online":
                    if activity_text:
                        print(f"   💭 {activity_text}")
                        if activity_task:
                            print(f"   📋 任务: {activity_task}")
                    else:
                        print(f"   ⏳ 待命中")
                else:
                    print(f"   ⏱️  离线 {offline_sec}s")
                print()
            
            time.sleep(args.interval)
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"❌ 错误: {e}")
            time.sleep(args.interval)


def handle_activity(args: argparse.Namespace) -> None:
    """
    上报当前活动状态
    
    让其他 Agent 和监控知道自己在做什么
    """
    agent = args.agent or os.environ.get("TEAM_AGENT_ID") or os.environ.get("TEAM_ROLE") or "A"
    
    payload = {
        "agent": agent,
        "status": args.status,
        "task": args.task or "",
        "ts": int(time.time() * 1000),
    }
    
    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = Request(
            f"{args.router_url}/activity",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        print(f"✅ 状态已更新: {args.status}")
        if args.task:
            print(f"📋 关联任务: {args.task}")
    except Exception as e:
        # 如果 Router 不支持这个端点，本地打印
        print(f"💭 当前状态: {args.status}")
        if args.task:
            print(f"📋 关联任务: {args.task}")


def handle_schedule(args: argparse.Namespace) -> None:
    """
    仅调度任务（不执行）

    分析任务并输出调度计划。
    """
    # 解析任务输入
    files = _parse_csv(args.files) if args.files else []
    task = TaskInput(
        description=args.task,
        files=files,
        context=args.context,
    )

    # 创建调度器并调度任务
    scheduler = TaskScheduler()
    schedule_result = scheduler.schedule(task)

    # 输出调度结果
    print(schedule_result.summary)
    print()

    # 输出JSON格式
    _print_json({
        "status": "scheduled",
        "mode": schedule_result.mode,
        "task_id": schedule_result.task_id,
        "complexity": {
            "level": schedule_result.complexity.level,
            "score": schedule_result.complexity.score,
            "reasons": schedule_result.complexity.reasons,
            "domains": list(schedule_result.complexity.domains),
            "parallelizable": schedule_result.complexity.parallelizable,
        },
        "assignments": [
            {
                "agent": a.agent,
                "agent_name": SPECIALIZED_AGENTS[a.agent].name if a.agent in SPECIALIZED_AGENTS else a.agent,
                "task_id": a.task_id,
                "domain": a.subtask.domain,
                "description": a.subtask.description,
                "files": a.subtask.files,
                "success_criteria": a.subtask.success_criteria,
                "dependencies": a.subtask.dependencies,
            }
            for a in schedule_result.assignments
        ],
        "execution_order": schedule_result.decompose_result.execution_order if schedule_result.decompose_result else [],
    })


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", help="config JSON path")
    common.add_argument("--workspace", help="workspace path")
    common.add_argument("--router-url", help="router base URL (e.g. http://127.0.0.1:8765)")
    common.add_argument("--router-host", help="router host")
    common.add_argument("--router-port", type=int, help="router port")

    parser = argparse.ArgumentParser(prog="team", parents=[common])
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", parents=[common])
    start.add_argument("--roles", help="comma-separated roles")
    start.add_argument("--terminal-adapter", choices=["terminal", "iterm2", "tmux"], help="terminal adapter")
    start.add_argument("--codex-path", help="codex executable or command")
    start.add_argument("--window-name-format", help="window name format")
    start.add_argument("--router-wait", type=int, default=8, help="seconds to wait for router")
    start.add_argument("--router-log", help="router log path")
    start.add_argument("--no-presence", action="store_true", help="skip presence.register after launch")
    start.set_defaults(func=handle_start)

    review = subparsers.add_parser("review", parents=[common])
    review.add_argument("--to", required=True)
    review.add_argument("--task", required=True)
    review.add_argument("--owner")
    review.add_argument("--file", required=True)
    review.add_argument("--focus")
    review.add_argument("--review-deadline")
    review.add_argument("--deadline", help="alias for --review-deadline")
    review.add_argument("--from", dest="from_role")
    review.add_argument("--agent-instance")
    review.add_argument("--wait")
    review.add_argument("--wait-timeout", type=int, default=120)
    review.add_argument("--wait-poll", type=float, default=1.0)
    review.add_argument("--default-review-deadline-s", type=int, default=3600)
    review.set_defaults(func=handle_review)

    assign = subparsers.add_parser("assign", parents=[common])
    assign.add_argument("--to", required=True)
    assign.add_argument("--task", required=True)
    assign.add_argument("--owner")
    assign.add_argument("--deadline", required=True)
    assign.add_argument("--files", required=True)
    assign.add_argument("--success-criteria", required=True)
    assign.add_argument("--dependencies")
    assign.add_argument("--action", help="task_type for assign")
    assign.add_argument("--from", dest="from_role")
    assign.add_argument("--agent-instance")
    assign.add_argument("--wait")
    assign.add_argument("--wait-timeout", type=int, default=120)
    assign.add_argument("--wait-poll", type=float, default=1.0)
    assign.set_defaults(func=handle_assign)

    ask = subparsers.add_parser("ask", parents=[common])
    ask.add_argument("--to", required=True)
    ask.add_argument("--task", required=True)
    ask.add_argument("--owner")
    ask.add_argument("--action", required=True)
    ask.add_argument("--doc-path")
    ask.add_argument("--code-path")
    ask.add_argument("--question")
    ask.add_argument("--context")
    ask.add_argument("--expected")
    ask.add_argument("--changes-summary")
    ask.add_argument("--from", dest="from_role")
    ask.add_argument("--agent-instance")
    ask.add_argument("--wait")
    ask.add_argument("--wait-timeout", type=int, default=120)
    ask.add_argument("--wait-poll", type=float, default=1.0)
    ask.set_defaults(func=handle_ask)

    send = subparsers.add_parser("send", parents=[common])
    send.add_argument("--to", required=True)
    send.add_argument("--task", required=True)
    send.add_argument("--owner")
    send.add_argument("--corr", required=True)
    send.add_argument("--body", required=True)
    send.add_argument("--from", dest="from_role")
    send.add_argument("--agent-instance")
    send.add_argument("--wait")
    send.add_argument("--wait-timeout", type=int, default=120)
    send.add_argument("--wait-poll", type=float, default=1.0)
    send.set_defaults(func=handle_send)

    done = subparsers.add_parser("done", parents=[common])
    done.add_argument("--to", required=True)
    done.add_argument("--task", required=True)
    done.add_argument("--corr", required=True)
    done.add_argument("--action")
    done.add_argument("--body")
    done.add_argument("--from", dest="from_role")
    done.add_argument("--agent-instance")
    done.add_argument("--wait")
    done.add_argument("--wait-timeout", type=int, default=120)
    done.add_argument("--wait-poll", type=float, default=1.0)
    done.set_defaults(func=handle_done)

    fail = subparsers.add_parser("fail", parents=[common])
    fail.add_argument("--to", required=True)
    fail.add_argument("--task", required=True)
    fail.add_argument("--corr", required=True)
    fail.add_argument("--reason", required=True)
    fail.add_argument("--blocked-by")
    fail.add_argument("--from", dest="from_role")
    fail.add_argument("--agent-instance")
    fail.add_argument("--wait")
    fail.add_argument("--wait-timeout", type=int, default=120)
    fail.add_argument("--wait-poll", type=float, default=1.0)
    fail.set_defaults(func=handle_fail)

    report = subparsers.add_parser("report", parents=[common])
    report.add_argument("--to", required=True)
    report.add_argument("--task", required=True)
    report.add_argument("--owner")
    report.add_argument("--corr", required=True)
    report.add_argument("--body", required=True)
    report.add_argument("--from", dest="from_role")
    report.add_argument("--agent-instance")
    report.add_argument("--wait")
    report.add_argument("--wait-timeout", type=int, default=120)
    report.add_argument("--wait-poll", type=float, default=1.0)
    report.set_defaults(func=handle_report)

    status = subparsers.add_parser("status", parents=[common])
    status.add_argument("--tasks", action="store_true")
    status.add_argument("--filter", dest="filter_task")
    status.set_defaults(func=handle_status)

    trace = subparsers.add_parser("trace", parents=[common])
    trace_group = trace.add_mutually_exclusive_group(required=True)
    trace_group.add_argument("--task")
    trace_group.add_argument("--id")
    trace.set_defaults(func=handle_trace)

    inbox = subparsers.add_parser("inbox", parents=[common])
    inbox.add_argument("--agent", help="agent instance id (default: TEAM_AGENT_ID)")
    inbox.add_argument("--limit", type=int, default=1)
    inbox.add_argument("--follow", action="store_true", help="poll inbox continuously")
    inbox.add_argument("--interval", type=float, default=1.0, help="poll interval seconds")
    inbox.add_argument("--no-ack", dest="ack", action="store_false", help="do not send accepted ack")
    inbox.set_defaults(func=handle_inbox, ack=True)

    say = subparsers.add_parser("say", parents=[common])
    say.add_argument("--to", required=True)
    say.add_argument("--text", required=True)
    say.add_argument("--task")
    say.add_argument("--owner")
    say.add_argument("--doc-path")
    say.add_argument("--code-path")
    say.add_argument("--context")
    say.add_argument("--expected")
    say.add_argument("--from", dest="from_role")
    say.add_argument("--agent-instance")
    say.add_argument("--wait")
    say.add_argument("--wait-timeout", type=int, default=120)
    say.add_argument("--wait-poll", type=float, default=1.0)
    say.set_defaults(func=handle_say)

    reply = subparsers.add_parser("reply", parents=[common])
    reply.add_argument("--to", required=True)
    reply.add_argument("--corr", required=True)
    reply.add_argument("--text", required=True)
    reply.add_argument("--task")
    reply.add_argument("--owner")
    reply.add_argument("--doc-path")
    reply.add_argument("--code-path")
    reply.add_argument("--doc-updated", action="store_true")
    reply.add_argument("--from", dest="from_role")
    reply.add_argument("--agent-instance")
    reply.add_argument("--wait")
    reply.add_argument("--wait-timeout", type=int, default=120)
    reply.add_argument("--wait-poll", type=float, default=1.0)
    reply.set_defaults(func=handle_reply)

    listen = subparsers.add_parser("listen", parents=[common])
    listen.add_argument("--agent", help="agent instance id (default: TEAM_AGENT_ID)")
    listen.add_argument("--limit", type=int, default=3)
    listen.add_argument("--follow", action="store_true", help="poll inbox continuously")
    listen.add_argument("--interval", type=float, default=1.0, help="poll interval seconds")
    listen.add_argument("--no-ack", dest="ack", action="store_false", help="do not send accepted ack")
    listen.add_argument("--log", help="append messages to a log file")
    listen.add_argument("--notify", action="store_true", help="macOS notification on message")
    listen.add_argument("--quiet", action="store_true", help="do not print to stdout")
    listen_auto = listen.add_mutually_exclusive_group()
    listen_auto.add_argument("--auto-reply", action="store_true", help="auto reply via codex exec")
    listen_auto.add_argument("--auto-input", action="store_true", help="auto input prompt into the agent window")
    listen.add_argument("--codex-cmd", help="codex command path for exec")
    listen.add_argument("--prompt-path", help="prompt template file (use {{ROLE}} and {{MESSAGE}})")
    listen.add_argument("--role", help="role override (default: TEAM_ROLE)")
    listen.add_argument("--window-name", help="target window name for auto-input (default: TEAM_WINDOW_NAME)")
    listen.add_argument("--remind-after", type=int, default=60, help="seconds before first reminder")
    listen.add_argument("--remind-interval", type=int, default=300, help="seconds between reminders")
    listen.add_argument("--remind-max", type=int, default=0, help="max reminder count (0=unlimited)")
    listen.add_argument("--pending-max-age", type=int, default=604800, help="seconds to keep pending entries")
    listen.set_defaults(func=handle_listen, ack=True)

    # 项目分析（加新功能前必须先分析！）
    analyze = subparsers.add_parser("analyze", parents=[common], help="分析现有项目结构和影响范围")
    analyze.add_argument("--path", "-p", help="项目路径（默认当前目录）")
    analyze.add_argument("--feature", "-f", help="要添加的新功能（进行影响分析）")
    analyze.add_argument("--json", action="store_true", help="同时输出 JSON 格式")
    analyze.set_defaults(func=handle_analyze)

    # 需求分析与设计（最重要的一步！）
    design = subparsers.add_parser("design", parents=[common], help="需求分析与设计 - 新项目必须先设计")
    design.add_argument("--requirement", "-r", required=True, help="用户需求描述")
    design.add_argument("--name", "-n", help="项目名称")
    design.add_argument("--existing", action="store_true", help="已有项目（基于现有架构）")
    design.add_argument("--refactor", action="store_true", help="重构项目")
    design.add_argument("--json", action="store_true", help="同时输出 JSON 格式")
    design.set_defaults(func=handle_design)

    # 智能任务入口
    run = subparsers.add_parser("run", parents=[common], help="智能任务入口 - 自动判断复杂度并分流")
    run.add_argument("--task", required=True, help="任务描述")
    run.add_argument("--files", help="涉及的文件列表（逗号分隔）")
    run.add_argument("--context", help="上下文信息")
    run.add_argument("--dry-run", action="store_true", help="仅输出调度计划，不执行")
    run.add_argument("--wait", action="store_true", help="等待所有子任务完成")
    run.add_argument("--wait-timeout", type=int, default=3600, help="等待超时时间（秒）")
    run.add_argument("--design-approved", action="store_true", help="确认设计已通过审核")
    run.set_defaults(func=handle_run)

    # 任务调度（仅分析）
    schedule = subparsers.add_parser("schedule", parents=[common], help="分析任务并输出调度计划")
    schedule.add_argument("--task", required=True, help="任务描述")
    schedule.add_argument("--files", help="涉及的文件列表（逗号分隔）")
    schedule.add_argument("--context", help="上下文信息")
    schedule.set_defaults(func=handle_schedule)

    # ============================================================
    # 协作命令
    # ============================================================

    # 进度看板
    board = subparsers.add_parser("board", parents=[common], help="查看进度看板")
    board.add_argument("--task", "-t", help="筛选特定任务")
    board.add_argument("--json", action="store_true", help="输出 JSON 格式")
    board.set_defaults(func=handle_board)

    # 报告进度
    progress = subparsers.add_parser("progress", parents=[common], help="报告当前进度")
    progress.add_argument("--task", "-t", required=True, help="任务 ID")
    progress.add_argument("--subtask", help="子任务 ID")
    progress.add_argument("--percent", "-p", type=int, required=True, help="完成百分比 0-100")
    progress.add_argument("--status", "-s", default="in_progress", 
                          choices=["pending", "in_progress", "blocked", "completed", "failed"],
                          help="状态")
    progress.add_argument("--step", required=True, help="当前步骤描述")
    progress.add_argument("--agent", "-a", help="Agent 角色（默认从环境变量）")
    progress.set_defaults(func=handle_progress)

    # 文件锁定
    lock = subparsers.add_parser("lock", parents=[common], help="锁定/解锁文件")
    lock.add_argument("--files", "-f", required=True, help="文件列表（逗号分隔）")
    lock.add_argument("--task", "-t", required=True, help="任务 ID")
    lock.add_argument("--unlock", "-u", action="store_true", help="解锁文件")
    lock.add_argument("--reason", "-r", help="锁定原因")
    lock.add_argument("--agent", "-a", help="Agent 角色")
    lock.add_argument("--list", "-l", action="store_true", help="列出当前锁定的文件")
    lock.set_defaults(func=handle_lock)

    # 变更通知
    notify = subparsers.add_parser("notify", parents=[common], help="通知接口/代码变更")
    notify.add_argument("--task", "-t", required=True, help="任务 ID")
    notify.add_argument("--interface", "-i", required=True, help="接口名称")
    notify.add_argument("--change-type", "-c", required=True, 
                        choices=["add", "modify", "remove"], help="变更类型")
    notify.add_argument("--old-value", help="旧值")
    notify.add_argument("--new-value", help="新值")
    notify.add_argument("--reason", "-r", help="变更原因")
    notify.add_argument("--agent", "-a", help="Agent 角色")
    notify.set_defaults(func=handle_notify)

    # 实时监控
    watch = subparsers.add_parser("watch", parents=[common], help="实时监控所有 Agent 状态")
    watch.add_argument("--interval", "-i", type=float, default=2.0, help="刷新间隔（秒）")
    watch.set_defaults(func=handle_watch)
    
    # 上报活动状态
    activity = subparsers.add_parser("activity", parents=[common], help="上报当前活动状态")
    activity.add_argument("--status", "-s", required=True, help="状态描述（如：思考中、编码中、测试中）")
    activity.add_argument("--task", "-t", help="关联的任务 ID")
    activity.add_argument("--agent", "-a", help="Agent 角色")
    activity.set_defaults(func=handle_activity)

    return parser


def main(argv: Optional[List[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    # 这些命令不需要 router 连接
    no_router_commands = ("schedule", "design", "analyze", "board", "progress", "lock", "notify")
    if args.command in no_router_commands:
        try:
            args.func(args)
        except Exception as exc:
            _print_json({"status": "error", "error": str(exc)})
            sys.exit(1)
        return

    if args.command != "start":
        config = load_config(args.config, args.workspace)
        args.router_url = resolve_router_url(config, args.router_url, args.router_host, args.router_port)
        if hasattr(args, "default_review_deadline_s") and config.get("default_review_deadline_s"):
            args.default_review_deadline_s = int(config["default_review_deadline_s"])

    try:
        args.func(args)
    except ValidationError as exc:
        _print_json({"status": "error", "error": "validation", "details": exc.errors})
        sys.exit(1)
    except Exception as exc:
        _print_json({"status": "error", "error": str(exc)})
        sys.exit(1)


if __name__ == "__main__":
    main()
