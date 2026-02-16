"""Tests for inbound text/photo aggregation helpers."""

import asyncio
from types import SimpleNamespace

import pytest

from src.bot.handlers.message import (
    _collect_media_group_photos,
    _collect_text_fragments,
)


def _build_text_update(
    *,
    message_id: int,
    text: str,
    user_id: int = 7,
    chat_id: int = -100123,
    thread_id: int = 0,
):
    """Build lightweight update object for text aggregation tests."""
    message = SimpleNamespace(text=text, message_id=message_id)
    return SimpleNamespace(
        message=message,
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=chat_id),
        effective_message=SimpleNamespace(message_thread_id=thread_id),
    )


def _build_photo_update(
    *,
    message_id: int,
    photo: object,
    media_group_id: str | None,
    caption: str | None,
    user_id: int = 7,
    chat_id: int = -100123,
):
    """Build lightweight update object for media_group aggregation tests."""
    message = SimpleNamespace(
        message_id=message_id,
        photo=[photo],
        media_group_id=media_group_id,
        caption=caption,
    )
    return SimpleNamespace(
        message=message,
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=chat_id),
        effective_message=SimpleNamespace(message_thread_id=0),
    )


@pytest.mark.asyncio
async def test_collect_text_fragments_returns_immediately_for_short_text():
    """Short text should bypass buffering and return immediately."""
    context = SimpleNamespace(bot_data={})
    update = _build_text_update(message_id=101, text="hello")

    ready, merged_text, source_message_id, fragment_count = (
        await _collect_text_fragments(update, context)
    )

    assert ready is True
    assert merged_text == "hello"
    assert source_message_id == 101
    assert fragment_count == 1


@pytest.mark.asyncio
async def test_collect_text_fragments_merges_long_split_messages(monkeypatch):
    """Consecutive long fragments should be merged into one payload."""
    monkeypatch.setattr("src.bot.handlers.message._TEXT_FRAGMENT_START_LENGTH", 10)
    monkeypatch.setattr("src.bot.handlers.message._TEXT_FRAGMENT_WINDOW_SECONDS", 0.03)

    context = SimpleNamespace(bot_data={})
    update1 = _build_text_update(message_id=201, text="A" * 20)
    update2 = _build_text_update(message_id=202, text="B" * 12)

    task1 = asyncio.create_task(_collect_text_fragments(update1, context))
    await asyncio.sleep(0.005)
    task2 = asyncio.create_task(_collect_text_fragments(update2, context))

    result1 = await task1
    result2 = await task2

    assert result1[0] is False
    assert result2[0] is True
    assert result2[1] == ("A" * 20) + "\n" + ("B" * 12)
    assert result2[2] == 201
    assert result2[3] == 2


@pytest.mark.asyncio
async def test_collect_media_group_photos_merges_photo_batch(monkeypatch):
    """Only latest media_group update should emit merged photo batch."""
    monkeypatch.setattr("src.bot.handlers.message._MEDIA_GROUP_WINDOW_SECONDS", 0.03)

    context = SimpleNamespace(bot_data={})
    photo1 = object()
    photo2 = object()
    update1 = _build_photo_update(
        message_id=301,
        photo=photo1,
        media_group_id="grp-1",
        caption="请一起分析",
    )
    update2 = _build_photo_update(
        message_id=302,
        photo=photo2,
        media_group_id="grp-1",
        caption=None,
    )

    task1 = asyncio.create_task(_collect_media_group_photos(update1, context))
    await asyncio.sleep(0.005)
    task2 = asyncio.create_task(_collect_media_group_photos(update2, context))

    result1 = await task1
    result2 = await task2

    assert result1[0] is False
    assert result2[0] is True
    assert result2[1] == [photo1, photo2]
    assert result2[2] == "请一起分析"
    assert result2[3] == 301


@pytest.mark.asyncio
async def test_collect_media_group_photos_returns_single_photo_without_group():
    """Photo without media_group should be processed immediately."""
    context = SimpleNamespace(bot_data={})
    photo = object()
    update = _build_photo_update(
        message_id=401,
        photo=photo,
        media_group_id=None,
        caption=None,
    )

    ready, photos, caption, source_message_id = await _collect_media_group_photos(
        update, context
    )

    assert ready is True
    assert photos == [photo]
    assert caption is None
    assert source_message_id == 401
