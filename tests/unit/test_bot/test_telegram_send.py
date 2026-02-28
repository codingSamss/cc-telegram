"""Tests for Telegram send helper behavior."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.bot.utils.telegram_send import send_message_resilient


@pytest.mark.asyncio
async def test_send_message_resilient_private_chat_drops_reply_to_message_id():
    """Private chats should not include quote replies by default."""
    bot = SimpleNamespace(send_message=AsyncMock(return_value=object()))

    await send_message_resilient(
        bot=bot,
        chat_id=12345,
        text="hello",
        reply_to_message_id=777,
        chat_type="private",
    )

    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == 12345
    assert kwargs["text"] == "hello"
    assert "reply_to_message_id" not in kwargs


@pytest.mark.asyncio
async def test_send_message_resilient_group_chat_keeps_reply_to_message_id():
    """Group chats should keep explicit reply target."""
    bot = SimpleNamespace(send_message=AsyncMock(return_value=object()))

    await send_message_resilient(
        bot=bot,
        chat_id=-100123,
        text="hello",
        reply_to_message_id=777,
        chat_type="supergroup",
    )

    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == -100123
    assert kwargs["reply_to_message_id"] == 777

