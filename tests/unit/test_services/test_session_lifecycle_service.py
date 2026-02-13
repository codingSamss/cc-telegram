"""Tests for session lifecycle service."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.services.session_lifecycle_service import SessionLifecycleService


class _FakePermissionManager:
    """Simple permission manager stub."""

    def __init__(self):
        self.cleared = []

    def clear_session(self, session_id: str) -> None:
        self.cleared.append(session_id)


@pytest.mark.asyncio
async def test_start_new_session_clears_scope_and_permissions():
    """New session should reset scope state and clear session permissions."""
    permission_manager = _FakePermissionManager()
    service = SessionLifecycleService(permission_manager=permission_manager)
    scope_state = {
        "claude_session_id": "sess-old-123",
        "session_started": False,
        "force_new_session": False,
    }

    result = service.start_new_session(scope_state)

    assert result.changed is True
    assert result.old_session_id == "sess-old-123"
    assert scope_state["claude_session_id"] is None
    assert scope_state["session_started"] is True
    assert scope_state["force_new_session"] is True
    assert permission_manager.cleared == ["sess-old-123"]


@pytest.mark.asyncio
async def test_end_session_handles_missing_active_session():
    """End session should return no-op when no active session exists."""
    service = SessionLifecycleService(permission_manager=_FakePermissionManager())
    scope_state = {"claude_session_id": None}

    result = service.end_session(scope_state)

    assert result.had_active_session is False
    assert result.ended_session_id is None


@pytest.mark.asyncio
async def test_end_session_clears_scope_and_permissions():
    """End session should clear active session and permission cache."""
    permission_manager = _FakePermissionManager()
    service = SessionLifecycleService(permission_manager=permission_manager)
    scope_state = {
        "claude_session_id": "sess-end-123",
        "session_started": True,
        "last_message": "hello",
    }

    result = service.end_session(scope_state)

    assert result.had_active_session is True
    assert result.ended_session_id == "sess-end-123"
    assert scope_state["claude_session_id"] is None
    assert scope_state["session_started"] is False
    assert scope_state["last_message"] is None
    assert permission_manager.cleared == ["sess-end-123"]


@pytest.mark.asyncio
async def test_continue_session_with_existing_session_uses_run_command():
    """Existing session should continue via run_command."""
    service = SessionLifecycleService()
    claude_integration = SimpleNamespace(
        run_command=AsyncMock(
            return_value=SimpleNamespace(
                session_id="sess-new-123",
                content="continued",
            )
        ),
        continue_session=AsyncMock(),
    )
    scope_state = {"claude_session_id": "sess-old-123"}

    result = await service.continue_session(
        user_id=1001,
        scope_state=scope_state,
        current_dir=Path("/tmp/project"),
        claude_integration=claude_integration,
        prompt=None,
        default_prompt="default prompt",
        permission_handler=None,
        use_empty_prompt_when_existing=False,
        allow_none_prompt_when_discover=False,
    )

    assert result.status == "continued"
    assert result.used_existing_session is True
    assert scope_state["claude_session_id"] == "sess-new-123"
    claude_integration.run_command.assert_awaited_once()
    assert (
        claude_integration.run_command.await_args.kwargs["prompt"] == "default prompt"
    )


@pytest.mark.asyncio
async def test_continue_session_with_discovery_uses_continue_session():
    """No active session should discover latest resumable session."""
    service = SessionLifecycleService()
    claude_integration = SimpleNamespace(
        run_command=AsyncMock(),
        continue_session=AsyncMock(
            return_value=SimpleNamespace(
                session_id="sess-discovered-123",
                content="continued",
            )
        ),
    )
    scope_state = {"claude_session_id": None}

    result = await service.continue_session(
        user_id=1002,
        scope_state=scope_state,
        current_dir=Path("/tmp/project"),
        claude_integration=claude_integration,
        prompt=None,
        default_prompt="default prompt",
        permission_handler=None,
        use_empty_prompt_when_existing=False,
        allow_none_prompt_when_discover=True,
    )

    assert result.status == "continued"
    assert result.used_existing_session is False
    assert scope_state["claude_session_id"] == "sess-discovered-123"
    claude_integration.continue_session.assert_awaited_once()
    assert claude_integration.continue_session.await_args.kwargs["prompt"] is None


@pytest.mark.asyncio
async def test_continue_session_without_integration():
    """Missing claude integration should return unavailable status."""
    service = SessionLifecycleService()
    scope_state = {"claude_session_id": None}

    result = await service.continue_session(
        user_id=1003,
        scope_state=scope_state,
        current_dir=Path("/tmp/project"),
        claude_integration=None,
        prompt=None,
        default_prompt="default prompt",
    )

    assert result.status == "integration_unavailable"
