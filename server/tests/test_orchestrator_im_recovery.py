from __future__ import annotations

import pytest

from orchestrator import _generate_preview_html_with_model, _is_im_chat_request


def test_im_chat_request_detects_qq_single_and_group_chat():
    assert _is_im_chat_request("生成一个模仿QQ的网站，要包含QQ的单聊群聊功能")
    assert _is_im_chat_request("build an IM app with friend messages and group chat")


@pytest.mark.asyncio
async def test_preview_generation_requires_configured_llm_for_im_requests(db_env):
    with pytest.raises(RuntimeError, match="No configured LLM agent"):
        await _generate_preview_html_with_model(
            conversation_id="conv_missing_llm",
            user_text="生成一个模仿QQ的网站，要包含QQ的单聊群聊功能",
            conversation_history=[],
            subtask_records=[],
            subtask_messages={},
        )
