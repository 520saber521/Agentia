"""AgentHub API Key 配置工具。

用法 (PowerShell):
  python configure_key.py --agent claude --api-key sk-ant-xxx
  python configure_key.py --agent codex --api-key sk-openai-xxx
  python configure_key.py --list

支持的 agent:
  claude  → agent_claude (Anthropic Claude)
  codex   → agent_codex   (OpenAI-compatible)
  mock    → agent_mock    (Mock, 不需要 key)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 确保 server/ 在 sys.path 中
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from db.engine import get_sessionmaker
from db.models import Agent
from sqlalchemy import select


AGENT_MAP = {
    "claude": "agent_claude",
    "codex": "agent_codex",
    "deepseek": "agent_deepseek",
    "mock": "agent_mock",
    "mock2": "agent_mock_2",
    "orchestrator": "agent_orchestrator",
}


async def list_agents() -> None:
    Session = get_sessionmaker()
    async with Session() as s:
        rows = (await s.scalars(select(Agent).order_by(Agent.name))).all()
        if not rows:
            print("  (no agents found)")
            return
        for a in rows:
            cfg = json.loads(a.config)
            api_key = cfg.get("api_key", "")
            masked = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "(empty)"
            print(f"  {a.id:<20}  {a.name:<20}  {a.adapter_type:<12}  key: {masked}")


async def set_api_key(agent_alias: str, api_key: str) -> None:
    agent_id = AGENT_MAP.get(agent_alias)
    if not agent_id:
        known = ", ".join(AGENT_MAP)
        print(f"Unknown agent alias: {agent_alias!r}. Known: [{known}]")
        sys.exit(1)

    Session = get_sessionmaker()
    async with Session() as s:
        row = await s.scalar(select(Agent).where(Agent.id == agent_id))
        if row is None:
            print(f"Agent {agent_id!r} not found in database. Run the BFF server first to seed defaults.")
            sys.exit(1)

        cfg = json.loads(row.config)
        old_key = cfg.get("api_key", "")
        cfg["api_key"] = api_key
        row.config = json.dumps(cfg, ensure_ascii=False)
        await s.commit()

        old_masked = old_key[:8] + "..." + old_key[-4:] if len(old_key) > 12 else "(empty)"
        print(f"  [OK] {agent_id} ({row.name}) API key updated:")
        print(f"     Old: {old_masked}")
        print(f"     New: {api_key[:8]}...{api_key[-4:]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentHub API Key 配置工具")
    parser.add_argument("--agent", "-a", help="Agent 别名: claude, codex, mock")
    parser.add_argument("--api-key", "-k", help="API Key")
    parser.add_argument("--list", "-l", action="store_true", help="列出所有 Agent 及其 key 状态")

    args = parser.parse_args()

    if args.list:
        import asyncio
        asyncio.run(list_agents())
        return

    if args.agent and args.api_key:
        import asyncio
        asyncio.run(set_api_key(args.agent, args.api_key))
        return

    parser.print_help()
    print("\n快速示例:")
    print("  python configure_key.py --list")
    print('  python configure_key.py --agent claude --api-key "sk-ant-xxxxxxxx"')
    print('  python configure_key.py --agent codex --api-key "sk-openai-xxxxxx"')


if __name__ == "__main__":
    main()
