"""Tests for streaming progress text formatting."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock

import pytest

from src.bot.handlers.message import (
    _append_progress_line_with_merge,
    _build_context_tag,
    _format_error_message,
    _format_progress_update,
    _get_stream_merge_key,
    _is_high_priority_stream_update,
    _is_markdown_parse_error,
    _is_noop_edit_error,
    _reply_text_resilient,
    _split_text_for_telegram,
    _with_engine_badge,
)
from src.bot.utils.cli_engine import ENGINE_CLAUDE, ENGINE_CODEX


@dataclass
class _FakeUpdate:
    type: str
    metadata: Optional[dict] = None
    content: Optional[str] = None
    tool_calls: Optional[list] = None
    progress: Optional[dict] = None
    error_info: Optional[dict] = None

    def is_error(self) -> bool:
        return False

    def get_error_message(self):
        return self.content or ""

    def get_progress_percentage(self):
        if self.progress:
            return self.progress.get("percentage")
        return None


@pytest.mark.asyncio
async def test_init_progress_text_does_not_show_stale_model_name():
    """Init line should stay generic and not claim a specific model."""
    update = _FakeUpdate(
        type="system",
        metadata={
            "subtype": "init",
            "tools": ["Read", "Write"],
            "model": "claude-3-5-sonnet-20241022",
        },
    )
    text = await _format_progress_update(update)
    assert text == "🚀 *Starting Claude* with 2 tools available"


@pytest.mark.asyncio
async def test_model_resolved_progress_text_uses_using_model_label():
    """Resolved model line should explicitly show the actual model in use."""
    update = _FakeUpdate(
        type="system",
        metadata={
            "subtype": "model_resolved",
            "model": "claude-opus-4-1",
        },
    )
    text = await _format_progress_update(update)
    assert text == "🧠 *Using model:* claude-opus-4-1"


@pytest.mark.asyncio
async def test_assistant_progress_text_uses_codex_label_when_metadata_present():
    """Assistant streaming line should show Codex label for codex metadata."""
    update = _FakeUpdate(
        type="assistant",
        content="partial response",
        metadata={"engine": "codex"},
    )

    text = await _format_progress_update(update)

    assert text is not None
    assert text.startswith("🤖 *Codex is working...*")


@pytest.mark.asyncio
async def test_progress_command_execution_renders_compact_running_line():
    """Codex command execution updates should render compact command status."""
    update = _FakeUpdate(
        type="progress",
        content="/bin/zsh -lc 'cd /tmp && ls'",
        metadata={
            "item_type": "command_execution",
            "status": "in_progress",
            "command": "/bin/zsh -lc 'cd /tmp && ls'",
            "engine": "codex",
        },
    )

    text = await _format_progress_update(update)

    assert text is not None
    assert text.startswith("🔧 *Running command*")
    assert "/bin/zsh -lc" in text


@pytest.mark.asyncio
async def test_progress_command_execution_renders_completion_exit_code():
    """Completed command update should include exit code in rendered line."""
    update = _FakeUpdate(
        type="progress",
        content="/bin/zsh -lc 'pwd'",
        metadata={
            "item_type": "command_execution",
            "status": "completed",
            "command": "/bin/zsh -lc 'pwd'",
            "exit_code": 0,
            "engine": "codex",
        },
    )

    text = await _format_progress_update(update)

    assert text is not None
    assert text.startswith("✅ *Command completed*")
    assert "exit 0" in text


def test_get_stream_merge_key_for_mergeable_events():
    """Progress and assistant plain content should be mergeable."""
    assistant_update = _FakeUpdate(
        type="assistant",
        content="partial",
        tool_calls=None,
    )
    progress_update = _FakeUpdate(type="progress", content="working")
    tool_update = _FakeUpdate(
        type="assistant",
        content=None,
        tool_calls=[{"name": "Read"}],
    )

    assert _get_stream_merge_key(assistant_update) == "assistant_content"
    assert _get_stream_merge_key(progress_update) == "progress"
    assert _get_stream_merge_key(tool_update) is None


def test_append_progress_line_with_merge_merges_only_consecutive_same_key():
    """Same merge key should replace previous line; other keys should append."""
    lines: list[str] = []
    merge_keys: list[Optional[str]] = []

    _append_progress_line_with_merge(
        progress_lines=lines,
        progress_merge_keys=merge_keys,
        progress_text="🤖 first",
        merge_key="assistant_content",
    )
    _append_progress_line_with_merge(
        progress_lines=lines,
        progress_merge_keys=merge_keys,
        progress_text="🤖 second",
        merge_key="assistant_content",
    )
    _append_progress_line_with_merge(
        progress_lines=lines,
        progress_merge_keys=merge_keys,
        progress_text="🔄 step 1",
        merge_key="progress",
    )
    _append_progress_line_with_merge(
        progress_lines=lines,
        progress_merge_keys=merge_keys,
        progress_text="🔄 step 2",
        merge_key="progress",
    )
    _append_progress_line_with_merge(
        progress_lines=lines,
        progress_merge_keys=merge_keys,
        progress_text="✅ done",
        merge_key=None,
    )
    _append_progress_line_with_merge(
        progress_lines=lines,
        progress_merge_keys=merge_keys,
        progress_text="✅ done again",
        merge_key=None,
    )

    assert lines == ["🤖 second", "🔄 step 2", "✅ done", "✅ done again"]
    assert merge_keys == ["assistant_content", "progress", None, None]


def test_append_progress_line_with_merge_skips_exact_consecutive_duplicates():
    """Exact duplicates should be skipped to reduce noisy edits."""
    lines: list[str] = []
    merge_keys: list[Optional[str]] = []

    _append_progress_line_with_merge(
        progress_lines=lines,
        progress_merge_keys=merge_keys,
        progress_text="🔧 Read: `a.py`",
        merge_key=None,
    )
    _append_progress_line_with_merge(
        progress_lines=lines,
        progress_merge_keys=merge_keys,
        progress_text="🔧 Read: `a.py`",
        merge_key=None,
    )

    assert lines == ["🔧 Read: `a.py`"]
    assert merge_keys == [None]


def test_high_priority_stream_update_detection():
    """High-priority updates should bypass debounce for snappier feedback."""
    error_update = _FakeUpdate(type="error", content="boom")
    tool_result_update = _FakeUpdate(type="tool_result", content="done")
    tool_call_update = _FakeUpdate(
        type="assistant",
        tool_calls=[{"name": "Read", "input": {"file_path": "x.py"}}],
    )
    system_init = _FakeUpdate(type="system", metadata={"subtype": "init"})
    system_model = _FakeUpdate(type="system", metadata={"subtype": "model_resolved"})
    plain_progress = _FakeUpdate(type="progress", content="working")

    assert _is_high_priority_stream_update(error_update) is True
    assert _is_high_priority_stream_update(tool_result_update) is True
    assert _is_high_priority_stream_update(tool_call_update) is True
    assert _is_high_priority_stream_update(system_init) is True
    assert _is_high_priority_stream_update(system_model) is True
    assert _is_high_priority_stream_update(plain_progress) is False


def test_noop_edit_error_detection():
    """Should detect Telegram 'message is not modified' edit rejection."""
    assert _is_noop_edit_error(Exception("Message is not modified")) is True
    assert (
        _is_noop_edit_error(Exception("Bad Request: message is not modified")) is True
    )
    assert _is_noop_edit_error(Exception("network timeout")) is False


def test_markdown_parse_error_detection():
    """Markdown parsing errors should be detected for fallback retry."""
    assert _is_markdown_parse_error(Exception("Bad Request: can't parse entities"))
    assert _is_markdown_parse_error(Exception("cannot parse entities")) is True
    assert _is_markdown_parse_error(Exception("Message is too long")) is False


def test_split_text_for_telegram_splits_long_text():
    """Long text should be split into safe chunks under Telegram limit."""
    text = "a" * 8000
    chunks = _split_text_for_telegram(text, limit=3900)
    assert len(chunks) == 3
    assert sum(len(chunk) for chunk in chunks) == len(text)
    assert all(len(chunk) <= 3900 for chunk in chunks)


@pytest.mark.asyncio
async def test_reply_text_resilient_retries_without_markdown_parse_mode():
    """Markdown parse failure should fallback to plain text send."""
    message = type("FakeMessage", (), {})()
    message.reply_text = AsyncMock(
        side_effect=[Exception("Bad Request: can't parse entities"), object()]
    )

    await _reply_text_resilient(
        message, "codex_core::rollout::list", parse_mode="Markdown"
    )

    assert message.reply_text.await_count == 2
    assert message.reply_text.await_args_list[0].kwargs["parse_mode"] == "Markdown"
    assert "parse_mode" not in message.reply_text.await_args_list[1].kwargs


@pytest.mark.asyncio
async def test_reply_text_resilient_splits_when_message_too_long():
    """Too-long errors should fallback to chunked plain text sending."""
    message = type("FakeMessage", (), {})()

    async def _reply_text_side_effect(text: str, **kwargs):
        if len(text) > 4096:
            raise Exception("Bad Request: message is too long")
        return object()

    message.reply_text = AsyncMock(side_effect=_reply_text_side_effect)
    text = "x" * 9000

    await _reply_text_resilient(message, text, parse_mode=None)

    assert message.reply_text.await_count == 4
    first_call = message.reply_text.await_args_list[0]
    assert len(first_call.args[0]) == 9000
    split_calls = message.reply_text.await_args_list[1:]
    assert all(len(call.args[0]) <= 3900 for call in split_calls)


def test_format_error_message_uses_codex_label_for_generic_errors():
    """Codex generic error should not render Claude-branded header."""
    text = _format_error_message("mcp backend crashed", engine=ENGINE_CODEX)
    assert "Codex CLI Error" in text
    assert "Claude Code Error" not in text


def test_format_error_message_uses_status_command_for_codex_hints():
    """Codex error hints should point to /status instead of /context."""
    text = _format_error_message("rate limit reached", engine=ENGINE_CODEX)
    assert "/status" in text
    assert "/context" not in text


def test_build_context_tag_renders_codex_badge():
    """Context tag should include Codex badge for Codex engine responses."""
    tag = _build_context_tag(
        scope_state={"current_directory": Path("/tmp/demo-project")},
        approved_directory=Path("/tmp"),
        active_engine=ENGINE_CODEX,
        session_id="session-codex-123456",
    )

    assert "🟦 `Codex CLI`" in tag
    assert "`demo-project`" in tag


def test_build_context_tag_renders_claude_badge():
    """Context tag should include Claude badge for Claude engine responses."""
    tag = _build_context_tag(
        scope_state={"current_directory": Path("/tmp/claude-project")},
        approved_directory=Path("/tmp"),
        active_engine=ENGINE_CLAUDE,
        session_id="session-claude-123456",
    )

    assert "🟩 `Claude CLI`" in tag
    assert "`claude-project`" in tag


def test_build_context_tag_shows_rate_limit_summary():
    """Context tag should append rate limit info when provided."""
    summary = "5h window: 12.5% · 7d window: 37.0% (updated 2026-02-09T13:54:15Z)"
    tag = _build_context_tag(
        scope_state={"current_directory": Path("/tmp/demo-project")},
        approved_directory=Path("/tmp"),
        active_engine=ENGINE_CODEX,
        session_id="session-codex-123456",
        rate_limit_summary=summary,
    )

    assert "🔋" in tag
    assert summary in tag


def test_with_engine_badge_prefixes_codex_bubble():
    """Engine badge helper should prepend codex marker to bubble text."""
    text = _with_engine_badge("正在处理你的请求...", ENGINE_CODEX)
    assert text.startswith("🟦 `Codex CLI`")
    assert "正在处理你的请求..." in text


def test_with_engine_badge_handles_empty_body():
    """Engine badge helper should still return badge when body is empty."""
    text = _with_engine_badge("", ENGINE_CLAUDE)
    assert text == "🟩 `Claude CLI`"
