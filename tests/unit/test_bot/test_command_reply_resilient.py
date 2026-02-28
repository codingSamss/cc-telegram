"""Tests for command reply fallback helper."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.bot.handlers.command import (
    _edit_message_resilient,
    _reply_update_message_resilient,
)


@pytest.mark.asyncio
async def test_reply_update_message_resilient_prefers_direct_reply_text():
    """Command reply should keep direct reply_text path when it succeeds."""
    message = SimpleNamespace(
        reply_text=AsyncMock(return_value=object()),
        message_thread_id=42,
    )
    update = SimpleNamespace(
        message=message,
        effective_chat=SimpleNamespace(id=-100123, type="supergroup"),
        effective_message=message,
    )
    context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))

    await _reply_update_message_resilient(
        update,
        context,
        "ok",
        parse_mode="Markdown",
    )

    assert message.reply_text.await_count == 1
    assert context.bot.send_message.await_count == 0


@pytest.mark.asyncio
async def test_reply_update_message_resilient_falls_back_to_threadless_retry():
    """When reply_text fails, helper should fallback and retry without thread."""
    message = SimpleNamespace(
        reply_text=AsyncMock(
            side_effect=Exception("Bad Request: message thread not found")
        ),
        message_thread_id=42,
    )
    update = SimpleNamespace(
        message=message,
        effective_chat=SimpleNamespace(id=-100123, type="supergroup"),
        effective_message=message,
    )
    context = SimpleNamespace(
        bot=SimpleNamespace(
            send_message=AsyncMock(
                side_effect=[
                    Exception("Bad Request: message thread not found"),
                    object(),
                ]
            )
        )
    )

    await _reply_update_message_resilient(
        update,
        context,
        "fallback",
        parse_mode="Markdown",
    )

    assert message.reply_text.await_count == 1
    assert context.bot.send_message.await_count == 2
    first_call_kwargs = context.bot.send_message.await_args_list[0].kwargs
    second_call_kwargs = context.bot.send_message.await_args_list[1].kwargs
    assert first_call_kwargs["message_thread_id"] == 42
    assert "message_thread_id" not in second_call_kwargs


@pytest.mark.asyncio
async def test_reply_update_message_resilient_private_chat_drops_reply_quote():
    """Private chat direct reply should not carry reply_to_message_id."""
    message = SimpleNamespace(
        reply_text=AsyncMock(return_value=object()),
        message_thread_id=None,
    )
    update = SimpleNamespace(
        message=message,
        effective_chat=SimpleNamespace(id=12345, type="private"),
        effective_message=message,
    )
    context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))

    await _reply_update_message_resilient(
        update,
        context,
        "no quote",
        reply_to_message_id=99,
    )

    kwargs = message.reply_text.await_args.kwargs
    assert "reply_to_message_id" not in kwargs


@pytest.mark.asyncio
async def test_edit_message_resilient_retries_without_markdown():
    """Edit helper should fallback to plain text when markdown parsing fails."""
    message = SimpleNamespace(
        edit_text=AsyncMock(
            side_effect=[Exception("Bad Request: can't parse entities"), object()]
        )
    )

    await _edit_message_resilient(
        message,
        "codex_core::rollout::list",
        parse_mode="Markdown",
    )

    assert message.edit_text.await_count == 2
    first_call_kwargs = message.edit_text.await_args_list[0].kwargs
    second_call_kwargs = message.edit_text.await_args_list[1].kwargs
    assert first_call_kwargs["parse_mode"] == "Markdown"
    assert "parse_mode" not in second_call_kwargs


@pytest.mark.asyncio
async def test_edit_message_resilient_ignores_noop_errors():
    """No-op edit error should be treated as successful no-op."""
    message = SimpleNamespace(
        edit_text=AsyncMock(
            side_effect=Exception("Bad Request: message is not modified")
        )
    )

    result = await _edit_message_resilient(
        message,
        "same content",
        parse_mode="Markdown",
    )

    assert message.edit_text.await_count == 1
    assert result is None
