"""Tests for Telegram update offset persistence store."""

import json

from src.bot.utils.update_offset_store import UpdateOffsetStore


def test_update_offset_store_loads_none_when_file_missing(tmp_path):
    """Missing state file should return None."""
    state_file = tmp_path / "data" / "state" / "telegram" / "update-offset.json"
    store = UpdateOffsetStore(state_file)

    assert store.load() is None


def test_update_offset_store_persists_and_loads_latest_id(tmp_path):
    """Store should persist last update id and load it on next startup."""
    state_file = tmp_path / "data" / "state" / "telegram" / "update-offset.json"
    store = UpdateOffsetStore(state_file, flush_interval_seconds=0)
    store.record(1234)

    payload = json.loads(state_file.read_text(encoding="utf-8"))
    assert payload["last_update_id"] == 1234

    reloaded = UpdateOffsetStore(state_file)
    assert reloaded.load() == 1234


def test_update_offset_store_ignores_non_incremental_id(tmp_path):
    """Store should not downgrade offset when receiving older update ids."""
    state_file = tmp_path / "data" / "state" / "telegram" / "update-offset.json"
    store = UpdateOffsetStore(state_file, flush_interval_seconds=0)
    store.record(55)
    store.record(40)

    payload = json.loads(state_file.read_text(encoding="utf-8"))
    assert payload["last_update_id"] == 55
