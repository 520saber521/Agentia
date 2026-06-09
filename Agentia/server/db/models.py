"""SQLAlchemy 2.x ORM 模型（与 ``docs/ARCHITECTURE.md`` §6.2 一致）。

Day3 落地四张表：``conversation`` / ``conversation_member`` / ``message`` / ``agent``。
W3 新增 ``task`` 表用于任务状态机。
W4 再补 ``artifact``。
"""

from __future__ import annotations

import time
import uuid
from typing import Optional

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


class Conversation(Base):
    __tablename__ = "conversation"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)  # 'single' | 'group'
    created_at: Mapped[int] = mapped_column(Integer, default=now_ms, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, default=now_ms, nullable=False)
    pinned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    archived: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_msg_preview: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    workspace_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True, default=None)
    owner_user_id: Mapped[str] = mapped_column(String, nullable=False)


class ConversationMember(Base):
    __tablename__ = "conversation_member"

    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversation.id", ondelete="CASCADE"), primary_key=True
    )
    member_id: Mapped[str] = mapped_column(String, primary_key=True)
    member_type: Mapped[str] = mapped_column(String, nullable=False)  # 'user' | 'agent'
    role: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    joined_at: Mapped[int] = mapped_column(Integer, default=now_ms, nullable=False)


class Message(Base):
    __tablename__ = "message"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False
    )
    sender_id: Mapped[str] = mapped_column(String, nullable=False)
    sender_type: Mapped[str] = mapped_column(String, nullable=False)  # 'user' | 'agent'
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)  # JSON string
    reply_to: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    mentions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON array string
    pinned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    artifact_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    agenthub_msg_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, default=now_ms, nullable=False)

    __table_args__ = (
        Index("idx_msg_conv", "conversation_id", "created_at"),
        Index("idx_msg_agenthub", "agenthub_msg_id"),
    )


class Agent(Base):
    __tablename__ = "agent"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    avatar: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    adapter_type: Mapped[str] = mapped_column(String, nullable=False)
    config: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    capabilities: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON array
    owner_user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_system: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_prompt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, default=now_ms, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, default=now_ms, nullable=False)


class AgentExecution(Base):
    __tablename__ = "agent_execution"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    message_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    agent_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("agent.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    input_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[int] = mapped_column(Integer, default=now_ms, nullable=False)
    finished_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        Index("idx_agent_execution_agent", "agent_id", "started_at"),
        Index("idx_agent_execution_conv", "conversation_id", "started_at"),
    )


class Artifact(Base):
    """产物表 — F-W4-2: artifact 一等对象与版本链。

    所有"可被预览 / 编辑 / 下载"的对象都落在这里。
    消息的 ``content`` 只存 ``artifact_id`` 与预览元数据。
    """

    __tablename__ = "artifact"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # 'code' | 'preview' | 'file' | 'diff'
    title: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    file_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    storage_path: Mapped[str] = mapped_column(String, nullable=False)
    source_message_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    meta: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, default=now_ms, nullable=False)

    __table_args__ = (
        Index("idx_artifact_conv", "conversation_id"),
        Index("idx_artifact_parent", "parent_id"),
    )


class Task(Base):
    __tablename__ = "task"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False
    )
    parent_task_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    domain: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    assigned_agent_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    agent_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    originating_message_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    result_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    progress_pct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, default=now_ms, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, default=now_ms, nullable=False)

    __table_args__ = (
        Index("idx_task_conv", "conversation_id"),
        Index("idx_task_parent", "parent_task_id"),
        Index("idx_task_status", "status"),
    )


class TraceEntry(Base):
    """Message routing trace — F-W3-1.

    Records each hop a message takes: user → Router → Adapter → done.
    """

    __tablename__ = "trace_entry"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    message_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False)
    trace_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String, nullable=False)
    node_role: Mapped[str] = mapped_column(String, nullable=False)
    event: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="ok")
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    seq: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, default=now_ms, nullable=False)

    __table_args__ = (
        Index("idx_trace_msg", "message_id", "seq"),
        Index("idx_trace_id", "trace_id"),
    )
