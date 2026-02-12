"""Tests for image processing status helpers and callbacks."""

import pytest

from src.bot.features.image_handler import ImageHandler
from src.bot.handlers.message import (
    _build_image_analyzing_status,
    _format_elapsed_time,
    _image_heartbeat_interval_seconds,
)
from src.config.settings import Settings


def test_format_elapsed_time():
    """Elapsed time should be formatted as mm:ss."""
    assert _format_elapsed_time(0) == "00:00"
    assert _format_elapsed_time(9) == "00:09"
    assert _format_elapsed_time(65) == "01:05"


def test_image_heartbeat_interval_seconds():
    """Heartbeat interval should adapt by elapsed time window."""
    assert _image_heartbeat_interval_seconds(0) == 6
    assert _image_heartbeat_interval_seconds(29) == 6
    assert _image_heartbeat_interval_seconds(30) == 12
    assert _image_heartbeat_interval_seconds(89) == 12
    assert _image_heartbeat_interval_seconds(90) == 20


def test_build_image_analyzing_status_includes_slow_hint():
    """Slow-analysis hint should only appear after long wait."""
    short_text = _build_image_analyzing_status(30)
    long_text = _build_image_analyzing_status(95)

    assert "响应时间较长" not in short_text
    assert "响应时间较长" in long_text


class _FakeTelegramFile:
    """Fake Telegram file for image handler tests."""

    async def download_as_bytearray(self):
        # Valid JPEG header + payload > 100 bytes
        return b"\xff\xd8\xff" + b"\x00" * 256


class _FakePhoto:
    """Fake Telegram photo object with get_file()."""

    async def get_file(self):
        return _FakeTelegramFile()


@pytest.mark.asyncio
async def test_image_handler_progress_callback_order(tmp_path):
    """Image handler should emit progress events in expected order."""
    settings = Settings(
        telegram_bot_token="test:token",
        telegram_bot_username="testbot",
        approved_directory=tmp_path,
        use_sdk=True,
    )
    handler = ImageHandler(settings)

    events: list[str] = []

    async def on_progress(stage: str):
        events.append(stage)

    result = await handler.process_image(
        photo=_FakePhoto(),
        caption="请分析这张图片",
        on_progress=on_progress,
    )

    assert events == ["downloading", "validating", "encoding"]
    assert result.prompt == "请分析这张图片"
    assert result.metadata["format"] == "jpeg"
    assert len(result.base64_data) > 0
