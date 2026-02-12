"""Tests for bot rate limit middleware utilities."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.bot.middleware.rate_limit import estimate_message_cost, rate_limit_middleware


def _make_event(*, text=None, caption=None, has_photo=False, has_document=False):
    """Create a lightweight Telegram-like event object for tests."""
    message = SimpleNamespace(
        text=text,
        caption=caption,
        photo=[object()] if has_photo else None,
        document=object() if has_document else None,
        reply_text=AsyncMock(),
    )
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=123, username="tester"),
        effective_message=message,
    )


def test_estimate_message_cost_photo_without_text():
    """Photo messages with text=None should be handled safely."""
    event = _make_event(text=None, has_photo=True)
    cost = estimate_message_cost(event)
    assert isinstance(cost, float)
    assert cost > 0


def test_estimate_message_cost_document_without_text():
    """Document messages with text=None should be handled safely."""
    event = _make_event(text=None, has_document=True)
    cost = estimate_message_cost(event)
    assert isinstance(cost, float)
    assert cost > 0


@pytest.mark.asyncio
async def test_rate_limit_middleware_photo_none_text_calls_next_handler():
    """Middleware should not raise on photo updates with no text."""
    event = _make_event(text=None, caption=None, has_photo=True)
    next_handler = AsyncMock(return_value="ok")
    rate_limiter = AsyncMock()
    rate_limiter.check_rate_limit = AsyncMock(return_value=(True, "ok"))

    result = await rate_limit_middleware(
        next_handler,
        event,
        {"rate_limiter": rate_limiter, "audit_logger": None},
    )

    assert result == "ok"
    next_handler.assert_awaited_once()
