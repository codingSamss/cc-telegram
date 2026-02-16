"""Tests for permission callback handler."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.bot.handlers.callback import handle_permission_callback
from src.services import ApprovalService


class _FakePermissionManager:
    """Simple permission manager stub."""

    def __init__(self, resolved: bool = True):
        self.resolved = resolved

    def resolve_permission(self, request_id: str, decision: str, user_id: int) -> bool:
        return self.resolved


def _build_query(user_id: int = 1001):
    """Build callback query stub."""
    return SimpleNamespace(
        from_user=SimpleNamespace(id=user_id),
        edit_message_text=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_handle_permission_callback_success():
    """Successful callback should render resolved message."""
    query = _build_query()
    context = SimpleNamespace(
        bot_data={
            "approval_service": ApprovalService(),
            "permission_manager": _FakePermissionManager(resolved=True),
        }
    )

    await handle_permission_callback(query, "allow:req-1", context)

    query.edit_message_text.assert_awaited_once()
    rendered = query.edit_message_text.await_args.args[0]
    assert "Permission Allowed" in rendered
    assert query.edit_message_text.await_args.kwargs["parse_mode"] == "Markdown"


@pytest.mark.asyncio
async def test_handle_permission_callback_expired():
    """Expired callback should render timeout message."""
    query = _build_query()
    context = SimpleNamespace(
        bot_data={
            "approval_service": ApprovalService(),
            "permission_manager": _FakePermissionManager(resolved=False),
        }
    )

    await handle_permission_callback(query, "deny:req-expired", context)

    rendered = query.edit_message_text.await_args.args[0]
    assert "Permission Request Expired" in rendered


@pytest.mark.asyncio
async def test_handle_permission_callback_invalid_param():
    """Invalid callback payload should fail fast."""
    query = _build_query()
    context = SimpleNamespace(
        bot_data={
            "approval_service": ApprovalService(),
            "permission_manager": _FakePermissionManager(resolved=True),
        }
    )

    await handle_permission_callback(query, "invalid", context)

    rendered = query.edit_message_text.await_args.args[0]
    assert rendered == "Invalid permission callback data."


@pytest.mark.asyncio
async def test_handle_permission_callback_fallbacks_to_plain_text_on_md_error():
    """Markdown edit failure should fallback to plain text edit instead of bubbling."""
    query = _build_query()
    query.edit_message_text.side_effect = [Exception("can't parse entities"), None]
    context = SimpleNamespace(
        bot_data={
            "approval_service": ApprovalService(),
            "permission_manager": _FakePermissionManager(resolved=True),
        }
    )

    await handle_permission_callback(query, "allow:req-md-fallback", context)

    assert query.edit_message_text.await_count == 2
    first_call = query.edit_message_text.await_args_list[0]
    second_call = query.edit_message_text.await_args_list[1]
    assert first_call.kwargs.get("parse_mode") == "Markdown"
    assert second_call.kwargs.get("parse_mode") is None
