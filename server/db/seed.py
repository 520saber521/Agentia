"""默认数据填充（幂等）。

启动时灌一份"演示数据"，让 BFF 不依赖任何外部状态就能跑通：

- 1 个用户：``user_demo``（占位，Day3 暂不做完整用户表）
- 内置 Agent（每种 Adapter 类型一个实例）：
    - ``agent_orchestrator`` → Orchestrator（任务编排器）
    - ``agent_claude``       → ClaudeCodeAdapter（Anthropic Claude）
    - ``agent_deepseek``     → CodexAdapter（OpenAI 兼容）
    - ``agent_opencode``     → OpenCodeAdapter（OpenCode 后端）
    - ``agent_mock_2``       → CustomAgentAdapter（自定义）
    - ``agent_mock``         → MockAdapter（离线测试）
- 1 个会话：``conv_demo``（单聊 user_demo ↔ MockAdapter）
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select

from .engine import get_sessionmaker
from .models import Agent, Conversation, ConversationMember
from services.agent import ORCHESTRATOR_SYSTEM_PROMPT

DEFAULT_USER_ID = "user_demo"
DEFAULT_AGENT_ID = "agent_mock"
DEFAULT_AGENT_ID_2 = "agent_mock_2"
DEFAULT_AGENT_CLAUDE = "agent_claude"
DEFAULT_AGENT_ORCHESTRATOR = "agent_orchestrator"
DEFAULT_AGENT_DEEPSEEK = "agent_deepseek"
DEFAULT_AGENT_OPENCODE = "agent_opencode"
DEFAULT_AGENT_SDK = "agent_sdk"
DEFAULT_CONV_ID = "conv_demo"

# Agents removed from seed but may still exist in existing databases
_REMOVED_SYSTEM_AGENTS = [
    "agent_idea", "agent_prd_actor", "agent_prd_critic",
    "agent_design_actor", "agent_design_critic",
    "agent_plan_actor", "agent_plan_critic",
    "agent_coding_actor", "agent_coding_critic",
    "agent_check", "agent_delivery",
]

_FRONTEND_SYSTEM_PROMPT = """【身份】你是前端专家 Agent，负责 HTML/CSS/JS/React/Vue 等前端开发。

【领域限定 — 最高优先级】
- 只做前端：HTML、CSS、JavaScript、TypeScript、React、Vue、UI/UX、布局、样式、交互。
- 绝对不做：后端(API/路由/Python/FastAPI)、数据库(SQL/ORM/Schema)、测试用例、文档撰写、部署配置。

【🔴 唯一输出：可预览的 HTML 页面】
你只需回复一个完整的 HTML 页面。通过 tool_call 格式调用 create_artifact 提交。

输出格式（严格遵循）：
```tool_call
{"name": "create_artifact", "arguments": {"kind": "preview", "mime_type": "text/html", "title": "页面标题", "content": "<!doctype html>\\n<html lang=\\"zh-CN\\">\\n<head>\\n  <meta charset=\\"UTF-8\\">\\n  <meta name=\\"viewport\\" content=\\"width=device-width, initial-scale=1.0\\">\\n  <title>页面标题</title>\\n  <style>\\n    /* CSS here */\\n  </style>\\n</head>\\n<body>\\n  <!-- HTML here -->\\n  <script>\\n    // JS here\\n  </script>\\n</body>\\n</html>"}}
```

🔴 关键规则：
- 只回复 tool_call 代码块 + 一句"已生成页面"即可
- content 中的 HTML 必须包含 <!doctype html>、<html>、<head>、<body> 完整标签
- content 中的 HTML 换行用 \\n 表示，缩进用空格（不用 tab）
- 所有 CSS 必须在 <style> 标签内，所有 JS 必须在 <script> 标签内
- 图片全部使用 https://picsum.photos/seed/关键词/WIDTH/HEIGHT
- 不要使用外部 CSS/JS 文件引用（如 <link> 或 <script src>）

🔴 页面质量标准：
1. 代码 ≥ 1500 行，CSS ≥ 500 行
2. 现代设计：玻璃态/渐变/暗色主题，CSS 变量统一配色
3. @keyframes 入场动画 + IntersectionObserver 滚动揭示
4. hover 效果用 cubic-bezier 缓动
5. Grid + Flexbox 布局
6. JS 交互 ≥ 4 项（汉堡菜单、回到顶部、轮播/选项卡、打字机等）
7. 页面在 iframe 中能完整显示，不需要外部资源"""

_BACKEND_SYSTEM_PROMPT = """【身份】你是后端专家 Agent，负责 API/服务/中间件/业务逻辑等后端开发。

