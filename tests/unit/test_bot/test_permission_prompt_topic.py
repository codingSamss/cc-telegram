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


@pytest.mark.asyncio
async def test_permission_prompt_drops_thread_in_private_chat():
    """Private chat should never include message_thread_id."""
    bot = SimpleNamespace(send_message=AsyncMock())
    settings = SimpleNamespace(use_sdk=True)
    handler = build_permission_handler(
        bot=bot,
        chat_id=123456,
        settings=settings,
        chat_type="private",
        message_thread_id=88,
    )

    assert handler is not None

    await handler(
        "req-private",
        "Read",
        {"file_path": "README.md"},
        "session-private",
    )

    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == 123456
    assert "message_thread_id" not in kwargs


@pytest.mark.asyncio
async def test_permission_prompt_retries_without_thread_when_thread_missing():
    """Should retry without topic thread when Telegram rejects thread id."""
    bot = SimpleNamespace(
        send_message=AsyncMock(
            side_effect=[Exception("Bad Request: message thread not found"), object()]
        )
    )
    settings = SimpleNamespace(use_sdk=True)
    handler = build_permission_handler(
        bot=bot,
        chat_id=-100123,
        settings=settings,
        chat_type="supergroup",
        message_thread_id=42,
    )

    assert handler is not None

    await handler(
        "req-threadless",
        "Bash",
        {"command": "ls -la"},
        "session-threadless",
    )

    assert bot.send_message.await_count == 2
    first_call_kwargs = bot.send_message.await_args_list[0].kwargs
    second_call_kwargs = bot.send_message.await_args_list[1].kwargs
    assert first_call_kwargs["message_thread_id"] == 42
    assert "message_thread_id" not in second_call_kwargs


@pytest.mark.asyncio
async def test_permission_prompt_retries_without_markdown_on_parse_error():
    """Should retry without parse_mode when Markdown parsing fails."""
    bot = SimpleNamespace(
        send_message=AsyncMock(
            side_effect=[Exception("Bad Request: can't parse entities"), object()]
        )
    )
    settings = SimpleNamespace(use_sdk=True)
    handler = build_permission_handler(
        bot=bot,
        chat_id=-100123,
        settings=settings,
        chat_type="supergroup",
        message_thread_id=42,
    )

    assert handler is not None

    await handler(
        "req-nomd",
        "Bash",
        {"command": "echo hi"},
        "session-nomd",
    )

    assert bot.send_message.await_count == 2
    first_call_kwargs = bot.send_message.await_args_list[0].kwargs
    second_call_kwargs = bot.send_message.await_args_list[1].kwargs
    assert first_call_kwargs["parse_mode"] == "Markdown"
    assert "parse_mode" not in second_call_kwargs
