"""Tests for topic-aware tool permission prompt delivery."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.bot.handlers.message import build_permission_handler


@pytest.mark.asyncio
async def test_permission_prompt_sent_to_same_topic_thread():
    """Permission prompt should stay in the same Telegram topic thread."""
    bot = SimpleNamespace(send_message=AsyncMock())
    settings = SimpleNamespace(use_sdk=True)
    handler = build_permission_handler(
        bot=bot,
        chat_id=-100123,
        settings=settings,
        message_thread_id=42,
    )

    assert handler is not None

    await handler(
        "req-1",
        "Bash",
        {"command": "ls -la"},
        "session-1",
    )

    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == -100123
    assert kwargs["message_thread_id"] == 42
    assert "Tool Permission Request" in kwargs["text"]


@pytest.mark.asyncio
async def test_permission_prompt_omits_thread_when_not_in_topic():
    """Permission prompt should omit thread id when no topic is active."""
    bot = SimpleNamespace(send_message=AsyncMock())
    settings = SimpleNamespace(use_sdk=True)
    handler = build_permission_handler(
        bot=bot,
        chat_id=123456,
        settings=settings,
        message_thread_id=None,
    )

    assert handler is not None

    await handler(
        "req-2",
        "Read",
        {"file_path": "README.md"},
        "session-2",
    )

    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == 123456
    assert "message_thread_id" not in kwargs
