from __future__ import annotations

from claude_agent_sdk import ToolResultBlock

from adapters.claude_agent_sdk import (
    _ensure_claude_config_dir,
    _render_tool_result,
    _try_direct_search,
    _try_direct_glob,
    _try_direct_read,
)


def test_render_tool_result_from_sdk_block() -> None:
    block = ToolResultBlock(
        tool_use_id="toolu_1",
        content="web/src/components/MessageBubble.tsx\nweb/src/components/App.tsx",
    )

    rendered = _render_tool_result(block)

    assert "web/src/components/MessageBubble.tsx" in rendered
    assert "web/src/components/App.tsx" in rendered
    assert not rendered.startswith("\n```")


def test_render_tool_result_from_dict_block() -> None:
    block = {
        "type": "tool_result",
        "tool_use_id": "toolu_1",
        "content": [{"type": "text", "text": "web/src/components/AgentCreateDialog.tsx"}],
    }

    rendered = _render_tool_result(block)

    assert "web/src/components/AgentCreateDialog.tsx" in rendered


def test_render_tool_result_marks_errors() -> None:
    block = ToolResultBlock(
        tool_use_id="toolu_1",
        content="command failed",
        is_error=True,
    )

    rendered = _render_tool_result(block)

    assert rendered.startswith("\n[stderr]\n")
    assert "command failed" in rendered


def test_direct_glob_lists_matching_files(tmp_path) -> None:
    components = tmp_path / "web" / "src" / "components"
    nested = components / "nested"
    nested.mkdir(parents=True)
    (components / "MessageBubble.tsx").write_text("x", encoding="utf-8")
    (nested / "Card.tsx").write_text("x", encoding="utf-8")
    (components / "style.css").write_text("x", encoding="utf-8")

    rendered = _try_direct_glob(
        "用 Glob 工具列出 web/src/components/ 下的所有 .tsx 文件",
        str(tmp_path),
    )

    assert rendered is not None
    assert "web/src/components/MessageBubble.tsx" in rendered
    assert "web/src/components/nested/Card.tsx" in rendered
    assert "style.css" not in rendered


def test_direct_search_finds_project_usage(tmp_path) -> None:
    target = tmp_path / "server" / "adapters" / "__init__.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        '"claude_agent_sdk": ClaudeAgentSDKAdapter\n',
        encoding="utf-8",
    )
    ignored = tmp_path / ".agenthub" / "cache.txt"
    ignored.parent.mkdir()
    ignored.write_text("claude_agent_sdk", encoding="utf-8")

    rendered = _try_direct_search("搜索项目里哪里使用了 claude_agent_sdk", str(tmp_path))

    assert rendered is not None
    assert "server/adapters/__init__.py:1" in rendered
    assert ".agenthub" not in rendered


def test_direct_search_does_not_intercept_web_search(tmp_path) -> None:
    rendered = _try_direct_search(
        "请搜索 Claude Agent SDK 官方文档，并总结主要用途",
        str(tmp_path),
    )

    assert rendered is None


def test_direct_read_does_not_intercept_multi_tool_edit(tmp_path) -> None:
    rendered = _try_direct_read(
        "Use Write to create server/.agenthub/a.txt, then use Edit, then Read it.",
        str(tmp_path),
    )

    assert rendered is None


def test_ensure_claude_config_dir_is_workspace_local(tmp_path) -> None:
    (tmp_path / "server").mkdir()

    config_dir = _ensure_claude_config_dir(str(tmp_path))

    assert config_dir == str(tmp_path / "server" / ".agenthub" / "claude")
    assert (tmp_path / "server" / ".agenthub" / "claude").is_dir()


def test_direct_read_returns_numbered_prefix_and_summary(tmp_path) -> None:
    target = tmp_path / "server" / "adapters" / "claude_agent_sdk.py"
    target.parent.mkdir(parents=True)
    target.write_text("line a\nline b\nline c\n", encoding="utf-8")

    rendered = _try_direct_read(
        "请用 Read 工具读取 server/adapters/claude_agent_sdk.py 的前 2 行，并总结这个文件做什么",
        str(tmp_path),
    )

    assert rendered is not None
    assert "1: line a" in rendered
    assert "2: line b" in rendered
    assert "3: line c" not in rendered
    assert "总结：" in rendered
