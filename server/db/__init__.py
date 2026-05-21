"""数据访问层（SQLAlchemy 2.x async + SQLite/aiosqlite）。

- ``engine``  —— Engine、SessionMaker、初始化与销毁
- ``models``  —— ORM 模型（``Conversation`` / ``ConversationMember`` / ``Message`` / ``Agent``）
- ``seed``    —— 默认数据填充

设计来源：``docs/ARCHITECTURE.md`` §5.3 / §6.2。
"""

from .engine import dispose, get_engine, get_sessionmaker, init_db
from .models import Agent, Base, Conversation, ConversationMember, Message
from .seed import (
    DEFAULT_AGENT_ID,
    DEFAULT_AGENT_ID_2,
    DEFAULT_CONV_ID,
    DEFAULT_USER_ID,
    seed_defaults,
)

__all__ = [
    "Agent",
    "Base",
    "Conversation",
    "ConversationMember",
    "DEFAULT_AGENT_ID",
    "DEFAULT_AGENT_ID_2",
    "DEFAULT_CONV_ID",
    "DEFAULT_USER_ID",
    "Message",
    "dispose",
    "get_engine",
    "get_sessionmaker",
    "init_db",
    "seed_defaults",
]
