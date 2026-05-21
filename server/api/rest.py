"""REST API（W1 Day3 起暴露会话与消息查询；W2 F-W2-5 起暴露 Agent 列表）。

| Path | 方法 | 说明 |
| --- | --- | --- |
| ``/api/agents`` | GET | 列出全部 Agent（W2 F-W2-5） |
| ``/api/conversations`` | GET | 列出全部会话（含成员） |
| ``/api/conversations`` | POST | 新建会话（含群聊 / 多 Agent，W2 F-W2-5 强化校验） |
| ``/api/conversations/{id}`` | GET | 单个会话详情 |
| ``/api/conversations/{id}/messages`` | GET | 游标分页拉消息（时间正序） |

鉴权留到 W4。
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from db import DEFAULT_USER_ID
from db.engine import get_sessionmaker
from router_client import get_router_client
from services.agent import list_agents
from services.conversation import (
    create_conversation,
    get_conversation,
    list_conversations,
    list_messages,
)

router = APIRouter(prefix="/api", tags=["bff"])


class CreateConversationBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    type: Literal["single", "group"] = "single"
    agent_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# /api/agents
# ---------------------------------------------------------------------------


@router.get("/agents")
async def api_list_agents() -> dict:
    """列出所有 Agent，按 ``name`` 升序。

    供前端 ``NewConversationDialog`` / 后续 ``AgentManage`` 页消费。
    """
    Session = get_sessionmaker()
    async with Session() as s:
        return {"agents": await list_agents(s)}


# ---------------------------------------------------------------------------
# /api/conversations
# ---------------------------------------------------------------------------


@router.get("/conversations")
async def api_list_conversations() -> dict:
    Session = get_sessionmaker()
    async with Session() as s:
        return {"conversations": await list_conversations(s)}


# 把 service 层抛出的 ValueError code 映射成 HTTP status + 稳定的错误码。
# 参考 ai-collab/rules/backend.mdc R-B-6：错误协议必须有稳定枚举。
_VALUE_ERROR_HTTP_STATUS: dict[str, int] = {
    "title required": 422,
    "invalid_type": 422,
    "group_requires_agents": 422,
    "unknown_agent": 422,
}


@router.post("/conversations", status_code=201)
async def api_create_conversation(body: CreateConversationBody) -> dict:
    """创建一个新会话。

    W1 Day5 起：owner 暂固定为 ``user_demo``，鉴权留到 W4。
    W2 F-W2-5 起：``type='group'`` 必须带 ≥1 个 ``agent_id``；
    所有 ``agent_id`` 必须存在；重复值会自动去重。
    """
    Session = get_sessionmaker()
    async with Session() as s:
        try:
            conv = await create_conversation(
                s,
                title=body.title,
                type_=body.type,
                owner_user_id=DEFAULT_USER_ID,
                agent_ids=body.agent_ids,
            )
        except ValueError as e:
            code = str(e)
            status = _VALUE_ERROR_HTTP_STATUS.get(code, 400)
            raise HTTPException(status_code=status, detail=code) from None
    return {"conversation": conv}


@router.get("/conversations/{conversation_id}")
async def api_get_conversation(conversation_id: str) -> dict:
    Session = get_sessionmaker()
    async with Session() as s:
        conv = await get_conversation(s, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail=f"conversation not found: {conversation_id}")
    return {"conversation": conv}


@router.get("/conversations/{conversation_id}/messages")
async def api_list_messages(
    conversation_id: str,
    before: str | None = Query(default=None, description="锚点消息 id；返回更早的消息"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    Session = get_sessionmaker()
    async with Session() as s:
        msgs = await list_messages(s, conversation_id, before_id=before, limit=limit)
    return {"conversation_id": conversation_id, "messages": msgs, "limit": limit}


# ---------------------------------------------------------------------------
# /api/trace
# ---------------------------------------------------------------------------


@router.get("/trace/{message_id}")
async def api_trace(message_id: str) -> dict[str, Any]:
    """拉取 Router 上某条消息的投递链路（F-W3-1）。

    Message 的 ``agenthub_msg_id`` 就是 Router 侧的消息 id。
    如果 BFF 尚未连接 Router，返回 502。
    """
    client = get_router_client()
    try:
        result = await client.trace(message_id=message_id)
        return {"trace": result}
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Router not reachable or trace not found",
        ) from None
