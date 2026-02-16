"""Tests for Telegram update dedupe cache."""

from src.bot.utils.update_dedupe import UpdateDedupeCache


def test_update_dedupe_cache_marks_duplicates():
    """Second encounter of the same update id should be treated as duplicate."""
    cache = UpdateDedupeCache(ttl_seconds=60, max_size=100)

    assert cache.check_and_mark(101) is False
    assert cache.check_and_mark(101) is True


def test_update_dedupe_cache_evicts_by_size():
    """Oldest ids should be evicted when cache exceeds max size."""
    cache = UpdateDedupeCache(ttl_seconds=60, max_size=2)

    assert cache.check_and_mark(1) is False
    assert cache.check_and_mark(2) is False
    assert cache.check_and_mark(3) is False
    assert cache.check_and_mark(1) is False


def test_update_dedupe_cache_expires_by_ttl(monkeypatch):
    """Expired ids should no longer be considered duplicates."""
    now = [100.0]
    monkeypatch.setattr(
        "src.bot.utils.update_dedupe.time.monotonic",
        lambda: now[0],
    )
    cache = UpdateDedupeCache(ttl_seconds=1, max_size=100)

    assert cache.check_and_mark(9) is False
    assert cache.check_and_mark(9) is True

    now[0] = 102.0
    assert cache.check_and_mark(9) is False
