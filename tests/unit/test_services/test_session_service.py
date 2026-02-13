"""Tests for session/event services."""

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.claude.integration import ClaudeResponse
from src.services import EventService, SessionService
from src.storage.facade import Storage


@pytest.fixture
async def storage():
    """Create test storage."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "test.db"
        storage = Storage(f"sqlite:///{db_path}")
        await storage.initialize()
        yield storage
        await storage.close()


@pytest.mark.asyncio
async def test_event_service_builds_recent_summary(storage):
    """Event service should summarize recent events by type."""
    await storage.get_or_create_user(22001, "svc_user")
    await storage.create_session(22001, "/test/svc", "svc-session-1")

    response = ClaudeResponse(
        content="处理完成",
        session_id="svc-session-1",
        cost=0.12,
        duration_ms=3200,
        num_turns=2,
        tools_used=[{"name": "Bash", "input": {"command": "pytest -q"}}],
    )
    await storage.save_claude_interaction(
        user_id=22001,
        session_id="svc-session-1",
        prompt="帮我运行测试并总结结果",
        response=response,
    )

    service = EventService(storage)
    summary = await service.get_recent_event_summary("svc-session-1", limit=20)

    assert summary["count"] >= 5
    assert summary["by_type"]["command_exec"] == 1
    assert summary["by_type"]["assistant_text"] == 1
    assert summary["by_type"]["tool_call"] == 1
    assert summary["by_type"]["tool_result"] == 1
    assert summary["latest_at"] is not None
    assert summary["highlights"]


@pytest.mark.asyncio
async def test_session_service_context_event_lines(storage):
    """Session service should render markdown lines for /context."""
    await storage.get_or_create_user(22002, "svc_user2")
    await storage.create_session(22002, "/test/svc2", "svc-session-2")

    response = ClaudeResponse(
        content="已完成最小修复。",
        session_id="svc-session-2",
        cost=0.03,
        duration_ms=1800,
        num_turns=1,
    )
    await storage.save_claude_interaction(
        user_id=22002,
        session_id="svc-session-2",
        prompt="修复这个报错",
        response=response,
    )

    event_service = EventService(storage)
    session_service = SessionService(storage=storage, event_service=event_service)
    lines = await session_service.get_context_event_lines("svc-session-2")

    rendered = "\n".join(lines)
    assert "Recent Session Events" in rendered
    assert "By Type:" in rendered
    assert "`command_exec`" in rendered
    assert "`assistant_text`" in rendered
    assert "Highlights:" not in rendered


@pytest.mark.asyncio
async def test_session_service_context_event_lines_empty(storage):
    """Unknown session should return empty summary lines."""
    event_service = EventService(storage)
    session_service = SessionService(storage=storage, event_service=event_service)

    lines = await session_service.get_context_event_lines("missing-session")
    assert lines == []


@pytest.mark.asyncio
async def test_build_context_snapshot_for_active_session():
    """Unified snapshot should include context/session/event lines."""
    approved = Path("/tmp/project")
    current_dir = approved
    claude_integration = SimpleNamespace(
        get_precise_context_usage=AsyncMock(
            return_value={
                "used_tokens": 1000,
                "total_tokens": 200000,
                "remaining_tokens": 199000,
                "used_percent": 0.5,
                "session_id": "sess-abc",
                "cached": False,
            }
        ),
        get_session_info=AsyncMock(
            return_value={
                "messages": 3,
                "turns": 2,
                "cost": 0.12,
                "model_usage": None,
            }
        ),
    )

    async def _event_lines_provider(session_id: str):
        assert session_id == "sess-abc"
        return ["", "*Recent Session Events*", "Count: 2"]

    snapshot = await SessionService.build_context_snapshot(
        user_id=3001,
        session_id="sess-abc",
        current_dir=current_dir,
        approved_directory=approved,
        current_model="sonnet",
        claude_integration=claude_integration,
        include_resumable=True,
        event_lines_provider=_event_lines_provider,
    )

    rendered = "\n".join(snapshot.lines)
    assert "Session: `sess-abc...`" in rendered
    assert "Messages: 3" in rendered
    assert "Turns: 2" in rendered
    assert "Recent Session Events" in rendered
    assert snapshot.precise_context is not None
    assert snapshot.session_info is not None


@pytest.mark.asyncio
async def test_build_context_snapshot_for_resumable_session():
    """No active session should show resumable info when available."""
    approved = Path("/tmp/project")
    current_dir = approved
    claude_integration = SimpleNamespace(
        _find_resumable_session=AsyncMock(
            return_value=SimpleNamespace(
                session_id="resume-12345678",
                message_count=18,
            )
        )
    )

    snapshot = await SessionService.build_context_snapshot(
        user_id=3002,
        session_id=None,
        current_dir=current_dir,
        approved_directory=approved,
        current_model=None,
        claude_integration=claude_integration,
        include_resumable=True,
    )

    rendered = "\n".join(snapshot.lines)
    assert "Session: none" in rendered
    assert "Resumable: `resume-1...` (18 msgs)" in rendered
    assert snapshot.resumable_payload is not None


@pytest.mark.asyncio
async def test_build_scope_context_snapshot_uses_scoped_state():
    """Scope snapshot helper should map scope state into unified builder args."""
    approved = Path("/tmp/project")
    claude_integration = SimpleNamespace(
        get_precise_context_usage=AsyncMock(return_value=None),
        get_session_info=AsyncMock(return_value=None),
    )
    provider_owner = SimpleNamespace(
        get_context_event_lines=AsyncMock(return_value=["", "*Recent Session Events*"])
    )
    scope_state = {
        "claude_session_id": "scope-sess-001",
        "current_directory": approved,
        "claude_model": "sonnet",
    }

    snapshot = await SessionService.build_scope_context_snapshot(
        user_id=3003,
        scope_state=scope_state,
        approved_directory=approved,
        claude_integration=claude_integration,
        session_service=provider_owner,
        include_resumable=False,
        include_event_summary=True,
    )

    rendered = "\n".join(snapshot.lines)
    assert "Session: `scope-se...`" in rendered
    assert "Recent Session Events" in rendered
    provider_owner.get_context_event_lines.assert_awaited_once_with("scope-sess-001")


@pytest.mark.asyncio
async def test_build_scope_context_snapshot_skips_event_provider_when_disabled():
    """Event provider should not be called when summary flag is disabled."""
    approved = Path("/tmp/project")
    claude_integration = SimpleNamespace(
        get_precise_context_usage=AsyncMock(return_value=None),
        get_session_info=AsyncMock(return_value=None),
    )
    provider_owner = SimpleNamespace(
        get_context_event_lines=AsyncMock(return_value=["", "*Recent Session Events*"])
    )
    scope_state = {
        "claude_session_id": "scope-sess-002",
        "current_directory": approved,
        "claude_model": "sonnet",
    }

    await SessionService.build_scope_context_snapshot(
        user_id=3004,
        scope_state=scope_state,
        approved_directory=approved,
        claude_integration=claude_integration,
        session_service=provider_owner,
        include_resumable=False,
        include_event_summary=False,
    )

    provider_owner.get_context_event_lines.assert_not_awaited()
