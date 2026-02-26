"""CC-Switch provider management for Telegram-side API provider switching.

Reads and updates the cc-switch desktop app's SQLite database and settings
to switch Claude Code API providers (relay stations) from Telegram.

Consistency model (per Battle Loop consensus):
- A (~/.claude/settings.json) + B (cc-switch.db is_current): strong consistency
- C (~/.cc-switch/settings.json): eventual consistency
- Authority source: B (DB). Startup self-check repairs A/C drift.
"""

import asyncio
import fcntl
import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()

# cc-switch data paths
CC_SWITCH_DB_PATH = Path.home() / ".cc-switch" / "cc-switch.db"
CC_SWITCH_SETTINGS_PATH = Path.home() / ".cc-switch" / "settings.json"
CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
PROVIDER_LOCK_PATH = Path.home() / ".cc-switch" / "provider-switch.lock"

# Settings key mapping: app_type -> settings.json key
_CURRENT_PROVIDER_KEYS: Dict[str, str] = {
    "claude": "currentProviderClaude",
    "codex": "currentProviderCodex",
    "gemini": "currentProviderGemini",
}


@dataclass
class ProviderInfo:
    """Summarized provider information for display."""

    id: str
    name: str
    app_type: str
    is_current: bool
    base_url: Optional[str]
    sort_index: Optional[int]


@dataclass
class SwitchResult:
    """Result of a provider switch operation."""

    status: str  # "OK", "FAILED", "DEGRADED"
    provider_name: Optional[str] = None
    base_url: Optional[str] = None
    error: Optional[str] = None


class _ProviderSwitchLock:
    """Process-internal asyncio.Lock + cross-process fcntl.flock."""

    def __init__(self) -> None:
        self._async_lock = asyncio.Lock()
        self._lock_fd: Optional[int] = None

    async def acquire(self) -> None:
        await self._async_lock.acquire()
        PROVIDER_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = os.open(str(PROVIDER_LOCK_PATH), os.O_CREAT | os.O_RDWR)
        self._lock_fd = lock_fd
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: fcntl.flock(lock_fd, fcntl.LOCK_EX))

    def release(self) -> None:
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(self._lock_fd)
            except OSError:
                pass
            self._lock_fd = None
        if self._async_lock.locked():
            self._async_lock.release()


