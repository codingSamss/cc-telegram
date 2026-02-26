"""Persistent store for Telegram polling update offsets."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class UpdateOffsetStore:
    """Persist last processed Telegram update id to local state file."""

    def __init__(
        self,
        state_file: Path,
        *,
        flush_interval_seconds: float = 1.0,
    ) -> None:
        self.state_file = state_file
        self.flush_interval_seconds = max(0.0, float(flush_interval_seconds))
        self._last_update_id: Optional[int] = None
        self._last_persisted_id: Optional[int] = None
        self._dirty: bool = False
        self._last_flush_at: float = 0.0

    @property
    def last_update_id(self) -> Optional[int]:
        """Latest update id recorded in memory."""
        return self._last_update_id

    def load(self) -> Optional[int]:
        """Load persisted update id from disk."""
        if not self.state_file.exists():
            return None

        payload = json.loads(self.state_file.read_text(encoding="utf-8"))
        update_id = self._parse_update_id(payload)
        self._last_update_id = update_id
        self._last_persisted_id = update_id
        self._dirty = False
        return update_id

    def record(self, update_id: int) -> None:
        """Record update id and flush to disk if needed."""
        normalized_id = int(update_id)
        if normalized_id < 0:
            return
        if self._last_update_id is not None and normalized_id <= self._last_update_id:
            return

        self._last_update_id = normalized_id
        self._dirty = True
        if self.flush_interval_seconds <= 0:
            self.flush(force=True)
            return

        now = time.monotonic()
        if now - self._last_flush_at >= self.flush_interval_seconds:
            self.flush(force=True)

    def flush(self, *, force: bool = False) -> None:
        """Persist latest update id when store has dirty changes."""
        if not self._dirty or self._last_update_id is None:
            return
        if (
            not force
            and self.flush_interval_seconds > 0
            and time.monotonic() - self._last_flush_at < self.flush_interval_seconds
        ):
            return

        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_update_id": self._last_update_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        tmp_file = self.state_file.with_suffix(f"{self.state_file.suffix}.tmp")
        tmp_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_file.replace(self.state_file)

        self._last_persisted_id = self._last_update_id
        self._dirty = False
        self._last_flush_at = time.monotonic()

    @staticmethod
    def _parse_update_id(payload: Any) -> Optional[int]:
        if isinstance(payload, int):
            return payload if payload >= 0 else None

        if isinstance(payload, dict):
            raw_update_id = payload.get("last_update_id")
            if raw_update_id is None:
                return None
            try:
                parsed = int(raw_update_id)
            except (TypeError, ValueError):
                return None
            return parsed if parsed >= 0 else None

        return None
