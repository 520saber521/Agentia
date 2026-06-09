# Skill：新增一个 Agent Adapter

> 本 Skill 是 [new-feature.md](new-feature.md)（端到端新功能开发）的子技能。如果是全新 Feature 开发，请先阅读元技能了解完整流程。

## 使用场景

当需要接入新的外部模型、SDK、本地 Agent 进程或 OpenAI 兼容 endpoint 时使用本 Skill。典型目标包括 Claude、Codex、OpenCode、自定义企业模型、本地推理服务。

## 预读材料

按顺序阅读：

1. `server/adapters/base.py`：确认 `AgentAdapter`、chunk 类型和 `send()` 约定。
2. `server/adapters/mock.py`：最小可运行参考。
3. `server/adapters/__init__.py`：Adapter 注册方式。
4. `server/handlers/send_message.py`：BFF 如何消费 Adapter 流。
5. `ai-collab/rules/adapter.mdc`：必须遵守的硬规则。

## 输入信息

开始实现前必须确认：

- Adapter 名称，例如 `foo`。
- 上游协议：HTTP streaming、SSE、SDK async iterator、本地进程 stdout。
- 必要配置：`api_key`、`base_url`、`model`、`endpoint`。
- 能力枚举：只能从 `text`、`tool_use`、`vision`、`code`、`web_search`、`file` 中选择。
- 取消策略：如何中断上游请求或停止读取。

## 实施步骤

### 1. 建立文件

```text
server/adapters/<name>.py
server/tests/test_<name>_adapter.py
```

不要修改无关 Adapter，不要把实现写进 `main.py` 或 handler。

### 2. 实现 Adapter 类

最小骨架：

```python
from collections.abc import AsyncIterator
import asyncio

from .base import AgentAdapter, Chunk


class FooAdapter(AgentAdapter):
    name = "foo"

    def __init__(self, *, model: str, api_key: str, base_url: str | None = None) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url or "https://api.foo.example/v1"

    def capabilities(self) -> list[str]:
        return ["text"]

    async def send(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        artifacts_context: dict | None = None,
        cancel: asyncio.Event | None = None,
    ) -> AsyncIterator[Chunk]:
        if not self.api_key:
            yield {"type": "error", "code": "missing_api_key", "message": "缺少 API key"}
            return

        # 在这里调用上游流式接口。每次 yield 前检查 cancel。
        ...
```

关键要求：

- `send()` 必须流式 yield。
- 取消时 `return`，不得 raise。
- 错误时 yield error chunk。
- 不读数据库，不发 WebSocket。
- 不直接读取环境变量。

### 3. 注册到工厂

在 `server/adapters/__init__.py` 中注册，让 BFF 可以通过统一入口创建：

```python
from .foo import FooAdapter

ADAPTER_REGISTRY["foo"] = FooAdapter
```

如果项目当前使用函数式注册或工厂闭包，沿用已有模式，不新建第二套注册系统。

### 4. 接入配置

- 默认 Agent 需要出现在 Demo 中时，更新 `server/db/seed.py`。
- 自定义 Agent 场景优先通过数据库配置读取，不写死在代码里。
- 密钥应由服务端配置或用户保存的 secret 注入，不能返回给前端。

### 5. 编写测试

必须覆盖以下用例：

| 用例 | 验收 |
| --- | --- |
| 成功流式输出 | 至少 yield 一个文本 chunk，最后正常结束 |
| 取消 | cancel 被 set 后能尽快 return |
| 上游超时 | yield `timeout` 或等价稳定错误码 |
| 上游错误或限流 | yield `upstream_error`、`rate_limited` 等稳定错误码 |
| 配置缺失 | yield `missing_api_key` 或等价错误，不抛 KeyError |
| 注册表 | `build_adapter("<name>", ...)` 可创建实例 |
| 能力枚举 | `capabilities()` 非空且值合法 |

### 6. 运行验证

```powershell
cd D:\桌面\Agentia_v7\Agentia
python -m pytest -c server\pyproject.toml server\tests\test_<name>_adapter.py -v
```

如 Adapter 影响 fan-out 或 Orchestrator，还要运行相关 WS 或 handler 测试。

## 常见错误

- 在 Adapter 里直接 `os.environ["API_KEY"]`。
- 上游返回完整文本后一次性 yield。
- 用异常表达用户取消。
- 在 Adapter 中写 DB、创建 Artifact 或发送 WebSocket。
- 忘记注册，导致数据库里有 `adapter_type` 但运行时找不到实现。

## PR 自检

- [ ] 新 Adapter 文件已创建。
- [ ] 已注册到统一工厂。
- [ ] 配置由 BFF 注入，不读取环境变量。
- [ ] 成功、取消、超时、上游错误、配置缺失、注册表测试齐全。
- [ ] `capabilities()` 返回合法枚举。
- [ ] 如作为 Demo Agent 使用，seed 或配置说明已更新。
