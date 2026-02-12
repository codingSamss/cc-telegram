"""Tests for streaming progress text formatting."""

from dataclasses import dataclass
from typing import Optional

import pytest

from src.bot.handlers.message import _format_progress_update


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
