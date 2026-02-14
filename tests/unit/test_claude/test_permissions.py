"""Tests for permission workflow persistence and state transitions."""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import pytest

from src.claude.permissions import PermissionManager


class InMemoryApprovalRequestRepository:
    """Simple in-memory approval persistence stub for unit tests."""

    def __init__(self):
        self.requests: Dict[str, Dict[str, Any]] = {}
        self.create_calls = 0

    async def create_request(
        self,
        *,
        request_id: str,
        user_id: int,
        session_id: str,
        tool_name: str,
        tool_input: Dict[str, Any],
        expires_at: datetime,
    ) -> None:
        self.create_calls += 1
        self.requests[request_id] = {
            "request_id": request_id,
            "user_id": user_id,
            "session_id": session_id,
            "tool_name": tool_name,
            "tool_input": tool_input,
            "status": "pending",
            "decision": None,
            "expires_at": expires_at,
            "resolved_at": None,
        }

    async def resolve_request(
        self,
        *,
        request_id: str,
        status: str,
        decision: Optional[str],
        resolved_at: datetime,
    ) -> bool:
        row = self.requests.get(request_id)
        if not row or row["status"] != "pending":
            return False
        row["status"] = status
        row["decision"] = decision
        row["resolved_at"] = resolved_at
        return True

    async def expire_all_pending(self, *, resolved_at: datetime) -> int:
        expired = 0
        for row in self.requests.values():
            if row["status"] == "pending":
                row["status"] = "expired"
                row["resolved_at"] = resolved_at
                expired += 1
        return expired


@pytest.mark.asyncio
async def test_initialize_expires_stale_pending_requests():
    """Startup recovery should mark persisted pending requests as expired."""
    repo = InMemoryApprovalRequestRepository()
    await repo.create_request(
        request_id="req-pending",
        user_id=1,
        session_id="s1",
        tool_name="Bash",
        tool_input={"command": "pytest"},
        expires_at=datetime.utcnow() + timedelta(minutes=2),
    )
    await repo.create_request(
        request_id="req-approved",
        user_id=1,
        session_id="s1",
        tool_name="Read",
        tool_input={"file_path": "a.py"},
        expires_at=datetime.utcnow() + timedelta(minutes=2),
    )
    await repo.resolve_request(
        request_id="req-approved",
        status="approved",
        decision="allow",
        resolved_at=datetime.utcnow(),
    )

    manager = PermissionManager(timeout_seconds=120, approval_repository=repo)
    await manager.initialize()

    assert repo.requests["req-pending"]["status"] == "expired"
    assert repo.requests["req-approved"]["status"] == "approved"


@pytest.mark.asyncio
async def test_request_permission_persists_and_resolves_allow():
    """Allow decision should resolve request and persist approved status."""
    repo = InMemoryApprovalRequestRepository()
    manager = PermissionManager(timeout_seconds=2, approval_repository=repo)

    async def send_buttons(
        request_id: str, tool_name: str, tool_input: Dict[str, Any], session_id: str
    ) -> None:
        manager.resolve_permission(request_id, "allow", user_id=100)

    allowed = await manager.request_permission(
        tool_name="Bash",
        tool_input={"command": "pytest"},
        user_id=100,
        session_id="session-1",
        send_buttons_callback=send_buttons,
    )
    await asyncio.sleep(0)

    assert allowed is True
    assert len(repo.requests) == 1
    request = next(iter(repo.requests.values()))
    assert request["status"] == "approved"
    assert request["decision"] == "allow"


@pytest.mark.asyncio
async def test_allow_all_is_session_scoped_and_skips_reprompt():
    """Allow-all should cache tool permission for the same session."""
    repo = InMemoryApprovalRequestRepository()
    manager = PermissionManager(timeout_seconds=2, approval_repository=repo)
    callback_invocations = {"count": 0}

    async def send_buttons(
        request_id: str, tool_name: str, tool_input: Dict[str, Any], session_id: str
    ) -> None:
        callback_invocations["count"] += 1
        manager.resolve_permission(request_id, "allow_all", user_id=200)

    first = await manager.request_permission(
        tool_name="Write",
        tool_input={"file_path": "src/a.py"},
        user_id=200,
        session_id="session-allow-all",
        send_buttons_callback=send_buttons,
    )
    await asyncio.sleep(0)

    second = await manager.request_permission(
        tool_name="Write",
        tool_input={"file_path": "src/b.py"},
        user_id=200,
        session_id="session-allow-all",
        send_buttons_callback=send_buttons,
    )

    assert first is True
    assert second is True
    assert callback_invocations["count"] == 1
    assert repo.create_calls == 1
    persisted = next(iter(repo.requests.values()))
    assert persisted["status"] == "approved"
    assert persisted["decision"] == "allow_all"


@pytest.mark.asyncio
async def test_request_permission_timeout_persists_expired():
    """Timeout should mark approval request as expired."""
    repo = InMemoryApprovalRequestRepository()
    manager = PermissionManager(timeout_seconds=0, approval_repository=repo)

    async def send_buttons(
        request_id: str, tool_name: str, tool_input: Dict[str, Any], session_id: str
    ) -> None:
        # Intentionally do nothing so wait_for times out immediately.
        return None

    allowed = await manager.request_permission(
        tool_name="Edit",
        tool_input={"file_path": "src/x.py"},
        user_id=300,
        session_id="session-timeout",
        send_buttons_callback=send_buttons,
    )

    assert allowed is False
    assert len(repo.requests) == 1
    request = next(iter(repo.requests.values()))
    assert request["status"] == "expired"
    assert request["decision"] is None
