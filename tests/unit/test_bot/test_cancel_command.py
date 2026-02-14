"""Tests for /cancel command fallback behavior."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.bot.handlers.command import cancel_task


@pytest.mark.asyncio
async def test_cancel_command_falls_back_to_user_scope(tmp_path):
    """`/cancel` should retry without scope key when scoped cancel misses."""
    user_id = 9201
    chat_id = 9301
    task_registry = SimpleNamespace(cancel=AsyncMock(side_effect=[False, True]))
    message = SimpleNamespace(
        chat_id=chat_id,
        message_thread_id=None,
        reply_text=AsyncMock(),
    )
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=chat_id),
        effective_message=message,
        message=message,
    )
    context = SimpleNamespace(
        bot_data={
            "task_registry": task_registry,
            "settings": SimpleNamespace(approved_directory=tmp_path),
        },
        user_data={},
    )

    await cancel_task(update, context)

    assert task_registry.cancel.await_count == 2
    first = task_registry.cancel.await_args_list[0]
    second = task_registry.cancel.await_args_list[1]
    assert first.args == (user_id,)
    assert first.kwargs["scope_key"] == f"{user_id}:{chat_id}:0"
    assert second.args == (user_id,)
    assert second.kwargs["scope_key"] is None
    message.reply_text.assert_awaited_once_with("Task cancellation requested.")
