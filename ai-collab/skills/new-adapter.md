# Skill: 新增一个 Agent Adapter

**When to use**：需要接入一个新的 AI Agent（Claude / Codex / OpenCode / 自建 / 任何 OpenAI 兼容 API）。

**Time budget**：1.5 ~ 3 h（不含调真 API 的环境/Token 准备时间）。

**Pre-reads**（按这个顺序看 5 分钟）

1. `server/adapters/base.py` — `AgentAdapter` ABC 与 `Chunk` 联合类型契约
2. `server/adapters/mock.py` — 最小可参考实现
3. `server/main.py` 里 `_handle_send_message` 的 `agent.send(...)` 调用现场（这是你的下游消费者）
4. `ai-collab/rules/adapter.mdc` — 不能怎么做

---

## Steps（给 AI 的执行清单）

### 1. 建文件

```
server/adapters/<name>.py
server/tests/test_<name>_adapter.py
```

### 2. 实现 `class <Name>Adapter(AgentAdapter)`

最小骨架：

```python
class FooAdapter(AgentAdapter):
    name = "foo"

    def __init__(self, *, model: str, api_key: str, base_url: str | None = None) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url or "https://api.foo.example/v1"

    def capabilities(self) -> list[str]:
        return ["text", "tool_use"]  # 与 base.py 中能力枚举对齐

    async def send(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        artifacts_context: dict | None = None,
        cancel: asyncio.Event | None = None,
    ) -> AsyncIterator[Chunk]:
        # 上游 httpx.AsyncClient 流式读
        # 注意：cancel.is_set() 时必须 return（不能 raise）
        ...
```

### 3. 把 Adapter 注册到工厂

在 `server/adapters/__init__.py`：

```python
from .foo import FooAdapter
ADAPTER_REGISTRY["foo"] = FooAdapter
```

### 4. 在 `db/seed.py` 加默认 Agent 实例（可选）

如果新 Adapter 需要默认 demo agent，比照 `agent_mock` 加一行 seed。

### 5. 写测试 — **必须覆盖以下 5 个点**

| 测试点 | 为什么必须 |
|---|---|
| Chunk 顺序：先若干 `text_delta`，最后恰好 1 个 `done`/`usage` | 上游 BFF 假设最后一个 chunk 决定"流结束" |
| 取消语义：set `cancel` 后 `send()` 必须在 100 ms 内 return | 否则 WS 取消会"卡在 outbound 队列" |
| 错误传播：API 5xx 时 yield `{type:"error", code, message}` 而不是 raise | 一旦 raise 会把整个 WS 连接拖垮 |
| capabilities 返回非空、且元素都在合法枚举内 | 前端 AgentPicker 会按它过滤 |
| 注册到 `ADAPTER_REGISTRY["<name>"]` 后 `build_adapter("<name>", ...)` 可工作 | 这是 BFF 唯一的入口 |

参考 `server/tests/test_mock_adapter.py` 作为骨架，复制即可。

### 6. 验收

```powershell
server/.venv/Scripts/python.exe -m pytest -c server/pyproject.toml server/tests/test_<name>_adapter.py -v
```

绿了 → 把 `server/README.md` 的"已接入 Adapter"列表也补上。

---

## 反模式 / 不能干的事

- ❌ **在 `send()` 里 `await asyncio.sleep()` 单纯模拟延迟**：会把 BFF 的取消语义破坏。Mock 想模拟延迟时用 `asyncio.wait_for(cancel.wait(), timeout=…)` 模式。
- ❌ **返回完整字符串而不是流式 yield**：会让"按字流式"的 UX 消失。如果上游 API 只给整段，至少要按 token / 标点切。
- ❌ **在 Adapter 里读写 DB**：DB 是 BFF 层的关注点，Adapter 必须无状态。

---

## 已知坑位

- httpx 流式响应在 Windows 下偶尔会"卡在最后一帧"，给 `httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=None))`。
- 真 API 的 SSE 帧里经常混 `data: [DONE]`，记得过滤再 yield。

---

## 落地清单（PR 自检）

- [ ] `adapters/<name>.py` 已建
- [ ] `__init__.py` 已注册
- [ ] `tests/test_<name>_adapter.py` 5 类用例齐 + 全绿
- [ ] `server/README.md` 已更新
- [ ] 跑了一次手工 smoke：浏览器选中该 Agent，能流式回复 + 能取消
