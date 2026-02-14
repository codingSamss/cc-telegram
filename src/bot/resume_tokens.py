"""Short-lived token manager for /resume callback_data.

Telegram callback_data has a 64-byte limit, so we map short tokens
(resume:p:<idx>, resume:s:<idx>, resume:f:<idx>) to actual payloads.
Tokens are bound to a user_id, single-use, and expire after a TTL.
"""

import copy
import time
from dataclasses import dataclass
from typing import Dict, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class _TokenEntry:
    kind: str
    user_id: int
    payload: dict
    created_at: float
    ttl_sec: int
    consumed: bool = False


class ResumeTokenManager:
    """Issue and resolve short-lived tokens for /resume inline buttons."""

    VALID_KINDS = {"p", "s", "f", "n"}
    _PURGE_INTERVAL = 50  # auto-purge every N issue() calls

    def __init__(self) -> None:
        self._counter: int = 0
        self._store: Dict[str, _TokenEntry] = {}
        self._issue_since_purge: int = 0

    def issue(
        self,
        *,
        kind: str,
        user_id: int,
        payload: dict,
        ttl_sec: int = 600,
    ) -> str:
        """Issue a short token bound to user_id.

        Args:
            kind: Token kind - "p" (project), "s" (session), "f" (force confirm),
                "n" (start new session).
            user_id: Telegram user ID the token is bound to.
            payload: Arbitrary data to store (e.g. project path, session id).
            ttl_sec: Time-to-live in seconds (default 10 minutes).

        Returns:
            The token index string (e.g. "0", "1", "2").
        """
        if kind not in self.VALID_KINDS:
            raise ValueError(
                f"Invalid token kind: {kind!r}, must be one of {self.VALID_KINDS}"
            )
        if ttl_sec <= 0:
            raise ValueError(f"ttl_sec must be positive, got {ttl_sec}")

        # Auto-purge periodically
        self._issue_since_purge += 1
        if self._issue_since_purge >= self._PURGE_INTERVAL:
            self.purge_expired()
            self._issue_since_purge = 0

        idx = self._counter
        self._counter += 1
        token = str(idx)

        self._store[f"{kind}:{token}"] = _TokenEntry(
            kind=kind,
            user_id=user_id,
            payload=copy.copy(payload),
            created_at=time.monotonic(),
            ttl_sec=ttl_sec,
        )

        logger.debug(
            "Resume token issued",
            kind=kind,
            token=token,
            user_id=user_id,
        )
        return token

    def resolve(
        self,
        *,
        kind: str,
        user_id: int,
        token: str,
        consume: bool = True,
    ) -> Optional[dict]:
        """Resolve a token, returning its payload or None.

        Checks kind, user_id, expiry, and consumed status.
        If consume=True (default), the token is marked consumed after
        successful resolution (single-use).
        """
        key = f"{kind}:{token}"
        entry = self._store.get(key)

        if entry is None:
            return None

        # Validate kind and user
        if entry.kind != kind or entry.user_id != user_id:
            return None

        # Check consumed
        if entry.consumed:
            return None

        # Check expiry
        elapsed = time.monotonic() - entry.created_at
        if elapsed > entry.ttl_sec:
            del self._store[key]
            return None

        if consume:
            entry.consumed = True

        return copy.copy(entry.payload)

    def purge_expired(self) -> int:
        """Remove all expired or consumed entries. Returns count removed."""
        now = time.monotonic()
        to_remove = [
            key
            for key, entry in self._store.items()
            if entry.consumed or (now - entry.created_at > entry.ttl_sec)
        ]
        for key in to_remove:
            del self._store[key]

        if to_remove:
            logger.debug("Purged resume tokens", count=len(to_remove))
        return len(to_remove)
