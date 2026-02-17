import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.bot.handlers.message import _send_chat_action_heartbeat


@pytest.mark.asyncio
async def test_send_chat_action_heartbeat_sends_typing_repeatedly() -> None:
    send_action = AsyncMock()
    message = SimpleNamespace(chat=SimpleNamespace(send_action=send_action))
    stop_event = asyncio.Event()

    task = asyncio.create_task(
        _send_chat_action_heartbeat(
            message=message,
            action="typing",
            stop_event=stop_event,
            interval_seconds=0.05,
        )
    )
    await asyncio.sleep(0.18)
    stop_event.set()
    await task

    assert send_action.await_count >= 2
    send_action.assert_called_with("typing")


@pytest.mark.asyncio
async def test_send_chat_action_heartbeat_uses_topic_thread_id() -> None:
    send_action = AsyncMock()
    message = SimpleNamespace(chat=SimpleNamespace(send_action=send_action))
    stop_event = asyncio.Event()

    task = asyncio.create_task(
        _send_chat_action_heartbeat(
            message=message,
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

    assert send_action.await_count >= 2
    send_action.assert_called_with("typing", message_thread_id=42)


@pytest.mark.asyncio
async def test_send_chat_action_heartbeat_skips_general_topic_id() -> None:
    send_action = AsyncMock()
    message = SimpleNamespace(chat=SimpleNamespace(send_action=send_action))
    stop_event = asyncio.Event()

    task = asyncio.create_task(
        _send_chat_action_heartbeat(
            message=message,
            action="typing",
            stop_event=stop_event,
            interval_seconds=0.05,
            message_thread_id=1,
            chat_type="supergroup",
        )
    )
    await asyncio.sleep(0.18)
    stop_event.set()
    await task

    assert send_action.await_count >= 2
    send_action.assert_called_with("typing")
