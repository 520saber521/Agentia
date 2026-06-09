from __future__ import annotations

import json
from typing import Any, AsyncIterator

from sqlalchemy import select

from adapters.base import AgentAdapter, Chunk
from db.engine import get_sessionmaker
from db.models import ConversationMember, Message
from db.seed import DEFAULT_AGENT_ID, DEFAULT_CONV_ID, seed_defaults
from services.react_loop import ReActEngine
from services.spells import expand_spell
from services.tool_registry import Tool, ToolCategory, _web_search, get_tool_registry


class InvalidToolCallThenTextAdapter(AgentAdapter):
    name = "invalid_tool_call_then_text"

    def __init__(self) -> None:
        super().__init__({})
        self.calls = 0

    async def send(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        artifacts_context: dict[str, Any] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[Chunk]:
        self.calls += 1
        if self.calls == 1:
            yield {
                "type": "text",
                "delta": (
                    "```tool_call\n"
                    "{\"name\":\"create_artifact\",\"arguments\":{\"content\":\"# Doc\n"
                    "```bash\njmap -h\n```\n"
                    "tail\"}}\n"
                    "```"
                ),
            }
        else:
            yield {"type": "text", "delta": "# Java 内存管理\n\n完整文档正文。"}
        yield {"type": "done"}

    def capabilities(self) -> list[str]:
        return []


class DSMLToolCallThenTextAdapter(AgentAdapter):
    name = "dsml_tool_call_then_text"

    def __init__(self) -> None:
        super().__init__({})
        self.calls = 0

    async def send(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        artifacts_context: dict[str, Any] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[Chunk]:
        self.calls += 1
        if self.calls == 1:
            yield {
                "type": "text",
                "delta": (
                    "我先查看工作区。\n"
                    "<｜｜DSML｜｜tool_calls>\n"
                    "<｜｜DSML｜｜invoke name=\"list_files\">{\"path\":\".\"}</｜｜DSML｜｜invoke>\n"
                    "</｜｜DSML｜｜tool_calls>"
                ),
            }
        else:
            yield {"type": "text", "delta": "工作区已检查，继续生成完整项目。"}
        yield {"type": "done"}

    def capabilities(self) -> list[str]:
        return []


class NativeWebSearchArgsAdapter(AgentAdapter):
    name = "codex"

    def __init__(self) -> None:
        super().__init__({})
        self.calls = 0

    async def send(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        artifacts_context: dict[str, Any] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[Chunk]:
        self.calls += 1
        if self.calls == 1:
            yield {
                "type": "tool_call",
                "name": "web_search",
                "args": {"query": "Agentia web search regression"},
                "call_id": "call_web_search",
            }
            yield {"type": "done"}
            return
        yield {"type": "text", "delta": "web search worked"}
        yield {"type": "done"}

    def capabilities(self) -> list[str]:
        return ["text", "tool_use"]


class OpenAIToolHistoryAdapter(AgentAdapter):
    name = "codex"

    def __init__(self) -> None:
        super().__init__({})
        self.calls = 0
        self.second_call_messages: list[dict[str, Any]] = []

    async def send(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        artifacts_context: dict[str, Any] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[Chunk]:
        self.calls += 1
        if self.calls == 1:
            yield {
                "type": "tool_call",
                "name": "list_files",
                "args": {"path": "."},
                "call_id": "call_list_files",
            }
            yield {"type": "done"}
            return

        self.second_call_messages = list(messages)
        tool_index = next(
            (i for i, message in enumerate(messages) if message.get("role") == "tool"),
            None,
        )
        assert tool_index is not None
        assert tool_index > 0
        previous = messages[tool_index - 1]
        assert previous.get("role") == "assistant"
        assert previous.get("tool_calls")
        assert previous["tool_calls"][0]["id"] == messages[tool_index]["tool_call_id"]
        yield {"type": "text", "delta": "tool history is valid"}
        yield {"type": "done"}

    def capabilities(self) -> list[str]:
        return ["text", "tool_use"]


def test_expand_spell_map_reduce() -> None:
    expanded = expand_spell("/map-reduce: build a login flow")
    assert "map-reduce orchestration spell" in expanded
    assert "create_agent" in expanded
    assert "send_message" in expanded
    assert "build a login flow" in expanded


async def test_react_discards_invalid_structured_tool_call_without_leaking_json() -> None:
    registry = get_tool_registry(project_root=".")
    adapter = InvalidToolCallThenTextAdapter()
    engine = ReActEngine(registry=registry, max_steps=2)

    chunks = [
        chunk
        async for chunk in engine.run(
            adapter,
            [{"role": "user", "content": "生成一个介绍 Java 内存管理的文档"}],
        )
    ]
    text = "".join(str(chunk.get("delta", "")) for chunk in chunks if chunk.get("type") == "text")

    assert "tool_call" not in text
    assert "create_artifact" not in text
    assert "jmap -h" not in text
    assert "# Java 内存管理" in text
    assert adapter.calls == 2


async def test_react_parses_dsml_tool_call_and_continues_without_leaking_markup() -> None:
    registry = get_tool_registry(project_root=".")
    adapter = DSMLToolCallThenTextAdapter()
    engine = ReActEngine(registry=registry, max_steps=2)

    chunks = [
        chunk
        async for chunk in engine.run(
            adapter,
            [{"role": "user", "content": "查看 workspace 后继续生成项目"}],
        )
    ]
    text = "".join(str(chunk.get("delta", "")) for chunk in chunks if chunk.get("type") == "text")
    observations = [chunk for chunk in chunks if chunk.get("type") == "observation"]

    assert "DSML" not in text
    assert "tool_calls" not in text
    assert "工作区已检查" in text
    assert any(chunk.get("name") == "list_files" and chunk.get("status") == "done" for chunk in observations)
    assert adapter.calls == 2


async def test_react_injects_openai_assistant_tool_call_before_tool_result() -> None:
    registry = get_tool_registry(project_root=".")
    adapter = OpenAIToolHistoryAdapter()
    engine = ReActEngine(registry=registry, max_steps=2)

    chunks = [
        chunk
        async for chunk in engine.run(
            adapter,
            [{"role": "user", "content": "Inspect workspace and summarize."}],
            tools=registry.get_openai_schemas(),
        )
    ]
    text = "".join(str(chunk.get("delta", "")) for chunk in chunks if chunk.get("type") == "text")

    assert text == "tool history is valid"
    assert adapter.calls == 2
    assert any(message.get("role") == "tool" for message in adapter.second_call_messages)


async def test_native_tool_call_args_are_executed_as_arguments() -> None:
    captured: dict[str, Any] = {}

    async def fake_web_search(query: str, **kwargs: Any) -> str:
        captured["query"] = query
        return f"result for {query}"

    registry = get_tool_registry(project_root=".")
    registry.register(Tool(
        name="web_search",
        description="fake web search",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        handler=fake_web_search,
        category=ToolCategory.WEB,
    ))
    adapter = NativeWebSearchArgsAdapter()
    engine = ReActEngine(registry=registry, max_steps=2)

    chunks = [
        chunk
        async for chunk in engine.run(
            adapter,
            [{"role": "user", "content": "Search the web."}],
            tools=registry.get_openai_schemas(),
        )
    ]
    observations = [chunk for chunk in chunks if chunk.get("type") == "observation"]

    assert captured["query"] == "Agentia web search regression"
    assert not any("missing required arguments" in str(chunk.get("result", "")) for chunk in observations)
    assert any(chunk.get("arguments", {}).get("query") == "Agentia web search regression" for chunk in observations)
    assert adapter.calls == 2


async def test_web_search_falls_back_to_bing_when_duckduckgo_is_empty(monkeypatch) -> None:
    class FakeResponse:
        def __init__(self, status_code: int, text: str = "", data: dict[str, Any] | None = None) -> None:
            self.status_code = status_code
            self.text = text
            self._data = data or {}

        def json(self) -> dict[str, Any]:
            return self._data

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def get(self, url: str, **kwargs: Any) -> FakeResponse:
            if "api.duckduckgo.com" in url:
                return FakeResponse(200, data={"AbstractText": "", "RelatedTopics": []})
            if "bing.com/search" in url:
                return FakeResponse(200, text=(
                    '<li class="b_algo"><h2><a href="https://example.com/test-plan">'
                    'Microblogging Platform Test Plan</a></h2>'
                    '<p>Acceptance criteria and best practices for social platform testing.</p></li>'
                ))
            return FakeResponse(404)

        async def post(self, url: str, **kwargs: Any) -> FakeResponse:
            return FakeResponse(200, text="")

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    result = await _web_search("microblogging platform test plan acceptance criteria best practices")

    assert "搜索结果来源：Bing HTML" in result
    assert "Microblogging Platform Test Plan" in result
    assert "搜索服务暂时不可用" not in result


async def test_agent_comm_tools_create_and_message(db_env) -> None:
    await seed_defaults()
    registry = get_tool_registry(project_root=".")
    registry.set_runtime_context(
        conversation_id=DEFAULT_CONV_ID,
        current_agent_id=DEFAULT_AGENT_ID,
    )

    schemas = registry.get_openai_schemas()
    names = {schema["function"]["name"] for schema in schemas}
    assert {"create_agent", "send_message", "list_agents"} <= names

    created_raw = await registry.execute(
        "create_agent",
        {"role": "reviewer", "guidance": "Review implementation risks."},
    )
    created = json.loads(created_raw)
    assert created["ok"] is True
    child_id = created["agentId"]

    sent_raw = await registry.execute(
        "send_message",
        {"to_agent_id": child_id, "content": "Please review the task."},
    )
    sent = json.loads(sent_raw)
    assert sent["ok"] is True

    Session = get_sessionmaker()
    async with Session() as s:
        member = await s.get(ConversationMember, (DEFAULT_CONV_ID, child_id))
        assert member is not None
        msg = await s.scalar(select(Message).where(Message.id == sent["messageId"]))
        assert msg is not None
        assert msg.sender_id == DEFAULT_AGENT_ID
