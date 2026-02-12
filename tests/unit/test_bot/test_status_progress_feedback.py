"""Tests for status loading feedback in command and callback handlers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.bot.handlers.callback import _handle_status_action
from src.bot.handlers.command import session_status


@pytest.mark.asyncio
async def test_session_status_shows_loading_message_before_final_output(tmp_path):
    """The /status command should send immediate loading feedback."""
    approved = tmp_path / "approved"
    approved.mkdir()

    status_msg = SimpleNamespace(edit_text=AsyncMock())
    message = SimpleNamespace(reply_text=AsyncMock(return_value=status_msg))
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=1001),
        message=message,
    )
    context = SimpleNamespace(
        bot_data={"settings": SimpleNamespace(approved_directory=approved)},
        user_data={},
    )

    await session_status(update, context)

    message.reply_text.assert_awaited_once_with("⏳ 正在获取会话状态，请稍候...")
    status_msg.edit_text.assert_awaited_once()
    assert "Session: none" in status_msg.edit_text.await_args.args[0]


@pytest.mark.asyncio
async def test_status_callback_shows_loading_message_before_refresh_result(tmp_path):
    """Status callback should first show a refreshing indicator."""
    approved = tmp_path / "approved"
    approved.mkdir()

    query = SimpleNamespace(edit_message_text=AsyncMock())
    context = SimpleNamespace(
        bot_data={"settings": SimpleNamespace(approved_directory=approved)},
        user_data={},
    )

    await _handle_status_action(query, context)

    assert query.edit_message_text.await_count == 2
    calls = query.edit_message_text.await_args_list
    assert "正在刷新状态" in calls[0].args[0]
    assert "Session: none" in calls[1].args[0]
