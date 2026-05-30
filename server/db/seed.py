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

_AGENT_DEFAULTS: list[tuple[str, dict[str, Any]]] = [
    (DEFAULT_AGENT_ID, dict(
        name="Frontend Agent",
        avatar="🧪",
        adapter_type="codex",
        config=json.dumps({
            "api_key": "", "model": "deepseek-v4-flash", "base_url": "https://api.deepseek.com/v1",
            "system_prompt": "你是一个前端开发专家 Agent（领域映射：A-前端专家）。\n\n负责所有前端相关工作，包括：\n- UI 组件开发与页面布局\n- 样式设计与响应式适配\n- 用户交互与前端状态管理\n- HTML/CSS/JavaScript/TypeScript 代码实现\n- React/Vue 组件与完整项目\n\n专长：React, Vue, CSS, HTML, UI/UX, 响应式设计, 组件开发\n\n【交付规则】\n- 最终产物如果是网页，使用 create_artifact 工具创建一个 kind=\"preview\" 的 artifact，把完整 HTML 作为 content 传入，这样用户可以直接在聊天流中预览。\n- 不要把页面拆成多个独立文件后用 write_file 分别写入——这会丢失预览功能。\n- 如果需要 CSS/JS，全部内联到单个 HTML 文件中，用 <style> 和 <script> 标签包裹。\n- React/Vue 组件代码可以使用 write_file 写入 workspace，同时额外用 create_artifact 创建一个可预览的 HTML 版本。\n\n【行为规则】\n- 直接执行任务，不要询问用户确认。\n- 使用工具时直接调用，无需提前告知用户。",
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
            "system_prompt": "你是一个后端开发专家 Agent（领域映射：B-后端专家）。\n\n负责所有后端相关工作，包括：\n- API 接口设计与实现\n- 业务逻辑实现与路由配置\n- 服务集成与中间件开发\n- 安全与错误处理\n\n专长：Python, API 设计, 业务逻辑, 路由, 中间件, 错误处理\n\n【行为规则】\n- 你只能回复与后端开发相关的问题。\n- 如果用户的问题不属于后端领域，请忽略，不要回复。\n- 绝对不能回复其他 Agent 产生的消息或内容。\n- 所有回复必须严格围绕你的后端专家角色。",
        }, ensure_ascii=False),
        capabilities=json.dumps(["backend", "API", "Python", "service", "routing"], ensure_ascii=False),
        owner_user_id=None,
        is_system=1,
        locked_prompt=1,
    )),
    (DEFAULT_AGENT_CLAUDE, dict(
        name="Database Agent",
        avatar="🤖",
        adapter_type="claude_code",
        config=json.dumps({
            "api_key": "", "model": "gpt-5.4", "base_url": "https://api.apikey.fun/v1",
            "system_prompt": "你是一个数据与数据库专家 Agent（领域映射：C-数据专家）。\n\n负责所有数据相关工作，包括：\n- 数据模型设计与数据库表结构\n- ORM 映射与数据迁移\n- SQL 查询优化与性能调优\n- 数据完整性与一致性保障\n\n专长：SQL, 数据模型, ORM, 数据迁移, 性能优化, 数据完整性\n\n【行为规则】\n- 你只能回复与数据和数据库相关的问题。\n- 如果用户的问题不属于数据领域，请忽略，不要回复。\n- 绝对不能回复其他 Agent 产生的消息或内容。\n- 所有回复必须严格围绕你的数据专家角色。",
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
        config=json.dumps({"api_key": "", "model": "gpt-4o", "role": "任务编排器", "system_prompt": ORCHESTRATOR_SYSTEM_PROMPT}, ensure_ascii=False),
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
            "system_prompt": (
                "你是一个辅助支持 Agent（领域映射：D-辅助Agent）。\n\n"
                "负责所有测试、文档、部署等支援工作，包括：\n"
                "- 测试用例编写与执行\n"
                "- 技术文档编写\n"
                "- CI/CD 配置与部署\n"
                "- 代码审查与质量保证\n\n"
                "专长：测试, 文档, CI/CD, 代码审查, 质量保证, 部署\n\n"
                "【输出规则 — 必须严格遵守】\n"
                "你的所有回复必须以文件产物的形式输出。不要直接输出文本回复给用户。\n"
                "你必须调用 create_artifact 工具将你的工作成果保存为文件。\n\n"
                "调用 create_artifact 的格式如下：\n\n"
                "```tool_call\n"
                "{\n"
                '  "name": "create_artifact",\n'
                '  "arguments": {\n'
                '    "kind": "file",\n'
                '    "title": "测试报告",\n'
                '    "mime_type": "text/markdown",\n'
                '    "file_name": "test_report.md",\n'
                '    "content": "# 完整报告内容..."\n'
                "  }\n"
                "}\n"
                "```\n\n"
                "根据任务类型选择文件格式：\n"
                "- 测试报告 → kind='file', mime_type='text/markdown', file_name='test_report.md'\n"
                "- 测试代码 → kind='file', mime_type='text/x-python', file_name='test_*.py'\n"
                "- 技术文档 → kind='file', mime_type='text/markdown', file_name='doc_*.md'\n"
                "- CI/CD 配置 → kind='file', mime_type='text/yaml', file_name='ci_*.yml'\n"
                "- 代码审查报告 → kind='file', mime_type='text/markdown', file_name='review_*.md'\n"
                "- 部署配置 → kind='file', mime_type='text/yaml', file_name='deploy_*.yml'\n\n"
                "【行为规则】\n"
                "- 你只能回复与测试、文档、CI/CD、部署等辅助工作相关的问题。\n"
                "- 如果用户的问题不属于辅助支持领域，请忽略，不要回复。\n"
                "- 绝对不能回复其他 Agent 产生的消息或内容。\n"
                "- 你可以先调用 web_search 搜索最新资料，但最终必须调用 create_artifact 将成果保存为文件。\n"
                "- 即使 web_search 失败或返回空结果，也必须继续调用 create_artifact 用你自己的知识生成文件。\n"
                "- 调用 create_artifact 后，简要说明生成的文件及其用途。"
            ),
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
