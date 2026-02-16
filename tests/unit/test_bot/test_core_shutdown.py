"""Tests for shutdown-time task finalization in bot core."""

import asyncio
from contextlib import suppress
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.bot.core import ClaudeCodeBot
from src.claude.task_registry import TaskRegistry


async def _long_running() -> None:
    """Keep task alive until cancelled."""
    await asyncio.sleep(3600)


@pytest.mark.asyncio
async def test_finalize_running_tasks_marks_progress_message_interrupted() -> None:
    """Shutdown should mark running progress bubble as interrupted."""
    registry = TaskRegistry()
    task = asyncio.create_task(_long_running())
    scope_key = "77:-100:0"
    await registry.register(
        user_id=77,
        task=task,
        scope_key=scope_key,
        chat_id=-100123,
        progress_message_id=9001,
    )

    bot = ClaudeCodeBot(
        settings=SimpleNamespace(), dependencies={"task_registry": registry}
    )
    bot.app = SimpleNamespace(
        bot=SimpleNamespace(
            edit_message_text=AsyncMock(),
            edit_message_reply_markup=AsyncMock(),
        )
    )

    await bot._finalize_running_tasks_before_shutdown()
    await asyncio.sleep(0)

    bot.app.bot.edit_message_text.assert_awaited_once_with(
        chat_id=-100123,
        message_id=9001,
        text="⚠️ 服务已重启，本次任务已中断。请重新发送消息继续。",
        reply_markup=None,
    )
    assert await registry.is_busy(77, scope_key=scope_key) is False

    with suppress(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_finalize_running_tasks_fallbacks_to_remove_stale_button() -> None:
    """If message text edit fails, shutdown should still clear reply markup."""
    registry = TaskRegistry()
    task = asyncio.create_task(_long_running())
    scope_key = "88:-100:0"
    await registry.register(
        user_id=88,
        task=task,
        scope_key=scope_key,
        chat_id=-100456,
        progress_message_id=9002,
    )

    bot = ClaudeCodeBot(
        settings=SimpleNamespace(), dependencies={"task_registry": registry}
    )
    bot.app = SimpleNamespace(
        bot=SimpleNamespace(
            edit_message_text=AsyncMock(side_effect=RuntimeError("edit failed")),
            edit_message_reply_markup=AsyncMock(),
        )
    )

    await bot._finalize_running_tasks_before_shutdown()
    await asyncio.sleep(0)

    bot.app.bot.edit_message_reply_markup.assert_awaited_once_with(
        chat_id=-100456,
        message_id=9002,
        reply_markup=None,
    )
    assert await registry.is_busy(88, scope_key=scope_key) is False

    with suppress(asyncio.CancelledError):
        await task