def _atomic_write(target: Path, content: str) -> None:
    """Write content to file atomically: tmpfile + fsync + os.replace."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path_str = tempfile.mkstemp(
        dir=str(target.parent), suffix=".tmp", prefix=".settings_"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path_str, str(target))
    except Exception:
        try:
            os.unlink(tmp_path_str)
        except OSError:
            pass
        raise


def _atomic_write_json(target: Path, data: Any) -> None:
    """Write JSON object to file atomically."""
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    _atomic_write(target, content)


class CCSwitchManager:
    """Manage cc-switch providers: list, switch, and sync configuration files.

    Thread-safety: all mutations go through _ProviderSwitchLock (dual lock).
    """

    def __init__(self) -> None:
        self._lock = _ProviderSwitchLock()
        self.provider_ready = asyncio.Event()
        self.provider_ready.set()
        self.provider_generation: int = 0
        self._degraded: bool = False

    # ------------------------------------------------------------------
    # Read-only queries
    # ------------------------------------------------------------------

    @staticmethod
    def is_available() -> bool:
        """Check whether cc-switch database exists."""
        return CC_SWITCH_DB_PATH.exists()

    @staticmethod
    def _parse_base_url(settings_config_raw: str) -> Optional[str]:
        """Extract ANTHROPIC_BASE_URL from a provider's settings_config JSON."""
        try:
            config = json.loads(settings_config_raw)
            value = config.get("env", {}).get("ANTHROPIC_BASE_URL")
            return str(value) if isinstance(value, str) else None
        except (json.JSONDecodeError, AttributeError):
            return None

    async def list_providers(self, app_type: str = "claude") -> List[ProviderInfo]:
        """List all providers for the given app_type."""
        import aiosqlite

        if not self.is_available():
            return []

        try:
            async with aiosqlite.connect(str(CC_SWITCH_DB_PATH)) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT id, name, app_type, is_current,"
                    " settings_config, sort_index"
                    " FROM providers WHERE app_type = ?"
                    " ORDER BY sort_index, name",
                    (app_type,),
                )
                rows = await cursor.fetchall()

            return [
                ProviderInfo(
                    id=row["id"],
                    name=row["name"],
                    app_type=row["app_type"],
                    is_current=bool(row["is_current"]),
                    base_url=self._parse_base_url(row["settings_config"]),
                    sort_index=row["sort_index"],
                )
                for row in rows
            ]
        except Exception as e:
            logger.error("Failed to list cc-switch providers", error=str(e))
            return []

    async def get_current_provider(
        self, app_type: str = "claude"
    ) -> Optional[ProviderInfo]:
        """Return the currently active provider."""
        providers = await self.list_providers(app_type)
        for p in providers:
            if p.is_current:
                return p
        return None

    # ------------------------------------------------------------------
    # Switch mutation
    # ------------------------------------------------------------------

    async def switch_provider(
        self, provider_id: str, app_type: str = "claude"
    ) -> SwitchResult:
        """Switch to the specified provider with full consistency guarantees.

        Steps (ordered):
        1. Acquire dual lock
        2. Clear provider_ready (block new queries)
        3. Read + backup current A
        4. Write new A (atomic)
        5. DB transaction: update is_current
        6. Write C (eventual consistency, non-fatal)
        7. Bump provider_generation
        8. Restore provider_ready
        9. Release dual lock
        """
        if self._degraded:
            return SwitchResult(
                status="DEGRADED",
                error="Provider switch is disabled due to previous rollback failure. "
                "Manual repair required.",
            )

        if not self.is_available():
            return SwitchResult(status="FAILED", error="cc-switch database not found")

        tx_id = uuid.uuid4().hex[:8]
        log = logger.bind(tx_id=tx_id, new_provider=provider_id, app_type=app_type)

        await self._lock.acquire()
        self.provider_ready.clear()
        try:
            return await self._do_switch(provider_id, app_type, tx_id, log)
        finally:
            self.provider_ready.set()
            self._lock.release()

    async def _do_switch(
        self,
        provider_id: str,
        app_type: str,
        tx_id: str,
        log: Any,
    ) -> SwitchResult:
        """Core switch logic executed under dual lock."""
        import aiosqlite

        # Step 3: Backup current A
        old_a_content: Optional[str] = None
        if CLAUDE_SETTINGS_PATH.exists():
            try:
                old_a_content = CLAUDE_SETTINGS_PATH.read_text(encoding="utf-8")
            except Exception as e:
                log.warning("provider_switch_backup_a_failed", error=str(e))

        # Read target provider config from DB
        async with aiosqlite.connect(str(CC_SWITCH_DB_PATH)) as db:
            await db.execute("PRAGMA busy_timeout = 5000")

            cursor = await db.execute(
                "SELECT name, settings_config FROM providers "
                "WHERE id = ? AND app_type = ?",
                (provider_id, app_type),
            )
            row = await cursor.fetchone()
            if not row:
                return SwitchResult(
                    status="FAILED",
                    error=f"Provider {provider_id} not found",
                )

            provider_name = row[0]
            settings_config_raw = row[1]

            try:
                settings_config = json.loads(settings_config_raw)
            except json.JSONDecodeError as e:
                return SwitchResult(
                    status="FAILED",
                    error=f"Invalid provider config JSON: {e}",
                )

            base_url = (settings_config.get("env") or {}).get("ANTHROPIC_BASE_URL")

            # Step 4: Write A (atomic)
            log.info("provider_switch_write_a")
            try:
                _atomic_write_json(CLAUDE_SETTINGS_PATH, settings_config)
            except Exception as e:
                log.error("provider_switch_write_a_failed", error=str(e))
                return SwitchResult(
                    status="FAILED",
                    error=f"Failed to write settings: {e}",
                )

            # Step 5-6: DB transaction
            try:
                log.info("provider_switch_db_commit")
                await db.execute(
                    "UPDATE providers SET is_current = 0 WHERE app_type = ?",
                    (app_type,),
                )
                await db.execute(
                    "UPDATE providers SET is_current = 1 "
                    "WHERE id = ? AND app_type = ?",
                    (provider_id, app_type),
                )
                await db.commit()
            except Exception as db_err:
                log.error("provider_switch_db_failed", error=str(db_err))
                # Rollback A
                if old_a_content is not None:
                    try:
                        _atomic_write(CLAUDE_SETTINGS_PATH, old_a_content)
                        log.info("provider_switch_a_rollback_ok")
                    except Exception as rollback_err:
                        log.critical(
                            "provider_switch_degraded",
                            rollback_error=str(rollback_err),
                        )
                        self._degraded = True
                        return SwitchResult(
                            status="DEGRADED",
                            error=f"DB failed and rollback failed: {rollback_err}",
                        )
                return SwitchResult(
                    status="FAILED",
                    error=f"DB update failed: {db_err}",
                )

        # Step 7: Write C (eventual consistency, non-fatal)
        try:
            log.info("provider_switch_write_c")
            self._update_cc_switch_settings(provider_id, app_type)
        except Exception as c_err:
            log.warning("provider_switch_c_repair_needed", error=str(c_err))
            asyncio.get_event_loop().call_later(
                1.0,
                lambda: asyncio.ensure_future(
                    self._repair_c(provider_id, app_type, max_retries=3)
                ),
            )

        # Step 8: Bump generation
        self.provider_generation += 1
        log.info(
            "provider_switch_complete",
            generation=self.provider_generation,
            provider_name=provider_name,
            base_url=base_url,
        )

        return SwitchResult(
            status="OK",
            provider_name=provider_name,
            base_url=base_url,
        )

    # ------------------------------------------------------------------
    # C repair (eventual consistency)
    # ------------------------------------------------------------------

    async def _repair_c(
        self, provider_id: str, app_type: str, max_retries: int = 3
    ) -> None:
        """Background retry to repair C after initial failure."""
        for attempt in range(1, max_retries + 1):
            try:
                self._update_cc_switch_settings(provider_id, app_type)
                logger.info(
                    "provider_switch_c_repaired",
                    provider_id=provider_id,
                    attempt=attempt,
                )
                return
            except Exception as e:
                logger.warning(
                    "provider_switch_c_repair_retry",
                    attempt=attempt,
                    max_retries=max_retries,
                    error=str(e),
                )
                if attempt < max_retries:
                    await asyncio.sleep(1.0)

        logger.error(
            "provider_switch_c_repair_exhausted",
            provider_id=provider_id,
            max_retries=max_retries,
        )

    @staticmethod
    def _update_cc_switch_settings(provider_id: str, app_type: str) -> None:
        """Update the currentProvider key in ~/.cc-switch/settings.json."""
        key = _CURRENT_PROVIDER_KEYS.get(app_type)
        if not key or not CC_SWITCH_SETTINGS_PATH.exists():
            return

        raw = CC_SWITCH_SETTINGS_PATH.read_text(encoding="utf-8")
        settings = json.loads(raw)
        settings[key] = provider_id
        _atomic_write_json(CC_SWITCH_SETTINGS_PATH, settings)

    # ------------------------------------------------------------------
    # Startup self-check
    # ------------------------------------------------------------------

    async def startup_consistency_check(self) -> None:
        """Repair A/C drift using B (DB) as authority source.

        Called once at bot startup before accepting requests.
        """
        import aiosqlite

        if not self.is_available():
            logger.info("cc-switch not available, skipping consistency check")
            return

        try:
            async with aiosqlite.connect(str(CC_SWITCH_DB_PATH)) as db:
                await db.execute("PRAGMA busy_timeout = 5000")
                cursor = await db.execute(
                    "SELECT id, settings_config FROM providers "
                    "WHERE app_type = 'claude' AND is_current = 1 LIMIT 1",
                )
                row = await cursor.fetchone()

            if not row:
                logger.info("No current provider in cc-switch DB, skipping self-check")
                return

            provider_id = row[0]
            expected_config_raw = row[1]

            try:
                expected_config = json.loads(expected_config_raw)
            except json.JSONDecodeError:
                logger.warning(
                    "startup_consistency_check: invalid settings_config in DB",
                    provider_id=provider_id,
                )
                return

            # Check A
            if CLAUDE_SETTINGS_PATH.exists():
                try:
                    current_a = json.loads(
                        CLAUDE_SETTINGS_PATH.read_text(encoding="utf-8")
                    )
                    current_base_url = (current_a.get("env") or {}).get(
                        "ANTHROPIC_BASE_URL"
                    )
                    expected_base_url = (expected_config.get("env") or {}).get(
                        "ANTHROPIC_BASE_URL"
                    )
                    if current_base_url != expected_base_url:
                        logger.warning(
                            "startup_consistency_drift_a",
                            current_url=current_base_url,
                            expected_url=expected_base_url,
                            provider_id=provider_id,
                        )
                        _atomic_write_json(CLAUDE_SETTINGS_PATH, expected_config)
                        logger.info("startup_consistency_a_repaired")
                except Exception as e:
                    logger.warning("startup_consistency_check_a_failed", error=str(e))

            # Check C
            key = _CURRENT_PROVIDER_KEYS.get("claude")
            if key and CC_SWITCH_SETTINGS_PATH.exists():
                try:
                    c_data = json.loads(
                        CC_SWITCH_SETTINGS_PATH.read_text(encoding="utf-8")
                    )
                    if c_data.get(key) != provider_id:
                        logger.warning(
                            "startup_consistency_drift_c",
                            current=c_data.get(key),
                            expected=provider_id,
                        )
                        c_data[key] = provider_id
                        _atomic_write_json(CC_SWITCH_SETTINGS_PATH, c_data)
                        logger.info("startup_consistency_c_repaired")
                except Exception as e:
                    logger.warning("startup_consistency_check_c_failed", error=str(e))

        except Exception as e:
            logger.error("startup_consistency_check_failed", error=str(e))