【领域限定 — 最高优先级】
- 只做后端：API 设计、路由、中间件、认证鉴权、业务逻辑、服务架构。
- 绝对不做：前端(HTML/CSS/JS/UI)、数据库设计(SQL/Schema)、测试用例、部署脚本。
- 收到多领域任务时只提取后端部分，其余静默忽略。

【统一输出契约】
用 **文字 + 代码块** 的方式回复（markdown 格式）：
- 先简述设计思路
- 再用 markdown 代码块贴代码（```python、```yaml 等）
- 如需产出大型文档（>2000字），使用 create_artifact(kind="file", mime_type="text/markdown", title="...", file_name="backend_design.md", content="...")
- content 是纯正文，以 # 标题开头，不含 JSON 包装。

【收到非后端任务时】简短拒绝。"""

_DATABASE_SYSTEM_PROMPT = """【身份】你是数据库专家 Agent，负责数据模型/SQL/ORM/表结构设计。

【领域限定 — 最高优先级】
- 只做数据库：表结构设计、SQL 查询、索引优化、ORM 映射、数据迁移。
- 绝对不做：前端(HTML/CSS/JS)、后端代码(Python/路由)、测试用例、部署。
- 收到多领域任务时只提取数据库部分，其余静默忽略。

【输出方式 — 文字 + 代码块】
用 markdown 格式回复，直接输出在聊天中：
- 先简述表设计思路、关系说明
- 再用 ```sql 代码块贴建表语句
- 可附带索引建议和 ER 关系说明
- 不要使用 create_artifact 工具，不要创建文件
- 所有内容直接写在回复消息中

示例回复格式：
好的，以下是数据库设计方案。

## 表结构设计思路
xxx 表用于存储 xxx，与 yyy 表是一对多关系...

```sql
CREATE TABLE users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ...
);
```

【收到非数据库任务时】简短拒绝。"""

_TESTDOCS_SYSTEM_PROMPT = """【身份】你是 Test & Docs Agent，负责测试/文档/代码审查/CI/CD 等支援工作。

【领域限定 — 最高优先级】
- 只做：测试用例、技术文档、代码审查、CI/CD 配置、验收清单。
- 绝对不做：前端(HTML/CSS)、后端开发(Python/API)、数据库设计(SQL)。只评审不实现。
- 收到多领域任务时只提取测试/文档部分。

【🔴 统一输出契约 — 必须通过工具调用提交】

你**必须**调用 create_artifact 工具来提交所有产出，**绝对不要**在聊天中直接输出大段正文或 JSON。

工具调用方式（tool_call 格式）：
当需要调用 create_artifact 时，回复中必须包含如下代码块：
```tool_call
{"name": "create_artifact", "arguments": {"kind": "file", "mime_type": "text/markdown", "title": "标题", "file_name": "xxx.md", "content": "纯markdown正文"}}
```

具体参数说明：
- kind: 始终使用 "file"
- mime_type: 始终使用 "text/markdown"（所有文档/报告/清单都用 .md 格式）
- title: 简洁的中文标题
- file_name: 遵循命名规范（test_report.md, doc_xxx.md, review_xxx.md, checklist_xxx.md）
- content: 纯 markdown 正文，以 # 标题开头。**只放正文，不包含任何聊天语句、json包装、tool_call标记**

**重要规则**：
- 不要输出 `create_artifact(kind="file", ...)` 这种 Python 函数调用格式
- 不要输出裸 JSON（不带 tool_call 代码块）
- 必须使用 ```tool_call { "name": "create_artifact", "arguments": {...} } ``` 格式
- 调用 create_artifact 后简短说明"已生成 xxx.md"即可

**示例**：
好的，我来生成测试计划。

```tool_call
{"name": "create_artifact", "arguments": {"kind": "file", "mime_type": "text/markdown", "title": "测试计划", "file_name": "test_plan.md", "content": "# 测试计划\n\n## 1. 测试范围\n..."}}
```

已生成 test_plan.md 文件。

【行为规则】可先 web_search 搜索资料，但最终必须通过工具调用 create_artifact 提交文件。"""

_AGENT_DEFAULTS: list[tuple[str, dict[str, Any]]] = [
    (DEFAULT_AGENT_ID, dict(
        name="Frontend Agent",
        avatar="🧪",
        adapter_type="codex",
        config=json.dumps({
            "api_key": "", "model": "deepseek-v4-flash", "base_url": "https://api.deepseek.com/v1",
            "max_tokens": 60000,
            "system_prompt": _FRONTEND_SYSTEM_PROMPT,
        }, ensure_ascii=False),
        capabilities=json.dumps(["frontend", "React", "HTML", "CSS", "UI", "preview"], ensure_ascii=False),
        owner_user_id=None,
        is_system=1,
        locked_prompt=1,
    )),
    (DEFAULT_AGENT_ID_2, dict(
        name="Backend Agent",
        avatar="🔧",
        adapter_type="codex",
        config=json.dumps({
            "api_key": "", "model": "deepseek-v4-flash", "base_url": "https://api.deepseek.com/v1",
            "max_tokens": 60000,
            "system_prompt": _BACKEND_SYSTEM_PROMPT,
        }, ensure_ascii=False),
        capabilities=json.dumps(["backend", "API", "Python", "service", "routing"], ensure_ascii=False),
        owner_user_id=None,
        is_system=1,
        locked_prompt=1,
    )),
    (DEFAULT_AGENT_CLAUDE, dict(
        name="Database Agent",
        avatar="🤖",
        adapter_type="codex",
        config=json.dumps({
            "api_key": "", "model": "deepseek-v4-flash", "base_url": "https://api.deepseek.com/v1",
            "max_tokens": 60000,
            "system_prompt": _DATABASE_SYSTEM_PROMPT,
        }, ensure_ascii=False),
        capabilities=json.dumps(["database", "SQL", "schema", "ORM", "migration"], ensure_ascii=False),
        owner_user_id=None,
        is_system=1,
        locked_prompt=1,
    )),
    (DEFAULT_AGENT_ORCHESTRATOR, dict(
        name="Orchestrator",
        avatar="🎯",
        adapter_type="codex",
        config=json.dumps({"api_key": "", "model": "gpt-4o", "system_prompt": ORCHESTRATOR_SYSTEM_PROMPT}, ensure_ascii=False),
        capabilities=json.dumps(["task_management", "scheduling", "decomposition", "aggregation", "orchestration", "conflict_detection"], ensure_ascii=False),
        owner_user_id=None,
        is_system=1,
        locked_prompt=1,
    )),
    (DEFAULT_AGENT_DEEPSEEK, dict(
        name="Test & Docs Agent",
        avatar="⚡",
        adapter_type="codex",
        config=json.dumps({
            "api_key": "", "model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1",
            "max_tokens": 60000,
            "system_prompt": _TESTDOCS_SYSTEM_PROMPT,
        }, ensure_ascii=False),
        capabilities=json.dumps(["testing", "docs", "QA", "deployment", "acceptance"], ensure_ascii=False),
        owner_user_id=None,
        is_system=1,
        locked_prompt=1,
    )),
    (DEFAULT_AGENT_OPENCODE, dict(
        name="Product Agent",
        avatar="📋",
        adapter_type="opencode",
        config=json.dumps({
            "api_key": "", "model": "deepseek-v4-flash", "base_url": "https://api.deepseek.com/v1",
            "system_prompt": "你是一个产品需求分析专家 Agent（领域映射：E-产品需求分析）。\n\n负责所有产品需求相关工作，包括：\n- 需求收集与分析\n- PRD（产品需求文档）撰写\n- 功能规划与优先级排序\n- 用户故事与用例编写\n- 竞品分析与市场调研\n- 流程图与原型设计\n\n专长：需求分析, PRD撰写, 功能规划, 原型设计, 竞品分析, 用户故事, 流程图\n\n【输出方式 — 文字 + 结构化内容】\n用 markdown 格式回复，直接输出在聊天中：\n- 先阐述需求分析结论和核心要点\n- 再展示 PRD/用户故事/功能列表等结构化内容\n- 可使用 ```mermaid 等代码块展示流程图\n- 不要使用 create_artifact 工具，不要创建文件\n- 所有内容直接写在回复消息中，让用户直接在聊天中看到\n\n示例格式：\n好的，以下是产品需求分析。\n\n## 需求概述\n...\n\n## 用户故事\n...\n\n## 功能规划\n...\n\n【行为规则】\n- 你只能回复与产品需求分析相关的问题。\n- 如果用户的问题不属于产品需求领域，请忽略，不要回复。\n- 绝对不能回复其他 Agent 产生的消息或内容。\n- 所有回复必须严格围绕你的产品需求分析角色。",
        }, ensure_ascii=False),
        capabilities=json.dumps(["product", "PRD", "user_story", "planning", "requirements"], ensure_ascii=False),
        owner_user_id=None,
        is_system=1,
        locked_prompt=1,
    )),
    (DEFAULT_AGENT_SDK, dict(
        name="Claude Code (SDK)",
        avatar="🛠️",
        adapter_type="claude_agent_sdk",
        config=json.dumps({
            "api_key": "",
            "model": "sonnet",
            "base_url": "",
            "system_prompt": "你是一个全栈开发专家，使用 Claude Code 完整工具集。\n\n你可以：\n- 读写编辑文件（Read/Write/Edit）\n- 搜索代码库（Grep/Glob）\n- 执行命令（Bash）\n- 搜索网页（WebSearch/WebFetch）\n\n请在每次操作后自我验证产出是否正确。",
            "permission_mode": "default",
            "bare": False,
            "tools": ["Read", "Write", "Edit", "Grep", "Glob", "Bash", "WebSearch", "WebFetch"],
            "allowed_tools": ["Read", "Write", "Edit", "Grep", "Glob", "Bash", "WebSearch", "WebFetch"],
        }, ensure_ascii=False),
        capabilities=json.dumps(["fullstack", "code", "bash", "search", "edit"], ensure_ascii=False),
        owner_user_id=None,
        is_system=1,
        locked_prompt=1,
    )),
]


