"""MockAdapter —— 离线固定回复，仅用于 W1 链路打通。

特点：

- 不调任何外部 API，完全可在 CI / 离线环境下运行。
- 按"英文词 / 中文字 / 空白 / 标点"切片，模拟真实 LLM 的流式 token。
- ``delay_ms`` 可控每片之间的睡眠时长，便于演示和压测。
- 对外部 ``asyncio.CancelledError`` 透传，配合 BFF 的取消机制。
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, AsyncIterator, List, Optional

from .base import AgentAdapter, Chunk

DEFAULT_REPLY = (
    "Hello! I am the AgentHub MockAdapter.\n"
    "I stream a fixed reply so you can verify the chain end-to-end "
    "before any real LLM API is wired in.\n"
    "你刚才说：{echo}"
)

# 简易 tokenizer：英文 / 数字成串，空白单独，CJK 单字，其它按字符。
_TOKEN_RE = re.compile(r"[A-Za-z]+|[0-9]+|\s+|[\u4e00-\u9fff]|.", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    return [tok for tok in _TOKEN_RE.findall(text or "") if tok]


def _last_user_text(messages: List[dict[str, Any]] | None) -> str:
    """从 ``messages`` 里捞最后一条 user 消息的文本内容。"""
    for m in reversed(messages or []):
        if m.get("role") == "user":
            c = m.get("content")
            return c if isinstance(c, str) else str(c)
    return ""


def _html_artifact_reply(echo: str, role: str) -> str:
    page_title = "AgentHub Generated Page"
    if "登录" in echo or "login" in echo.lower():
        page_title = "登录注册 Web 应用"
    elif "商品" in echo or "order" in echo.lower():
        page_title = "商品订单 Web 应用"
    return f"""【{role}】我会把这个需求落成可预览 HTML 产物，并给出分工建议。

## Agent 分工
- 产品/交互 Agent：明确页面信息架构、主要用户路径和验收标准。
- 前端 Agent：实现 HTML/CSS/JS 单文件可运行页面。
- 后端 Agent：定义 API 契约、数据模型和错误码。
- 测试 Agent：补充冒烟测试、表单校验和关键路径用例。

## 可落地 HTML
```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{page_title}</title>
  <style>
    :root {{ color-scheme: dark; font-family: Georgia, 'Microsoft YaHei', serif; }}
    body {{ margin: 0; min-height: 100vh; background: radial-gradient(circle at 20% 10%, #264b73, transparent 35%), linear-gradient(135deg, #08111f, #142238); color: #eef7ff; }}
    .shell {{ max-width: 1100px; margin: 0 auto; padding: 48px 24px; }}
    .hero {{ display: grid; gap: 22px; grid-template-columns: 1.1fr .9fr; align-items: center; }}
    .badge {{ display: inline-flex; border: 1px solid #79d6ff55; color: #9be4ff; border-radius: 999px; padding: 6px 12px; font-size: 12px; letter-spacing: .16em; }}
    h1 {{ font-size: clamp(38px, 7vw, 76px); line-height: .92; margin: 18px 0; }}
    p {{ color: #b9c8d9; font-size: 17px; line-height: 1.8; }}
    .panel {{ border: 1px solid #ffffff1f; border-radius: 28px; background: #ffffff10; backdrop-filter: blur(18px); padding: 24px; box-shadow: 0 24px 80px #0008; }}
    input, button {{ width: 100%; box-sizing: border-box; border-radius: 14px; border: 1px solid #ffffff24; padding: 14px 16px; margin-top: 12px; background: #08111fcc; color: #fff; }}
    button {{ background: linear-gradient(135deg, #6be1ff, #8cffb5); color: #07111f; font-weight: 800; cursor: pointer; }}
    .cards {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-top: 28px; }}
    .card {{ border: 1px solid #ffffff18; border-radius: 22px; padding: 18px; background: #ffffff0c; }}
    @media (max-width: 820px) {{ .hero, .cards {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main class="shell">
    <section class="hero">
      <div>
        <span class="badge">AGENT GENERATED</span>
        <h1>{page_title}</h1>
        <p>这是根据用户需求生成的可运行网页原型，覆盖登录注册、商品列表、订单提交等核心路径，可继续在 Monaco 中编辑并保存为新版本。</p>
      </div>
      <form class="panel" onsubmit="event.preventDefault(); alert('提交成功，订单已进入待处理状态');">
        <h2>快速开始</h2>
        <input placeholder="邮箱 / 用户名" required />
        <input placeholder="密码" type="password" required />
        <button>登录并提交示例订单</button>
      </form>
    </section>
    <section class="cards">
      <article class="card"><h3>用户账户</h3><p>登录、注册、表单校验、错误提示。</p></article>
      <article class="card"><h3>商品列表</h3><p>商品卡片、价格、库存和加入订单。</p></article>
      <article class="card"><h3>订单提交</h3><p>确认信息、提交状态、成功反馈。</p></article>
    </section>
  </main>
</body>
</html>
```

## API 契约
```json
{{"POST /api/auth/login":"登录","GET /api/products":"商品列表","POST /api/orders":"提交订单"}}
```
"""


class MockAdapter(AgentAdapter):
    """W1 用 Mock：固定模板 + 把最近 user 文本回灌进 ``{echo}``。"""

    name = "mock"

    def __init__(self, config: Optional[dict[str, Any]] = None) -> None:
        super().__init__(config)
        self.delay_ms: int = int(self.config.get("delay_ms", 20))
        self.reply_template: str = str(self.config.get("reply", DEFAULT_REPLY))
        self.role: str = str(self.config.get("role", "通用助手"))

    async def send(
        self,
        messages: List[dict[str, Any]],
        *,
        tools: Optional[List[dict[str, Any]]] = None,  # noqa: ARG002
        artifacts_context: Optional[dict[str, Any]] = None,  # noqa: ARG002
        stream: bool = True,
    ) -> AsyncIterator[Chunk]:
        echo = _last_user_text(messages) or "<empty>"
        lower_echo = echo.lower()
        if any(keyword in lower_echo for keyword in ["html", "网页", "页面", "landing", "web app", "website"]):
            full = _html_artifact_reply(echo, self.role)
        else:
            full = self.reply_template.format(echo=echo)

        tokens = _tokenize(full) if stream else [full]
        delay = max(0.0, self.delay_ms / 1000.0)

        input_tokens = sum(
            len(_tokenize(str(m.get("content", "")))) for m in (messages or [])
        )
        output_tokens = 0

        for tok in tokens:
            yield {"type": "text", "delta": tok}
            output_tokens += 1
            if delay:
                # 这里 sleep 是取消窗口；asyncio.CancelledError 透传给上层。
                await asyncio.sleep(delay)

        yield {
            "type": "usage",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        yield {"type": "done"}

    def capabilities(self) -> List[str]:
        return ["text", "mock"]
