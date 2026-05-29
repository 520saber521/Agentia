"""工具注册中心 — 管理工具定义、生成 JSON Schema、执行内置工具。

架构
====
``ToolRegistry`` 是 ReAct 循环的工具层，负责三件事：

1. **注册** — 内置工具注册到全局 registry，支持分类索引和批量注册
2. **Schema 生成** — 为原生 Function Calling 模型生成 ``tools`` 参数
3. **结构化提示词** — 为不支持原生 FC 的模型生成描述文本

优化 (v2):
- ToolCategory 枚举实现工具分类索引，O(1) 按类别查找
- register_batch() 批量注册，验证依赖完整性
- get_categories() 发现可用工具分类
- lazy_init 支持延迟初始化，减少启动开销

内置工具
========
- ``read_file`` — 读取本地文件
- ``write_file`` — 写入/创建文件
- ``web_search`` — 搜索网页
- ``list_files`` — 列出目录内容
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from sqlalchemy import select

from db.engine import get_sessionmaker
from db.models import ConversationMember
from services.animation_bus import animation_bus

logger = logging.getLogger("agenthub.services.tool_registry")


class ToolCategory(Enum):
    FILE_IO = "file_io"
    CODE_EXEC = "code_exec"
    WEB = "web"
    SYSTEM = "system"
    CUSTOM = "custom"
    AGENT_COMM = "agent_comm"


@dataclass
class Tool:
    """单个工具定义。"""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
    handler: Callable[..., Any]
    category: ToolCategory = ToolCategory.CUSTOM
    requires_confirmation: bool = False
    dependencies: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 内置工具 handler
# ---------------------------------------------------------------------------

_ALLOWED_ROOTS: list[str] = []


def _normalize_path(path: str, project_root: str = "") -> str | None:
    if not path:
        return None
    abs_path = os.path.abspath(os.path.join(project_root, path))
    allowed = _ALLOWED_ROOTS or [os.path.abspath(project_root)] if project_root else []
    if allowed and not any(abs_path.startswith(r) for r in allowed):
        return None
    return abs_path


async def _read_file(path: str, project_root: str = "", **kwargs: Any) -> str:
    safe = _normalize_path(path, project_root)
    if not safe:
        return "Error: path outside allowed directory"
    try:
        # Check file size before reading
        stat = os.stat(safe)
        max_bytes = 1_000_000  # 1 MB
        if stat.st_size > max_bytes:
            return (
                f"Error: file too large ({stat.st_size / 1024 / 1024:.1f} MB). "
                f"Max read size is {max_bytes / 1024 / 1024:.1f} MB. "
                f"Use a more specific file path or process in smaller chunks."
            )
        loop = asyncio.get_running_loop()
        with open(safe, "r", encoding="utf-8", errors="replace") as f:
            content = await loop.run_in_executor(None, f.read)
        return content
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except IsADirectoryError:
        return f"Error: is a directory: {path}"
    except PermissionError:
        return f"Error: permission denied: {path}"
    except Exception as exc:
        return f"Error reading file: {exc}"


async def _read_artifact(
    artifact_id: str = "",
    file_name: str = "",
    conversation_id: str = "",
    **kwargs: Any,
) -> str:
    """Read a previously created artifact by ID or by filename in the current conversation."""
    from services.artifact import get_artifact, list_artifacts, read_artifact_content_with_session

    Session = get_sessionmaker()
    async with Session() as s:
        aid = artifact_id.strip()
        if aid:
            artifact = await get_artifact(s, aid)
            if artifact is None:
                return f"Error: artifact not found: {aid}"
            content = await read_artifact_content_with_session(s, aid)
            if content is None:
                return f"Error: cannot read content of artifact {aid}"
            return (
                f"--- Artifact: {artifact['title']} ({artifact.get('file_name', 'unknown')}) ---\n"
                f"ID: {artifact['id']}\n"
                f"Kind: {artifact['kind']}\n"
                f"Content:\n{content}"
            )

        # Search by filename in the current conversation
        fname = file_name.strip()
        if not fname:
            return "Error: provide artifact_id or file_name"
        if not conversation_id:
            return "Error: conversation_id required for file_name lookup"

        items = await list_artifacts(s, conversation_id, limit=50)
        matches = [a for a in items if a.get("file_name") == fname]
        if not matches:
            # Try partial match
            matches = [a for a in items if fname.lower() in (a.get("file_name") or "").lower()]
        if not matches:
            available = ", ".join(a.get("file_name", "?") for a in items[:10]) or "(none)"
            return f"Error: no artifact with file_name '{fname}' in this conversation.\nAvailable artifacts: {available}"

        artifact = matches[0]
        content = await read_artifact_content_with_session(s, artifact["id"])
        if content is None:
            return f"Error: cannot read content of artifact {artifact['id']}"
        return (
            f"--- Artifact: {artifact['title']} ({artifact.get('file_name', 'unknown')}) ---\n"
            f"ID: {artifact['id']}\n"
            f"Kind: {artifact['kind']}\n"
            f"Content:\n{content}"
        )


async def _write_file(
    path: str,
    content: str,
    project_root: str = "",
    conversation_id: str = "",
    conn: Any = None,
    **kwargs: Any,
) -> str:
    safe = _normalize_path(path, project_root)
    if not safe:
        return "Error: path outside allowed directory"
    try:
        existed = os.path.exists(safe)
        os.makedirs(os.path.dirname(safe), exist_ok=True)
        loop = asyncio.get_running_loop()
        with open(safe, "w", encoding="utf-8") as f:
            await loop.run_in_executor(None, f.write, content)
        # Notify frontend of workspace file change
        if conn is not None and conversation_id:
            try:
                from ws import event as ws_event
                await conn.send(ws_event(
                    "workspace_file_changed",
                    conversation_id=conversation_id,
                    path=path,
                    action="modified" if existed else "created",
                ))
            except Exception:
                pass
        return f"OK: wrote {len(content)} bytes to {path}"
    except PermissionError:
        return f"Error: permission denied: {path}"
    except Exception as exc:
        return f"Error writing file: {exc}"


async def _list_files(
    path: str = ".",
    pattern: str = "",
    project_root: str = "",
    **kwargs: Any,
) -> str:
    safe = _normalize_path(path, project_root)
    if not safe:
        return "Error: path outside allowed directory"
    try:
        entries = os.listdir(safe)
        if pattern:
            pat = re.compile(pattern, re.IGNORECASE)
            entries = [e for e in entries if pat.search(e)]
        lines = []
        for e in sorted(entries):
            full = os.path.join(safe, e)
            suffix = "/" if os.path.isdir(full) else ""
            lines.append(f"{e}{suffix}")
        if not lines:
            return f"(empty directory: {path})"
        return "\n".join(lines)
    except FileNotFoundError:
        return f"Error: directory not found: {path}"
    except NotADirectoryError:
        return f"Error: not a directory: {path}"
    except PermissionError:
        return f"Error: permission denied: {path}"
    except Exception as exc:
        return f"Error listing directory: {exc}"


async def _web_search(query: str, **kwargs: Any) -> str:
    """Search the web and return results. Tries DuckDuckGo first, falls back to Bing."""
    import httpx

    async def _try_ddg(q: str) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://api.duckduckgo.com/",
                    params={"q": q, "format": "json", "no_html": "1", "skip_disambig": "1"},
                )
                if resp.status_code != 200:
                    return None
                data = resp.json()
                abs_text = data.get("AbstractText", "").strip()
                related = [t.get("Text", "") for t in data.get("RelatedTopics", [])[:3] if t.get("Text")]
                parts = [abs_text] if abs_text else []
                parts.extend(related[:4])
                return "\n\n".join(parts) if parts else None
        except Exception:
            return None

    async def _try_ddg_html(q: str) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://html.duckduckgo.com/html/",
                    data={"q": q},
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if resp.status_code != 200:
                    return None
                text = resp.text
                results = re.findall(
                    r'class="result__snippet">(.*?)</a>',
                    text,
                    re.DOTALL,
                )
                if results:
                    return "\n\n".join(
                        re.sub(r"<[^>]+>", "", r).strip() for r in results[:5]
                    )
                return None
        except Exception:
            return None

    # Try DuckDuckGo JSON API first (fast, clean), then HTML fallback
    result = await _try_ddg(query)
    if result:
        return result

    result = await _try_ddg_html(query)
    if result:
        return result

    # Search failed — guide the model to continue with its own knowledge
    return (
        "搜索服务暂时不可用（网络限制或超时）。\n"
        "请使用你自己的知识继续完成任务。如果你需要生成文件，请调用 create_artifact 工具。\n"
        f"原始搜索关键词: {query}"
    )


async def _create_agent_tool(
    role: str,
    guidance: str = "",
    conversation_id: str = "",
    current_agent_id: str = "",
    **kwargs: Any,
) -> str:
    from services.agent import create_agent

    if not conversation_id:
        return "Error: conversation_id unavailable"
    clean_role = (role or "assistant").strip()[:80]
    system_prompt = guidance.strip() or f"You are a specialized {clean_role} agent."
    Session = get_sessionmaker()
    async with Session() as s:
        created = await create_agent(
            s,
            name=clean_role,
            adapter_type="mock",
            config={"system_prompt": system_prompt},
            capabilities=[clean_role.lower(), "agent_comm"],
            avatar=None,
        )
        s.add(ConversationMember(
            conversation_id=conversation_id,
            member_id=created["id"],
            member_type="agent",
            role="worker",
        ))
        await s.commit()
    animation_bus.agent_created(
        conversation_id=conversation_id,
        agent_id=created["id"],
        role=clean_role,
        parent_id=current_agent_id or None,
        domain=clean_role.lower(),
        agent_name=created["name"],
    )
    if current_agent_id:
        animation_bus.beam(
            conversation_id=conversation_id,
            from_id=current_agent_id,
            to_id=created["id"],
            kind="create",
            label=clean_role,
        )
    animation_bus.viz_event(
        conversation_id=conversation_id,
        kind="agent",
        label=f"created agent: {created['name']}",
    )
    return json.dumps({"ok": True, "agentId": created["id"], "role": clean_role}, ensure_ascii=False)


async def _create_artifact_tool(
    kind: str,
    title: str,
    content: str,
    mime_type: str = "text/plain",
    file_name: str = "",
    conversation_id: str = "",
    current_agent_id: str = "",
    conn: Any = None,
    _artifacts: Any = None,
    **kwargs: Any,
) -> str:
    """Create a file/code/preview artifact in the current conversation.

    The artifact is persisted to disk and broadcast to all connected clients.
    Use this whenever your output is a complete file (report, code, config, doc, etc.).
    """
    from services.artifact import create_artifact as create_service_artifact

    if not conversation_id:
        return "Error: conversation_id unavailable"
    if kind not in ("file", "code", "preview", "diff"):
        return "Error: kind must be one of: file, code, preview, diff"
    if not title or not title.strip():
        return "Error: title required"
    if not content or not content.strip():
        return "Error: content required"

    Session = get_sessionmaker()
    async with Session() as s:
        artifact = await create_service_artifact(
            s,
            conversation_id=conversation_id,
            kind=kind,
            title=title.strip(),
            mime_type=mime_type or "text/plain",
            file_name=file_name or None,
            content=content.strip(),
            source_message_id=None,
            created_by=current_agent_id or "agent",
        )

    # Signal that an artifact was created — post-loop code checks this list
    if isinstance(_artifacts, list):
        _artifacts.append(artifact)

    # Broadcast artifact_ready so frontend can show it immediately
    if conn is not None:
        try:
            from ws import event
            await conn.send(event(
                "artifact_ready",
                conversation_id=conversation_id,
                artifact=artifact,
            ))
        except Exception:
            pass

    return json.dumps({
        "ok": True,
        "artifact_id": artifact["id"],
        "kind": kind,
        "title": title.strip(),
        "file_name": artifact.get("file_name") or file_name,
        "file_path": artifact.get("storage_path", ""),
        "version": artifact.get("version", 1),
        "hint": f"后续可用 read_artifact(artifact_id='{artifact['id']}') 或 read_artifact(file_name='{artifact.get('file_name') or file_name}') 读取此文件。",
    }, ensure_ascii=False)


async def _send_agent_message_tool(
    to_agent_id: str,
    content: str,
    conversation_id: str = "",
    current_agent_id: str = "",
    conn: Any = None,
    **kwargs: Any,
) -> str:
    from services.message import create_message, message_to_dict

    if not conversation_id:
        return "Error: conversation_id unavailable"
    if not to_agent_id:
        return "Error: to_agent_id required"
    Session = get_sessionmaker()
    async with Session() as s:
        member = await s.get(ConversationMember, (conversation_id, to_agent_id))
        if member is None:
            s.add(ConversationMember(
                conversation_id=conversation_id,
                member_id=to_agent_id,
                member_type="agent",
                role="worker",
            ))
        msg = await create_message(
            s,
            conversation_id=conversation_id,
            sender_id=current_agent_id or "agent",
            sender_type="agent",
            content={"type": "text", "text": content},
            mentions=[to_agent_id],
        )
        reply = None
        if conn is not None:
            reply = await create_message(
                s,
                conversation_id=conversation_id,
                sender_id=to_agent_id,
                sender_type="agent",
                content={"type": "text", "text": ""},
            )
            msg_dict = message_to_dict(msg)
            reply_dict = message_to_dict(reply)
    if current_agent_id:
        animation_bus.beam(
            conversation_id=conversation_id,
            from_id=current_agent_id,
            to_id=to_agent_id,
            kind="message",
            label="tool message",
        )
    animation_bus.viz_event(
        conversation_id=conversation_id,
        kind="message",
        label=f"agent message: {current_agent_id or 'agent'} -> {to_agent_id}",
    )
    if conn is not None and reply is not None:
        from handlers.send_message import run_agent_reply
        from ws import event

        await conn.send(event("message_created", message=msg_dict))
        await conn.send(event("message_created", message=reply_dict))
        await run_agent_reply(conn, to_agent_id, reply.id, conversation_id, content)
        return json.dumps(
            {"ok": True, "messageId": msg.id, "replyMessageId": reply.id, "to": to_agent_id},
            ensure_ascii=False,
        )
    return json.dumps({"ok": True, "messageId": msg.id, "to": to_agent_id}, ensure_ascii=False)


async def _list_agents_tool(conversation_id: str = "", **kwargs: Any) -> str:
    from services.agent import list_agents

    Session = get_sessionmaker()
    async with Session() as s:
        agents = await list_agents(s)
        if conversation_id:
            members = (
                await s.scalars(
                    select(ConversationMember).where(
                        ConversationMember.conversation_id == conversation_id,
                        ConversationMember.member_type == "agent",
                    )
                )
            ).all()
            member_ids = {m.member_id for m in members}
            agents = [a for a in agents if a["id"] in member_ids]
    compact = [
        {
            "id": a["id"],
            "name": a["name"],
            "adapter_type": a["adapter_type"],
            "capabilities": a["capabilities"],
        }
        for a in agents
    ]
    return json.dumps({"ok": True, "agents": compact}, ensure_ascii=False)


_BUILTIN_TOOLS: list[dict[str, Any]] = [
    {
        "name": "create_artifact",
        "description": "Create a file artifact in the conversation. Use this to save your output as a persistent file (report, document, code file, config, etc.) that the user can preview and download.",
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["file", "code", "preview", "diff"],
                    "description": "Artifact kind: 'file' for generic files (reports, docs), 'code' for source code, 'preview' for HTML pages, 'diff' for code changes.",
                },
                "title": {"type": "string", "description": "Human-readable title for the artifact."},
                "mime_type": {"type": "string", "description": "MIME type, e.g. 'text/markdown', 'application/json', 'text/x-python'.", "default": "text/plain"},
                "file_name": {"type": "string", "description": "File name with extension, e.g. 'test_report.md', 'config.yml'.", "default": ""},
                "content": {"type": "string", "description": "The complete file content."},
            },
            "required": ["kind", "title", "content"],
        },
        "handler": _create_artifact_tool,
        "category": ToolCategory.FILE_IO,
    },
    {
        "name": "read_file",
        "description": "读取项目中的文件内容。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
            },
            "required": ["path"],
        },
        "handler": _read_file,
        "category": ToolCategory.FILE_IO,
    },
    {
        "name": "read_artifact",
        "description": "读取之前创建的产物（文件/文档/代码）。用 artifact_id 或 file_name 查找当前会话中的产物并返回完整内容。当你需要查看之前生成的文件时使用此工具。",
        "parameters": {
            "type": "object",
            "properties": {
                "artifact_id": {"type": "string", "description": "产物 ID（如果知道确切 ID）", "default": ""},
                "file_name": {"type": "string", "description": "产物文件名，如 'test_report.md'。在当前会话中查找匹配的产物。", "default": ""},
            },
        },
        "handler": _read_artifact,
        "category": ToolCategory.FILE_IO,
    },
    {
        "name": "write_file",
        "description": "写入或创建文件。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "文件内容"},
            },
            "required": ["path", "content"],
        },
        "handler": _write_file,
        "category": ToolCategory.FILE_IO,
    },
    {
        "name": "list_files",
        "description": "列出目录中的文件和子目录。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目录路径", "default": "."},
                "pattern": {"type": "string", "description": "正则过滤", "default": ""},
            },
        },
        "handler": _list_files,
        "category": ToolCategory.FILE_IO,
    },
    {
        "name": "web_search",
        "description": "搜索互联网获取实时信息。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
            },
            "required": ["query"],
        },
        "handler": _web_search,
        "category": ToolCategory.WEB,
    },
    {
        "name": "create_agent",
        "description": "Create a child Agent for a delegated role inside the current conversation.",
        "parameters": {
            "type": "object",
            "properties": {
                "role": {"type": "string", "description": "Role name, such as coder, researcher, reviewer."},
                "guidance": {"type": "string", "description": "Extra system guidance for the child agent."},
            },
            "required": ["role"],
        },
        "handler": _create_agent_tool,
        "category": ToolCategory.AGENT_COMM,
    },
    {
        "name": "send_message",
        "description": "Send a message to another Agent in the current conversation.",
        "parameters": {
            "type": "object",
            "properties": {
                "to_agent_id": {"type": "string", "description": "Target Agent id."},
                "content": {"type": "string", "description": "Message content."},
            },
            "required": ["to_agent_id", "content"],
        },
        "handler": _send_agent_message_tool,
        "category": ToolCategory.AGENT_COMM,
    },
    {
        "name": "list_agents",
        "description": "List Agents available in the current conversation.",
        "parameters": {"type": "object", "properties": {}},
        "handler": _list_agents_tool,
        "category": ToolCategory.AGENT_COMM,
    },
]


class ToolRegistry:
    """工具注册中心，管理工具定义和执行。

    优化:
    - 分类索引 (_by_category): O(1) 按类别查找
    - 依赖验证: register_batch() 自动检查依赖完整性
    - 延迟初始化: lazy_init 标记，减少启动开销
    """

    def __init__(self, project_root: str = "") -> None:
        self._tools: dict[str, Tool] = {}
        self._by_category: dict[ToolCategory, list[Tool]] = {}
        self.project_root = os.path.abspath(project_root) if project_root else ""
        self.runtime_context: dict[str, Any] = {}
        self._initialized: bool = False
        if self.project_root and self.project_root not in _ALLOWED_ROOTS:
            _ALLOWED_ROOTS.append(self.project_root)

    def initialize(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._register_builtins()

    def _register_builtins(self) -> None:
        for t in _BUILTIN_TOOLS:
            self.register(Tool(
                name=t["name"],
                description=t["description"],
                parameters=t["parameters"],
                handler=t["handler"],
                category=t.get("category", ToolCategory.CUSTOM),
                requires_confirmation=t.get("requires_confirmation", False),
                dependencies=t.get("dependencies", []),
            ))

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        self._by_category.setdefault(tool.category, []).append(tool)
        logger.debug("Tool registered: %s [%s]", tool.name, tool.category.value)

    def register_batch(self, tools: list[Tool]) -> list[str]:
        errors = []
        for tool in tools:
            for dep in tool.dependencies:
                if dep not in self._tools and not any(t.name == dep for t in tools):
                    errors.append(f"Tool '{tool.name}' depends on unknown tool '{dep}'")
        if errors:
            for err in errors:
                logger.warning(err)
        for tool in tools:
            self.register(tool)
        return errors

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def list_by_category(self, category: ToolCategory) -> list[Tool]:
        return self._by_category.get(category, [])

    def get_categories(self) -> list[ToolCategory]:
        cats = list(self._by_category.keys())
        cats.sort(key=lambda c: c.value)
        return cats

    def get_openai_schemas(self) -> list[dict[str, Any]]:
        schemas = []
        for t in self._tools.values():
            schemas.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            })
        return schemas

    def set_runtime_context(self, **context: Any) -> None:
        self.runtime_context = {k: v for k, v in context.items() if v is not None}

    def pop_pending_artifacts(self) -> list[dict[str, Any]]:
        """Retrieve and clear artifacts created by tool calls during a ReAct loop."""
        artifacts = self.runtime_context.pop("_artifacts", None)
        if isinstance(artifacts, list):
            return artifacts
        return []

    def get_openai_schemas_by_category(self, category: ToolCategory) -> list[dict[str, Any]]:
        schemas = []
        for t in self.list_by_category(category):
            schemas.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            })
        return schemas

    def to_react_prompt(self) -> str:
        if not self._tools:
            return ""
        lines = [
            "## 工具调用",
            "你可以调用以下工具来完成任务。当需要调用工具时，请严格按以下格式输出：",
            "",
        ]
        for t in self._tools.values():
            params = t.parameters.get("properties", {})
            param_desc = "; ".join(
                f"{k}: {v.get('description', v.get('type', ''))}"
                for k, v in params.items()
            )
            lines.append(f"- **{t.name}**: {t.description}")
            if param_desc:
                lines.append(f"  参数: {param_desc}")
            lines.append("")
        lines.append(
            '当需要调用工具时，请用如下格式回复：\n\n'
            '```tool_call\n'
            '{\n'
            '  "name": "工具名",\n'
            '  "arguments": {\n'
            '    "参数1": "值1"\n'
            '  }\n'
            '}\n'
            '```\n\n'
            '执行完工具获取结果后，继续分析结果并给出下一步行动或最终回复。'
        )
        return "\n".join(lines)

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: unknown tool: {name}"

        if self.project_root:
            arguments.setdefault("project_root", self.project_root)
        for key, value in self.runtime_context.items():
            arguments.setdefault(key, value)

        try:
            handler = tool.handler
            if asyncio.iscoroutinefunction(handler):
                result = await handler(**arguments)
            else:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, lambda: handler(**arguments))
            return str(result)
        except Exception as exc:
            logger.error("Tool %s failed: %s", name, exc)
            return f"Error executing {name}: {exc}"

    def tool_descriptions(self) -> str:
        return ", ".join(
            f"{t.name}({', '.join(t.parameters.get('properties', {}))})"
            for t in self._tools.values()
        )


_default_registry: ToolRegistry | None = None


def get_tool_registry(project_root: str = "") -> ToolRegistry:
    global _default_registry
    if project_root:
        registry = ToolRegistry(project_root=project_root)
        registry.initialize()
        return registry
    if _default_registry is None:
        _default_registry = ToolRegistry(project_root=project_root)
        _default_registry.initialize()
    return _default_registry
