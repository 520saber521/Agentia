"""业务服务层。

把跨 ORM 的查询 / 写入收敛成函数，给 ``main.py`` / ``api/rest.py`` 调用。
未来 Day5 接 Router 时，可以在这里加 ``agenthub_msg_id`` 的双向映射逻辑。
"""

from .agent import (
    agent_to_dict,
    get_existing_agent_ids,
    list_agents,
)
from .conversation import (
    conv_to_dict,
    create_conversation,
    get_conversation,
    list_conversations,
    list_messages,
)
from .message import (
    create_message,
    message_to_dict,
    update_message_content,
)

__all__ = [
    "agent_to_dict",
    "conv_to_dict",
    "create_conversation",
    "create_message",
    "get_conversation",
    "get_existing_agent_ids",
    "list_agents",
    "list_conversations",
    "list_messages",
    "message_to_dict",
    "update_message_content",
]