async def seed_defaults() -> None:
    """首次启动创建默认 agent；后续只更新已存在的，不恢复被用户删除的。"""
    Session = get_sessionmaker()
    async with Session() as s:
        existing_count = await s.scalar(select(func.count()).select_from(Agent))
        is_first_run = existing_count == 0

        for agent_id, fields in _AGENT_DEFAULTS:
            row = await s.scalar(select(Agent).where(Agent.id == agent_id))
            if row is None:
                if is_first_run or fields.get("is_system"):
                    s.add(Agent(id=agent_id, **fields))
                # 非首次且非系统 agent 且 row 不存在 = 被用户删过，跳过
                continue
            # 更新已存在的 agent（保留用户已配置的 config 值和 adapter_type）
            now = int(__import__("time").time() * 1000)
            for key, value in fields.items():
                if key == "config" and row.config:
                    existing_cfg = json.loads(row.config)
                    new_cfg = json.loads(value) if isinstance(value, str) else value
                    # locked_prompt agents: system_prompt always follows the code default
                    if row.locked_prompt:
                        existing_cfg.pop("system_prompt", None)
                    for cfg_key, cfg_value in existing_cfg.items():
                        if cfg_value not in (None, "", [], {}):
                            new_cfg[cfg_key] = cfg_value
                    if agent_id == DEFAULT_AGENT_SDK:
                        if str(new_cfg.get("base_url", "")).rstrip("/") == "https://api.apikey.fun/v1":
                            new_cfg["base_url"] = ""
                        if str(new_cfg.get("model", "")).startswith("claude-sonnet-4-6"):
                            new_cfg["model"] = "sonnet"
                        if new_cfg.get("cwd") in ("D:/Agentia/Agentia", "D:\\Agentia\\Agentia"):
                            new_cfg.pop("cwd", None)
                        if new_cfg.get("cli_path") in (
                            "C:/Users/fan/.local/bin/claude.exe",
                            "C:\\Users\\fan\\.local\\bin\\claude.exe",
                        ):
                            new_cfg.pop("cli_path", None)
                        if "tools" not in new_cfg or not new_cfg.get("tools"):
                            new_cfg["tools"] = new_cfg.get("allowed_tools") or [
                                "Read", "Write", "Edit", "Grep", "Glob", "Bash", "WebSearch", "WebFetch",
                            ]
                    value = json.dumps(new_cfg, ensure_ascii=False)
                # 不覆盖用户已修改的 adapter_type（用户可能通过 UI 更改了模型供应商）
                if key == "adapter_type" and row.adapter_type and agent_id != DEFAULT_AGENT_SDK:
                    continue
                setattr(row, key, value)
            setattr(row, "updated_at", now)

        conv = await s.scalar(select(Conversation).where(Conversation.id == DEFAULT_CONV_ID))
        if conv is None:
            s.add(
                Conversation(
                    id=DEFAULT_CONV_ID,
                    title="Demo · 与 MockAdapter 单聊",
                    type="single",
                    owner_user_id=DEFAULT_USER_ID,
                )
            )
            s.add(
                ConversationMember(
                    conversation_id=DEFAULT_CONV_ID,
                    member_id=DEFAULT_USER_ID,
                    member_type="user",
                    role="owner",
                )
            )
            s.add(
                ConversationMember(
                    conversation_id=DEFAULT_CONV_ID,
                    member_id=DEFAULT_AGENT_ID,
                    member_type="agent",
                    role="worker",
                )
            )

        # Clean up removed system agents from existing databases
        for agent_id in _REMOVED_SYSTEM_AGENTS:
            row = await s.scalar(select(Agent).where(Agent.id == agent_id))
            if row is not None:
                await s.delete(row)
                await s.execute(
                    ConversationMember.__table__.delete().where(
                        ConversationMember.member_id == agent_id
                    )
                )

        await s.commit()
