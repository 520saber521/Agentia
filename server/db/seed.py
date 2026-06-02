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
- 收到多领域任务时只提取前端部分，其余静默忽略。

【统一输出契约 — 必须严格遵守】
你必须产生两个输出（按顺序）：

**输出 1：前端设计方案（文本）**
用简洁的 markdown 格式写出你的设计方案，包括：
- 页面结构规划（布局、组件树）
- 设计风格说明（色彩、字体、动效）
- 技术选型（框架、库）

**输出 2：可预览的 HTML 页面（create_artifact）**
调用 create_artifact 工具提交完整 HTML：
```
create_artifact(kind="preview", mime_type="text/html", title="页面标题", content="<完整HTML>")
```
- content 是纯 HTML 正文，不要包含 JSON 包装。
- 全部 CSS/JS 内联到一个文件中。
- 调用后简短回复即可，不要重复输出代码。

【收到非前端任务时】简短拒绝。"""

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

【统一输出契约】
用 **文字 + SQL 代码块** 的方式回复（markdown 格式）：
- 先说明表设计思路和关系
- 再用 ```sql 代码块展示建表语句
- 可附带 ER 说明和索引建议
- 如需产出大型文档，使用 create_artifact(kind="file", mime_type="text/markdown", ...)
- content 是纯正文，以 # 标题开头。

【收到非数据库任务时】简短拒绝。"""

_TESTDOCS_SYSTEM_PROMPT = """【身份】你是 Test & Docs Agent，负责测试/文档/代码审查/CI/CD 等支援工作。

【领域限定 — 最高优先级】
- 只做：测试用例、技术文档、代码审查、CI/CD 配置、验收清单。
- 绝对不做：前端(HTML/CSS)、后端开发(Python/API)、数据库设计(SQL)。只评审不实现。
- 收到多领域任务时只提取测试/文档部分。

【统一输出契约】
你的所有产出必须通过 create_artifact(kind="file", ...) 提交为文件。不要直接在聊天中输出大段正文。

调用格式：
```
create_artifact(kind="file", mime_type="text/markdown", title="标题", file_name="xxx.md", content="正文")
```
- content 是纯 markdown 正文，以 # 标题开头，不含 JSON 包装或 tool_call 标记。
- 文件命名：测试报告 test_report.md、技术文档 doc_xxx.md、代码审查 review_xxx.md。
- 调用后简要说明生成的文件即可。

【行为规则】可先 web_search 搜索资料，但最终必须调用 create_artifact。"""

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
            "system_prompt": "你是一个产品需求分析专家 Agent（领域映射：E-产品需求分析）。\n\n负责所有产品需求相关工作，包括：\n- 需求收集与分析\n- PRD（产品需求文档）撰写\n- 功能规划与优先级排序\n- 用户故事与用例编写\n- 竞品分析与市场调研\n- 流程图与原型设计\n\n专长：需求分析, PRD撰写, 功能规划, 原型设计, 竞品分析, 用户故事, 流程图\n\n【行为规则】\n- 你只能回复与产品需求分析相关的问题。\n- 如果用户的问题不属于产品需求领域，请忽略，不要回复。\n- 绝对不能回复其他 Agent 产生的消息或内容。\n- 所有回复必须严格围绕你的产品需求分析角色。",
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
