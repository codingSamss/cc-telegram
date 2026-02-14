"""Tests for approval service."""

from types import SimpleNamespace

from src.services import ApprovalService


class _FakePermissionManager:
    """Simple permission manager stub."""

    def __init__(
        self,
        resolved: bool = True,
        pending: SimpleNamespace | None = None,
        snapshot: dict | None = None,
    ):
        self.resolved = resolved
        self.calls = []
        self.pending = pending
        self.snapshot = snapshot

    def resolve_permission(self, request_id: str, decision: str, user_id: int) -> bool:
        self.calls.append((request_id, decision, user_id))
        return self.resolved

    def get_pending_request(
        self, request_id: str, user_id: int | None = None
    ) -> SimpleNamespace | None:
        return self.pending

    def get_resolution_snapshot(
        self, request_id: str, user_id: int | None = None
    ) -> dict | None:
        return self.snapshot


def test_resolve_callback_rejects_invalid_param():
    """Invalid callback payload should fail fast."""
    service = ApprovalService()
    result = service.resolve_callback(
        param="invalid",
        user_id=1001,
        permission_manager=_FakePermissionManager(),
    )
    assert result.ok is False
    assert result.code == "invalid_param"
    assert result.message == "Invalid permission callback data."


def test_resolve_callback_rejects_missing_manager():
    """Missing permission manager should return clear message."""
    service = ApprovalService()
    result = service.resolve_callback(
        param="allow:req-1",
        user_id=1001,
        permission_manager=None,
    )
    assert result.ok is False
    assert result.code == "missing_manager"
    assert result.message == "Permission manager not available."


def test_resolve_callback_handles_expired_request():
    """Unresolved request should be treated as expired."""
    service = ApprovalService()
    manager = _FakePermissionManager(resolved=False)
    result = service.resolve_callback(
        param="deny:req-expired",
        user_id=1001,
        permission_manager=manager,
    )
    assert result.ok is False
    assert result.code == "expired"
    assert "Permission Request Expired" in result.message
    assert "Request: `req-expired`" in result.message
    assert manager.calls == [("req-expired", "deny", 1001)]


def test_resolve_callback_expired_message_uses_snapshot_status_details():
    """Expired callback should explain latest known status/decision details."""
    service = ApprovalService()
    manager = _FakePermissionManager(
        resolved=False,
        snapshot={
            "status": "approved",
            "decision": "allow_all",
            "tool_name": "Bash",
            "tool_input": {"command": "pytest -q"},
        },
    )
    result = service.resolve_callback(
        param="deny:req-stale",
        user_id=1001,
        permission_manager=manager,
    )

    assert result.ok is False
    assert "already been handled" in result.message
    assert "Latest decision: `Allowed (all for session)`" in result.message
    assert "Latest status: `approved`" in result.message
    assert "Tool: `Bash`" in result.message


def test_resolve_callback_returns_labelled_success_message():
    """Successful resolution should include decision label."""
    service = ApprovalService()
    manager = _FakePermissionManager(resolved=True)
    result = service.resolve_callback(
        param="allow_all:req-2",
        user_id=1001,
        permission_manager=manager,
    )
    assert result.ok is True
    assert result.code == "resolved"
    assert "Permission Allowed (all for session)" in result.message
    assert manager.calls == [("req-2", "allow_all", 1001)]


def test_resolve_callback_includes_tool_context_when_pending_available():
    """Resolved callback should include tool context for user clarity."""
    service = ApprovalService()
    manager = _FakePermissionManager(
        resolved=True,
        pending=SimpleNamespace(
            tool_name="Bash",
            tool_input={"command": "pytest -q tests/unit"},
        ),
    )
    result = service.resolve_callback(
        param="allow:req-ctx",
        user_id=1001,
        permission_manager=manager,
    )

    assert result.ok is True
    assert "Tool: `Bash`" in result.message
    assert "Command:" in result.message
