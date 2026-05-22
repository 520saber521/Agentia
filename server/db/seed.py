"""默认数据填充（幂等）。

启动时灌一份"演示数据"，让 BFF 不依赖任何外部状态就能跑通：

- 1 个用户：``user_demo``（占位，Day3 暂不做完整用户表）
- 内置 Agent：
    - ``agent_mock``   → MockAdapter（流式打字，主用单聊 demo）
    - ``agent_mock_2`` → MockAdapter 另一份配置（W2 F-W2-5 起 seed，仅为
      让"新建群聊"模态里至少有 2 个可选 Agent；W2-T2 接入 Claude 后此 seed
      会与 ``agent_claude`` 共存）
- 1 个会话：``conv_demo``（单聊 user_demo ↔ agent_mock）
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from .engine import get_sessionmaker
from .models import Agent, Conversation, ConversationMember

DEFAULT_USER_ID = "user_demo"
DEFAULT_AGENT_ID = "agent_mock"
DEFAULT_AGENT_ID_2 = "agent_mock_2"
DEFAULT_AGENT_CLAUDE = "agent_claude"
DEFAULT_AGENT_ORCHESTRATOR = "agent_orchestrator"
DEFAULT_AGENT_DEEPSEEK = "agent_deepseek"
DEFAULT_CONV_ID = "conv_demo"


async def _upsert_agent(s, *, agent_id: str, fields: dict[str, Any]) -> None:
    row = await s.scalar(select(Agent).where(Agent.id == agent_id))
    if row is None:
        s.add(Agent(id=agent_id, **fields))
    else:
        for key, value in fields.items():
            if key == "config" and row.config:
                existing_cfg = json.loads(row.config)
                new_cfg = json.loads(value) if isinstance(value, str) else value
                for cfg_key, cfg_value in existing_cfg.items():
                    if cfg_value not in (None, "", [], {}):
                        new_cfg[cfg_key] = cfg_value
                value = json.dumps(new_cfg, ensure_ascii=False)
            setattr(row, key, value)


async def seed_defaults() -> None:
    """运行多次结果一致 —— 已存在的不会重复插入。"""
    Session = get_sessionmaker()
    async with Session() as s:
        await _upsert_agent(
            s,
            agent_id=DEFAULT_AGENT_ID,
            fields=dict(
                name="Frontend Designer",
                avatar=None,
                adapter_type="mock",
                config=json.dumps({
                    "delay_ms": 20,
                    "role": "前端页面 Agent",
                    "reply": (
                        "【前端页面 Agent】我负责把需求落成可运行 UI / HTML / CSS：\n"
                        "{echo}\n\n"
                        "我会输出可预览的页面结构、交互状态和响应式布局。"
                    ),
                }, ensure_ascii=False),
                capabilities=json.dumps(["text", "mock", "frontend", "html", "preview"], ensure_ascii=False),
                owner_user_id=None,
            ),
        )
        await _upsert_agent(
            s,
            agent_id=DEFAULT_AGENT_ID_2,
            fields=dict(
                name="Backend Architect",
                avatar=None,
                adapter_type="mock",
                config=json.dumps({
                    "delay_ms": 35,
                    "role": "后端接口 Agent",
                    "reply": (
                        "【后端接口 Agent】我负责 API、数据模型、权限和错误码：\n"
                        "{echo}\n\n"
                        "我会给出接口契约、数据结构和可测试的后端边界。"
                    ),
                }, ensure_ascii=False),
                capabilities=json.dumps(["text", "mock", "backend", "api", "database"], ensure_ascii=False),
                owner_user_id=None,
            ),
        )
        await _upsert_agent(
            s,
            agent_id=DEFAULT_AGENT_CLAUDE,
            fields=dict(
                name="Claude Code",
                avatar=None,
                adapter_type="claude_code",
                config=json.dumps({"api_key": "", "model": "claude-sonnet-4-20250514"}, ensure_ascii=False),
                capabilities=json.dumps(["text", "code", "tool_use", "vision"], ensure_ascii=False),
                owner_user_id=None,
            ),
        )
        await _upsert_agent(
            s,
            agent_id=DEFAULT_AGENT_ORCHESTRATOR,
            fields=dict(
                name="Orchestrator",
                avatar=None,
                adapter_type="mock",
                config=json.dumps({
                    "delay_ms": 10,
                    "role": "任务编排器",
                    "reply": (
                        "【Orchestrator 任务编排器】\n"
                        "正在分析任务：{echo}\n\n"
                        "我将把任务拆解为子任务并分配给各 Agent。"
                    ),
                }, ensure_ascii=False),
                capabilities=json.dumps(["task_management", "scheduling", "decomposition", "aggregation"], ensure_ascii=False),
                owner_user_id=None,
            ),
        )
        await _upsert_agent(
            s,
            agent_id=DEFAULT_AGENT_DEEPSEEK,
            fields=dict(
                name="DeepSeek V4 Flash",
                avatar=None,
                adapter_type="codex",
                config=json.dumps({
                    "api_key": "",
                    "model": "deepseek-chat",
                    "base_url": "https://api.deepseek.com/v1",
                }, ensure_ascii=False),
                capabilities=json.dumps(["text", "code"], ensure_ascii=False),
                owner_user_id=None,
            ),
        )

        conv = await s.scalar(select(Conversation).where(Conversation.id == DEFAULT_CONV_ID))
        if conv is None:
            s.add(
                Conversation(
                    id=DEFAULT_CONV_ID,
                    title="Demo · 与 Mock Agent 单聊",
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

        await s.commit()
