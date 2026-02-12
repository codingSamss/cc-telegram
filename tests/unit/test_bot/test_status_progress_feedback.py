"""Tests for status loading feedback in command and callback handlers."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.bot.handlers.callback import _handle_status_action
from src.bot.handlers.command import (
    _build_status_full_payload,
    _render_status_full_text,
    session_status,
)


@pytest.mark.asyncio
async def test_session_status_shows_loading_message_before_final_output(tmp_path):
    """The /status command should send immediate loading feedback."""
    approved = tmp_path / "approved"
    approved.mkdir()

    status_msg = SimpleNamespace(edit_text=AsyncMock())
    message = SimpleNamespace(reply_text=AsyncMock(return_value=status_msg))
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=1001),
        message=message,
    )
    context = SimpleNamespace(
        bot_data={"settings": SimpleNamespace(approved_directory=approved)},
        user_data={},
    )

    await session_status(update, context)

    message.reply_text.assert_awaited_once_with("⏳ 正在获取会话状态，请稍候...")
    status_msg.edit_text.assert_awaited_once()
    assert "Session: none" in status_msg.edit_text.await_args.args[0]
    assert "reply_markup" not in status_msg.edit_text.await_args.kwargs


@pytest.mark.asyncio
async def test_status_callback_shows_loading_message_before_refresh_result(tmp_path):
    """Status callback should first show a refreshing indicator."""
    approved = tmp_path / "approved"
    approved.mkdir()

    query = SimpleNamespace(edit_message_text=AsyncMock())
    context = SimpleNamespace(
        bot_data={"settings": SimpleNamespace(approved_directory=approved)},
        user_data={},
    )

    await _handle_status_action(query, context)

    assert query.edit_message_text.await_count == 2
    calls = query.edit_message_text.await_args_list
    assert "正在刷新状态" in calls[0].args[0]
    assert "Session: none" in calls[1].args[0]
    assert "reply_markup" not in calls[1].kwargs


@pytest.mark.asyncio
async def test_session_status_full_mode_renders_full_payload(tmp_path):
    """`/context full` should include full structured context/session payload."""
    approved = tmp_path / "approved"
    approved.mkdir()

    status_msg = SimpleNamespace(edit_text=AsyncMock())
    message = SimpleNamespace(reply_text=AsyncMock(return_value=status_msg))
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=1001),
        message=message,
    )
    claude_integration = SimpleNamespace(
        get_precise_context_usage=AsyncMock(
            return_value={
                "used_tokens": 55_000,
                "total_tokens": 200_000,
                "remaining_tokens": 145_000,
                "used_percent": 27.5,
                "raw_text": "Context usage: 27.5% (55,000 / 200,000 tokens)",
                "session_id": "session-abcdef123",
                "cached": False,
            }
        ),
        get_session_info=AsyncMock(
            return_value={
                "session_id": "session-abcdef123",
                "messages": 3,
                "turns": 2,
                "cost": 0.1234,
                "model_usage": {"sdk": {"inputTokens": 111, "outputTokens": 22}},
            }
        ),
    )
    context = SimpleNamespace(
        bot_data={
            "settings": SimpleNamespace(approved_directory=approved),
            "claude_integration": claude_integration,
        },
        user_data={
            "claude_session_id": "session-abcdef123",
            "current_directory": approved,
            "claude_model": "sonnet",
        },
        args=["full"],
    )

    await session_status(update, context)

    rendered = status_msg.edit_text.await_args.args[0]
    assert rendered.startswith("Session Status (full)")
    assert "[/context Structured Summary]" in rendered
    assert "No markdown table summary detected in /context output." in rendered
    assert "used_tokens: 55,000" in rendered
    assert "total_tokens: 200,000" in rendered
    assert "messages: 3" in rendered
    assert "[Raw Payload JSON]" not in rendered
    assert "Context usage: 27.5% (55,000 / 200,000 tokens)" not in rendered
    assert status_msg.edit_text.await_args.kwargs["parse_mode"] is None


def test_render_status_full_text_summarizes_mcp_table():
    """Full context rendering should summarize MCP table payload."""
    raw_text = (
        "## Context Usage\n\n"
        "### Estimated usage by category\n\n"
        "| Category | Tokens | Percentage |\n"
        "|----------|--------|------------|\n"
        "| System tools | 22.3k | 11.1% |\n"
        "| Messages | 7.2k | 3.6% |\n"
        "| Free space | 132.5k | 66.2% |\n\n"
        "### MCP Tools\n\n"
        "| Tool | Server | Tokens |\n"
        "|------|--------|--------|\n"
        "| mcp__a | notion-local | 1.5k |\n"
        "| mcp__b | notion-local | 800 |\n"
        "| mcp__c | codex | 700 |\n"
    )
    payload = _build_status_full_payload(
        relative_path=Path("."),
        current_model="default",
        claude_session_id="session-1",
        precise_context={
            "used_tokens": 33_600,
            "total_tokens": 200_000,
            "remaining_tokens": 166_400,
            "used_percent": 16.8,
            "raw_text": raw_text,
            "session_id": "session-1",
            "cached": False,
        },
        info={
            "project": "/tmp",
            "created": "2026-02-12T10:00:00",
            "last_used": "2026-02-12T10:05:00",
            "cost": 0.1,
            "turns": 1,
            "messages": 1,
            "expired": False,
            "tools_used": [],
            "model_usage": {},
        },
        resumable_payload=None,
    )

    rendered = _render_status_full_text(payload)
    assert "[/context Structured Summary]" in rendered
    assert "[Estimated Usage by Category]" in rendered
    assert "[MCP Tools Summary]" in rendered
    assert "tool_count: 3" in rendered
    assert "- notion-local: 2,300 tokens / 2 tools" in rendered
