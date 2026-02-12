"""Tests for streaming progress text formatting."""

from dataclasses import dataclass
from typing import Optional

import pytest

from src.bot.handlers.message import (
    _append_progress_line_with_merge,
    _format_progress_update,
    _get_stream_merge_key,
)


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
