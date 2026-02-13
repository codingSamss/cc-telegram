"""Tests for export callback flow."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.features.session_export import ExportedSession, ExportFormat
from src.bot.handlers.callback import _handle_export_action, handle_export_callback


class _FakeFeatures:
    """Minimal features stub for export callback tests."""

    def __init__(self, exporter):
        self._exporter = exporter

    def get_session_export(self):
        return self._exporter


def _build_query(user_id: int = 1001):
    """Build a minimal callback query stub."""
    query = SimpleNamespace()
    query.from_user = SimpleNamespace(id=user_id)
    query.message = SimpleNamespace(reply_document=AsyncMock())
    query.edit_message_text = AsyncMock()
    return query


def _build_context(
    exporter,
    session_id: str | None = "session-abc-123",
    *,
    user_id: int = 1001,
):
    """Build a minimal callback context stub."""
    scope_key = f"{user_id}:{user_id}:0"
    scope_state = {}
    if session_id is not None:
        scope_state["claude_session_id"] = session_id
    return SimpleNamespace(
        bot_data={"features": _FakeFeatures(exporter)},
        user_data={"scope_state": {scope_key: scope_state}},
    )


@pytest.mark.asyncio
async def test_handle_export_callback_calls_exporter_with_correct_signature():
    """Export callback should pass user/session/format correctly and send file."""
    exporter = MagicMock()
    exporter.export_session = AsyncMock(
        return_value=ExportedSession(
            format=ExportFormat.MARKDOWN,
            content="# hello",
            filename="session_test.md",
            mime_type="text/markdown",
            size_bytes=7,
            created_at=datetime(2026, 2, 13, 5, 0, 0),
        )
    )
    query = _build_query(user_id=42)
    context = _build_context(exporter, session_id="session-xyz", user_id=42)

    await handle_export_callback(query, "markdown", context)

    exporter.export_session.assert_awaited_once_with(
        user_id=42,
        session_id="session-xyz",
        format=ExportFormat.MARKDOWN,
    )
    query.message.reply_document.assert_awaited_once()
    caption = query.message.reply_document.await_args.kwargs["caption"]
    assert "Format: MARKDOWN" in caption


@pytest.mark.asyncio
async def test_handle_export_callback_rejects_invalid_export_format():
    """Invalid export format should fail fast without exporter call."""
    exporter = MagicMock()
    exporter.export_session = AsyncMock()
    query = _build_query()
    context = _build_context(exporter)

    await handle_export_callback(query, "yaml", context)

    exporter.export_session.assert_not_awaited()
    query.edit_message_text.assert_awaited_once()
    assert "Invalid Export Format" in query.edit_message_text.await_args.args[0]


@pytest.mark.asyncio
async def test_handle_export_action_shows_format_keyboard_for_active_session():
    """Action export entry should present the real format selection keyboard."""
    exporter = MagicMock()
    query = _build_query()
    context = _build_context(exporter, session_id="session-abc-123")

    await _handle_export_action(query, context)

    query.edit_message_text.assert_awaited_once()
    kwargs = query.edit_message_text.await_args.kwargs
    reply_markup = kwargs["reply_markup"]
    keyboard = reply_markup.inline_keyboard
    assert keyboard[0][0].callback_data == "export:markdown"
    assert keyboard[0][1].callback_data == "export:html"
    assert keyboard[1][0].callback_data == "export:json"
    assert keyboard[1][1].callback_data == "export:cancel"
