"""Tests for callback reply fallback helper."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.bot.handlers.callback import (
    _edit_query_message_resilient,
    _reply_query_message_resilient,
)


@pytest.mark.asyncio
async def test_reply_query_message_resilient_prefers_direct_reply_text():
    """Callback reply should keep direct reply_text path when it succeeds."""
    message = SimpleNamespace(
        reply_text=AsyncMock(return_value=object()),
        chat_id=-100123,
        chat=SimpleNamespace(id=-100123, type="supergroup"),
        message_thread_id=42,
    )
    query = SimpleNamespace(message=message)
    context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))

    await _reply_query_message_resilient(
        query,
        context,
        "ok",
        parse_mode="Markdown",
    )

    assert message.reply_text.await_count == 1
    assert context.bot.send_message.await_count == 0


@pytest.mark.asyncio
async def test_reply_query_message_resilient_falls_back_to_threadless_retry():
    """When reply_text fails, helper should fallback and retry without thread."""
    message = SimpleNamespace(
        reply_text=AsyncMock(
            side_effect=Exception("Bad Request: message thread not found")
        ),
        chat_id=-100123,
        chat=SimpleNamespace(id=-100123, type="supergroup"),
        message_thread_id=42,
    )
    query = SimpleNamespace(message=message)
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

    await _reply_query_message_resilient(
        query,
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
async def test_edit_query_message_resilient_retries_without_markdown():
    """Edit helper should fallback to plain text when markdown parsing fails."""
    query = SimpleNamespace(
        edit_message_text=AsyncMock(
            side_effect=[Exception("Bad Request: can't parse entities"), object()]
        )
    )

    await _edit_query_message_resilient(
        query,
        "codex_core::rollout::list",
        parse_mode="Markdown",
    )

    assert query.edit_message_text.await_count == 2
    first_call_kwargs = query.edit_message_text.await_args_list[0].kwargs
    second_call_kwargs = query.edit_message_text.await_args_list[1].kwargs
    assert first_call_kwargs["parse_mode"] == "Markdown"
    assert "parse_mode" not in second_call_kwargs


@pytest.mark.asyncio
async def test_edit_query_message_resilient_ignores_noop_errors():
    """No-op edit error should be treated as successful no-op."""
    query = SimpleNamespace(
        edit_message_text=AsyncMock(
            side_effect=Exception("Bad Request: message is not modified")
        )
    )

    result = await _edit_query_message_resilient(
        query,
        "same content",
        parse_mode="Markdown",
    )

    assert query.edit_message_text.await_count == 1
    assert result is None
