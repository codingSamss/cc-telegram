"""Tests for core update dedupe/stale guard."""

from types import SimpleNamespace

import pytest
from telegram.ext import ApplicationHandlerStop

from src.bot.core import ClaudeCodeBot


@pytest.mark.asyncio
async def test_update_guard_blocks_duplicate_update():
    """Duplicate updates should be blocked by the guard."""
    bot = ClaudeCodeBot(settings=SimpleNamespace(), dependencies={})
    recorded_ids: list[int] = []
    bot._update_offset_store = SimpleNamespace(record=recorded_ids.append)

    update = SimpleNamespace(update_id=2026001)
    context = SimpleNamespace()

    await bot._handle_update_guard(update, context)
    assert recorded_ids == [2026001]

    with pytest.raises(ApplicationHandlerStop):
        await bot._handle_update_guard(update, context)

    assert recorded_ids == [2026001]


@pytest.mark.asyncio
async def test_update_guard_blocks_stale_update_before_dedupe():
    """Updates below persisted startup offset should be skipped."""
    bot = ClaudeCodeBot(settings=SimpleNamespace(), dependencies={})
    bot._startup_min_update_id = 300
    recorded_ids: list[int] = []
    bot._update_offset_store = SimpleNamespace(record=recorded_ids.append)

    stale_update = SimpleNamespace(update_id=299)

    with pytest.raises(ApplicationHandlerStop):
        await bot._handle_update_guard(stale_update, SimpleNamespace())

    assert recorded_ids == []
