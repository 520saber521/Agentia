"""LLM-based task classification — determines whether user input is software dev or not."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from sqlalchemy import select

from db.engine import get_sessionmaker
from db.models import Agent

logger = logging.getLogger("agenthub.orchestrator.classifier")

ORCHESTRATOR_AGENT_ID = "agent_orchestrator"


async def _llm_classify_task(user_text: str) -> str | None:
    """Use a configured LLM agent to classify whether the task is software development or not.

    Returns ``"software"``, ``"non_software"``, or ``None`` (LLM unavailable/error).
    """
    Session = get_sessionmaker()
    async with Session() as s:
        agents = (
            await s.scalars(
                select(Agent).where(
                    Agent.id != ORCHESTRATOR_AGENT_ID,
                    Agent.adapter_type != "mock",
                )
            )
        ).all()
        llm_agents = []
        for a in agents:
            try:
                cfg = json.loads(a.config) if a.config else {}
            except (TypeError, ValueError):
                cfg = {}
            if cfg.get("api_key"):
                llm_agents.append(a)
    if not llm_agents:
        return None

    from handlers.agent_ops import load_adapter_for
    loaded = await load_adapter_for(llm_agents[0].id)
    if loaded is None:
        return None
    adapter, _ = loaded

    prompt = (
        "你是一个任务分类器。判断以下用户请求属于哪一类。\n\n"
        "A-软件开发类：涉及创建/修改网页、前端界面、后端API、数据库、UI组件、App开发、部署等。\n"
        "B-非软件开发类：数学建模、数据分析、论文写作、研究报告、学术问题、物理/化学/生物等科学问题。\n\n"
        "只回复单个词：\"software\" 或 \"non_software\"\n\n"
        "用户请求：\n"
        f"{user_text[:3000]}"
    )
    try:
        async with asyncio.timeout(20):
            result = ""
            async for chunk in adapter.send(
                messages=[{"role": "user", "content": prompt}]
            ):
                if chunk.get("type") == "text":
                    result += chunk.get("delta", "")
                elif chunk.get("type") == "error":
                    logger.warning("LLM classify error: %s", chunk.get("message"))
                    return None
                elif chunk.get("type") == "done":
                    break
            result = result.strip().lower()
            if "non_software" in result:
                return "non_software"
            return "software"
    except asyncio.TimeoutError:
        logger.warning("LLM task classification timed out after 20s")
        return None
    except Exception as exc:
        logger.warning("LLM task classification failed: %s", exc)
        return None
