"""工具注册中心 — 管理工具定义、生成 JSON Schema、执行内置工具。

架构
====
``ToolRegistry`` 是 ReAct 循环的工具层，负责三件事：

1. **注册** — 内置工具注册到全局 registry，每个工具包含 name、description、parameters(JSON Schema)、handler
2. **Schema 生成** — 为原生 Function Calling 模型生成 ``tools`` 参数，直接传给 ``adapter.send(tools=...)``
3. **结构化提示词** — 为不支持原生 FC 的模型（如 DeepSeek）生成描述文本，嵌入 system prompt

内置工具
========
- ``read_file`` — 读取本地文件
- ``write_file`` — 写入/创建文件
- ``web_search`` — 搜索网页
- ``list_files`` — 列出目录内容

用法
====
  registry = ToolRegistry(project_root="D:/Agentia/Agentia")
  schema = registry.get_openai_schemas()
  prompt = registry.to_react_prompt()
  result = await registry.execute("read_file", {"path": "server/main.py"})
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger("agenthub.services.tool_registry")

# ---------------------------------------------------------------------------
# 工具描述数据结构
# ---------------------------------------------------------------------------


@dataclass
class Tool:
    """单个工具定义。"""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
    handler: Callable[..., Any]
    requires_confirmation: bool = False


# ---------------------------------------------------------------------------
# 内置工具 handler
# ---------------------------------------------------------------------------

# 安全路径白名单（限制文件操作范围）
_ALLOWED_ROOTS: list[str] = []


def _normalize_path(path: str, project_root: str = "") -> str | None:
    """检查并规范化路径，防止目录穿越。"""
    if not path:
        return None
    abs_path = os.path.abspath(os.path.join(project_root, path))
    allowed = _ALLOWED_ROOTS or [os.path.abspath(project_root)] if project_root else []
    if allowed and not any(abs_path.startswith(r) for r in allowed):
        return None
    return abs_path


async def _read_file(path: str, project_root: str = "", **kwargs: Any) -> str:
    """读取文件内容。"""
    safe = _normalize_path(path, project_root)
    if not safe:
        return "Error: path outside allowed directory"
    try:
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


async def _write_file(
    path: str,
    content: str,
    project_root: str = "",
    **kwargs: Any,
) -> str:
    """写入内容到文件。"""
    safe = _normalize_path(path, project_root)
    if not safe:
        return "Error: path outside allowed directory"
    try:
        os.makedirs(os.path.dirname(safe), exist_ok=True)
        loop = asyncio.get_running_loop()
        with open(safe, "w", encoding="utf-8") as f:
            await loop.run_in_executor(None, f.write, content)
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
    """列出目录内容。"""
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
    """搜索网页并返回摘要结果。"""
    try:
        import httpx
        # 使用本地 WebFetch 服务或公共搜索 API
        # 这里用简单的 DuckDuckGo 风格请求作为示例
        url = f"https://html.duckduckgo.com/html/"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, data={"q": query})
            # 提取搜索结果摘要
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
            return "(no search results found)"
    except ImportError:
        return "Error: httpx not available"
    except Exception as exc:
        return f"Error searching: {exc}"


# ---------------------------------------------------------------------------
# 内置工具定义
# ---------------------------------------------------------------------------

_BUILTIN_TOOLS: list[dict[str, Any]] = [
    {
        "name": "read_file",
        "description": "读取项目中的文件内容。适用于查看源代码、配置文件、文档等。返回文件全部文本内容。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径，相对于项目根目录或绝对路径。例如：server/main.py",
                },
            },
            "required": ["path"],
        },
        "handler": _read_file,
    },
    {
        "name": "write_file",
        "description": "写入或创建文件。内容已存在则覆盖。适用于生成代码、修复 bug、创建文档。注意：操作不可撤销。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径，相对于项目根目录。例如：src/utils/helper.py",
                },
                "content": {
                    "type": "string",
                    "description": "要写入的完整文件内容。",
                },
            },
            "required": ["path", "content"],
        },
        "handler": _write_file,
    },
    {
        "name": "list_files",
        "description": "列出目录中的文件和子目录。可用于查看项目结构或查找特定文件。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "目录路径，相对于项目根目录。默认当前目录。",
                    "default": ".",
                },
                "pattern": {
                    "type": "string",
                    "description": "可选的正则表达式过滤。例如：*.py 或 test_*",
                    "default": "",
                },
            },
        },
        "handler": _list_files,
    },
    {
        "name": "web_search",
        "description": "搜索互联网获取实时信息。适用于查找最新文档、技术方案、bug 解决方案、API 参考等。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索查询关键词。建议用中文或英文关键词。",
                },
            },
            "required": ["query"],
        },
        "handler": _web_search,
    },
]


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------


class ToolRegistry:
    """工具注册中心，管理工具定义和执行。"""

    def __init__(self, project_root: str = "") -> None:
        self._tools: dict[str, Tool] = {}
        self.project_root = os.path.abspath(project_root) if project_root else ""
        if self.project_root:
            _ALLOWED_ROOTS.append(self.project_root)
        self._register_builtins()

    def _register_builtins(self) -> None:
        for t in _BUILTIN_TOOLS:
            self.register(
                Tool(
                    name=t["name"],
                    description=t["description"],
                    parameters=t["parameters"],
                    handler=t["handler"],
                    requires_confirmation=t.get("requires_confirmation", False),
                )
            )

    def register(self, tool: Tool) -> None:
        """注册一个工具。同名工具会被覆盖。"""
        self._tools[tool.name] = tool
        logger.debug("Tool registered: %s", tool.name)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())

    # ------------------------------------------------------------------
    # Schema 输出
    # ------------------------------------------------------------------

    def get_openai_schemas(self) -> list[dict[str, Any]]:
        """生成 OpenAI/Anthropic 格式的 tools 参数。"""
        schemas = []
        for t in self._tools.values():
            schema: dict[str, Any] = {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            schemas.append(schema)
        return schemas

    def to_react_prompt(self) -> str:
        """为不支持原生 FC 的模型（DeepSeek 等）生成结构化提示词。"""
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

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> str:
        """执行工具，返回结果文本。"""
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: unknown tool: {name}"

        # 注入 project_root
        if self.project_root:
            arguments.setdefault("project_root", self.project_root)

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
        """生成简洁的工具列表文本（用于调试/日志）。"""
        return ", ".join(
            f"{t.name}({', '.join(t.parameters.get('properties', {}))})"
            for t in self._tools.values()
        )


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

_default_registry: ToolRegistry | None = None


def get_tool_registry(project_root: str = "") -> ToolRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = ToolRegistry(project_root=project_root)
    return _default_registry
