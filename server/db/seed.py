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
from services.secrets import encrypt_secret

DEFAULT_USER_ID = "user_demo"
DEFAULT_AGENT_ID = "agent_mock"
DEFAULT_AGENT_ID_2 = "agent_mock_2"
DEFAULT_AGENT_CLAUDE = "agent_claude"
DEFAULT_AGENT_ORCHESTRATOR = "agent_orchestrator"
DEFAULT_AGENT_DEEPSEEK = "agent_deepseek"
DEFAULT_AGENT_OPENCODE = "agent_opencode"
DEFAULT_CONV_ID = "conv_demo"

_AGENT_DEFAULTS: list[tuple[str, dict[str, Any]]] = [
    (DEFAULT_AGENT_ID, dict(
        name="MockAdapter",
        avatar="🧪",
        adapter_type="mock",
        config=json.dumps({"delay_ms": 80, "reply": "模拟回复（离线测试用）"}, ensure_ascii=False),
        capabilities=json.dumps(["text", "code", "frontend", "backend", "database", "test", "docs", "testing"], ensure_ascii=False),
        owner_user_id=None,
    )),
    (DEFAULT_AGENT_ID_2, dict(
        name="CustomAgentAdapter",
        avatar="🔧",
        adapter_type="codex",
        config=json.dumps({"api_key": "", "model": "deepseek-v4-flash", "base_url": "https://api.deepseek.com/v1"}, ensure_ascii=False),
        capabilities=json.dumps(["text", "code", "custom", "flexible"], ensure_ascii=False),
        owner_user_id=None,
    )),
    (DEFAULT_AGENT_CLAUDE, dict(
        name="ClaudeCodeAdapter",
        avatar="🤖",
        adapter_type="claude_code",
        config=json.dumps({"api_key": "", "model": "gpt-5.4", "base_url": "https://api.apikey.fun/v1"}, ensure_ascii=False),
        capabilities=json.dumps(["text", "code", "tool_use", "vision", "analysis"], ensure_ascii=False),
        owner_user_id=None,
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
        name="CodexAdapter",
        avatar="⚡",
        adapter_type="codex",
        config=json.dumps({"api_key": "", "model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1"}, ensure_ascii=False),
        capabilities=json.dumps(["text", "code", "frontend", "backend", "database"], ensure_ascii=False),
        owner_user_id=None,
    )),
    (DEFAULT_AGENT_OPENCODE, dict(
        name="OpenCodeAdapter",
        avatar="🔗",
        adapter_type="opencode",
        config=json.dumps({"api_key": encrypt_secret("sk-980b1a1f9aa3019f34346eab42cc5a3a07f5e70913087d813e5b2189c33768d1"), "model": "gpt-5.4", "base_url": "https://api.apikey.fun/v1"}, ensure_ascii=False),
        capabilities=json.dumps(["text", "code", "tool_use", "backend", "frontend", "fullstack"], ensure_ascii=False),
        owner_user_id=None,
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
                if is_first_run:
                    s.add(Agent(id=agent_id, **fields))
                # 非首次且 row 不存在 = 被用户删过，跳过
                continue
            # 更新已存在的 agent（保留用户已配置的 config 值）
            now = int(__import__("time").time() * 1000)
            for key, value in fields.items():
                if key == "config" and row.config:
                    existing_cfg = json.loads(row.config)
                    new_cfg = json.loads(value) if isinstance(value, str) else value
                    for cfg_key, cfg_value in existing_cfg.items():
                        if cfg_value not in (None, "", [], {}):
                            new_cfg[cfg_key] = cfg_value
                    value = json.dumps(new_cfg, ensure_ascii=False)
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

        await s.commit()
