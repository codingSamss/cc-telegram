"""Tests for Codex desktop resume scanner."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.bot.utils.codex_resume_scanner import CodexSessionScanner


def _write_codex_session(
    *,
    file_path: Path,
    session_id: str,
    cwd: Path,
    first_message: str,
    timestamp: datetime,
) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "timestamp": timestamp.isoformat() + "Z",
            "type": "session_meta",
            "payload": {"id": session_id, "cwd": str(cwd)},
        },
        {
            "timestamp": (timestamp + timedelta(seconds=1)).isoformat() + "Z",
            "type": "event_msg",
            "payload": {"type": "task_started"},
        },
        {
            "timestamp": (timestamp + timedelta(seconds=2)).isoformat() + "Z",
            "type": "event_msg",
            "payload": {"type": "user_message", "message": first_message},
        },
    ]
    with open(file_path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    ts = timestamp.replace(tzinfo=timezone.utc).timestamp()
    os.utime(file_path, (ts, ts))


@pytest.mark.asyncio
async def test_codex_scanner_list_projects_filters_by_approved_directory(tmp_path):
    """Only projects under approved root should be listed."""
    approved = tmp_path / "approved"
    approved.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sessions_dir = tmp_path / ".codex" / "sessions"

    now = datetime.utcnow()
    _write_codex_session(
        file_path=sessions_dir / "2026/02/14/rollout-a.jsonl",
        session_id="session-a",
        cwd=approved / "proj-a",
        first_message="hello a",
        timestamp=now,
    )
    _write_codex_session(
        file_path=sessions_dir / "2026/02/14/rollout-b.jsonl",
        session_id="session-b",
        cwd=outside / "proj-b",
        first_message="hello b",
        timestamp=now + timedelta(seconds=10),
    )

    scanner = CodexSessionScanner(
        approved_directory=approved,
        cache_ttl_sec=0,
        sessions_dir=sessions_dir,
    )
    projects = await scanner.list_projects()

    assert projects == [(approved / "proj-a").resolve()]


@pytest.mark.asyncio
async def test_codex_scanner_list_sessions_extracts_message_and_activity(tmp_path):
    """Session list should include parsed message preview and activity marker."""
    approved = tmp_path / "approved"
    project = approved / "proj-a"
    project.mkdir(parents=True)
    sessions_dir = tmp_path / ".codex" / "sessions"

    old_ts = datetime.utcnow() - timedelta(hours=1)
    new_ts = datetime.utcnow() - timedelta(seconds=2)
    old_file = sessions_dir / "2026/02/14/rollout-old.jsonl"
    new_file = sessions_dir / "2026/02/14/rollout-new.jsonl"

    _write_codex_session(
        file_path=old_file,
        session_id="session-old",
        cwd=project,
        first_message="old message",
        timestamp=old_ts,
    )
    _write_codex_session(
        file_path=new_file,
        session_id="session-new",
        cwd=project,
        first_message="new message",
        timestamp=new_ts,
    )

    scanner = CodexSessionScanner(
        approved_directory=approved,
        cache_ttl_sec=0,
        sessions_dir=sessions_dir,
    )
    sessions = await scanner.list_sessions(project_cwd=project, active_window_sec=5)

    assert len(sessions) == 2
    assert sessions[0].session_id == "session-new"
    assert sessions[0].first_message == "new message"
    assert sessions[0].is_probably_active is True
    assert sessions[1].session_id == "session-old"
    assert sessions[1].is_probably_active is False
