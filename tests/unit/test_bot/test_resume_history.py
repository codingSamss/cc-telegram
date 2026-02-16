"""Tests for resume history preview helpers."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.bot.utils.resume_history import load_resume_history_preview
from src.claude.integration import ClaudeResponse
from src.storage.facade import Storage


@pytest.fixture
async def storage():
    """Create storage for resume history tests."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "resume-history-test.db"
        store = Storage(f"sqlite:///{db_path}")
        await store.initialize()
        yield store
        await store.close()


@pytest.mark.asyncio
async def test_load_resume_history_preview_prefers_storage(storage, tmp_path):
    """Storage records should be used when available."""
    user_id = 9123
    session_id = "resume-history-storage"
    project = tmp_path / "project-storage"
    project.mkdir(parents=True)

    await storage.get_or_create_user(user_id, "resume_user")
    await storage.create_session(user_id, str(project), session_id)

    for idx in range(1, 4):
        response = ClaudeResponse(
            content=f"assistant-{idx}",
            session_id=session_id,
            cost=0.01,
            duration_ms=1000,
            num_turns=1,
        )
        await storage.save_claude_interaction(
            user_id=user_id,
            session_id=session_id,
            prompt=f"user-{idx}",
            response=response,
        )

    preview = await load_resume_history_preview(
        session_id=session_id,
        user_id=user_id,
        project_cwd=project,
        engine="claude",
        limit=4,
        storage=storage,
        scanner=None,
    )

    assert [(item.role, item.content) for item in preview] == [
        ("user", "user-2"),
        ("assistant", "assistant-2"),
        ("user", "user-3"),
        ("assistant", "assistant-3"),
    ]


@pytest.mark.asyncio
async def test_load_resume_history_preview_falls_back_to_codex_jsonl(tmp_path):
    """When storage is absent, codex session jsonl should provide preview lines."""
    user_id = 9201
    session_id = "codex-session-preview"
    project = tmp_path / "project-codex"
    project.mkdir(parents=True)
    session_file = tmp_path / "codex-session.jsonl"

    rows = [
        {
            "type": "session_meta",
            "payload": {"id": session_id, "cwd": str(project)},
        },
        {
            "type": "event_msg",
            "payload": {"type": "user_message", "message": "first user"},
        },
        {
            "type": "event_msg",
            "payload": {"type": "assistant_message", "message": "first assistant"},
        },
        {
            "type": "event_msg",
            "payload": {"type": "user_message", "message": "second user"},
        },
        {
            "type": "event_msg",
            "payload": {"type": "assistant_message", "message": "second assistant"},
        },
    ]
    with open(session_file, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    scanner = SimpleNamespace(
        list_sessions=AsyncMock(
            return_value=[
                SimpleNamespace(session_id=session_id, source_file=session_file),
            ]
        )
    )

    preview = await load_resume_history_preview(
        session_id=session_id,
        user_id=user_id,
        project_cwd=project,
        engine="codex",
        limit=4,
        storage=None,
        scanner=scanner,
    )

    assert [(item.role, item.content) for item in preview] == [
        ("user", "first user"),
        ("assistant", "first assistant"),
        ("user", "second user"),
        ("assistant", "second assistant"),
    ]


@pytest.mark.asyncio
async def test_load_resume_history_preview_parses_claude_jsonl(tmp_path):
    """Claude jsonl format should be parsed when storage has no messages."""
    user_id = 9202
    session_id = "claude-session-preview"
    project = tmp_path / "project-claude"
    project.mkdir(parents=True)
    session_file = tmp_path / "claude-session.jsonl"

    rows = [
        {"cwd": str(project), "sessionId": session_id},
        {"type": "user", "message": {"content": "first user"}},
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "first assistant"}]},
        },
        {"type": "user", "message": {"content": "second user"}},
        {"type": "assistant", "message": {"content": "second assistant"}},
    ]
    with open(session_file, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    scanner = SimpleNamespace(
        list_sessions=AsyncMock(
            return_value=[
                SimpleNamespace(session_id=session_id, source_file=session_file),
            ]
        )
    )

    preview = await load_resume_history_preview(
        session_id=session_id,
        user_id=user_id,
        project_cwd=project,
        engine="claude",
        limit=2,
        storage=None,
        scanner=scanner,
    )

    assert [(item.role, item.content) for item in preview] == [
        ("user", "second user"),
        ("assistant", "second assistant"),
    ]
