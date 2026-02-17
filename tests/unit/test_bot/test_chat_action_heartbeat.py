import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.bot.handlers.callback import _send_chat_action_heartbeat as callback_heartbeat
from src.bot.handlers.command import _send_chat_action_heartbeat as command_heartbeat


@pytest.mark.asyncio
async def test_command_chat_action_heartbeat_uses_topic_thread_id() -> None:
    send_chat_action = AsyncMock()
    bot = SimpleNamespace(send_chat_action=send_chat_action)
    stop_event = asyncio.Event()

    task = asyncio.create_task(
        command_heartbeat(
            bot=bot,
            chat_id=10001,
            action="typing",
            stop_event=stop_event,
            interval_seconds=0.05,
            message_thread_id=42,
            chat_type="supergroup",
        )
    )
    await asyncio.sleep(0.18)
    stop_event.set()
    await task

    assert send_chat_action.await_count >= 2
    send_chat_action.assert_called_with(
        chat_id=10001, action="typing", message_thread_id=42
    )


@pytest.mark.asyncio
async def test_callback_chat_action_heartbeat_skips_thread_for_private_chat() -> None:
    send_chat_action = AsyncMock()
    bot = SimpleNamespace(send_chat_action=send_chat_action)
    stop_event = asyncio.Event()

    task = asyncio.create_task(
        callback_heartbeat(
            bot=bot,
            chat_id=10002,
            action="typing",
            stop_event=stop_event,
            interval_seconds=0.05,
            message_thread_id=88,
            chat_type="private",
        )
    )
    await asyncio.sleep(0.18)
    stop_event.set()
    await task

    assert send_chat_action.await_count >= 2
    send_chat_action.assert_called_with(chat_id=10002, action="typing")
