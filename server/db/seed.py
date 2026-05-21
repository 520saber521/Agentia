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
DEFAULT_CONV_ID = "conv_demo"


async def _upsert_agent(s, *, agent_id: str, fields: dict[str, Any]) -> None:
    row = await s.scalar(select(Agent).where(Agent.id == agent_id))
    if row is None:
        s.add(Agent(id=agent_id, **fields))
    else:
        for key, value in fields.items():
            setattr(row, key, value)


async def seed_defaults() -> None:
    """运行多次结果一致 —— 已存在的不会重复插入。"""
    Session = get_sessionmaker()
    async with Session() as s:
        await _upsert_agent(
            s,
            agent_id=DEFAULT_AGENT_ID,
            fields=dict(
                name="Mock Agent",
                avatar=None,
                adapter_type="mock",
                config=json.dumps({
                    "delay_ms": 20,
                    "role": "通用助手",
                    "reply": (
                        "我是通用助手 MockAgent，收到你的消息：\n"
                        "{echo}\n\n"
                        "我正在处理你的请求，请稍候..."
                    ),
                }, ensure_ascii=False),
                capabilities=json.dumps(["text", "mock", "general"], ensure_ascii=False),
                owner_user_id=None,
            ),
        )
        await _upsert_agent(
            s,
            agent_id=DEFAULT_AGENT_ID_2,
            fields=dict(
                name="Mock Agent 2",
                avatar=None,
                adapter_type="mock",
                config=json.dumps({
                    "delay_ms": 35,
                    "role": "后端开发",
                    "reply": (
                        "[后端 MockAgent] 收到 API / 数据处理相关任务：\n"
                        "{echo}\n\n"
                        "我在设计接口和数据模型，请其他 Agent 配合前端对接。"
                    ),
                }, ensure_ascii=False),
                capabilities=json.dumps(["text", "mock", "backend"], ensure_ascii=False),
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
