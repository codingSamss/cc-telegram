"""Approval application service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ApprovalResolution:
    """Approval resolution result for callback handlers."""

    ok: bool
    message: str
    parse_mode: Optional[str] = None
    request_id: Optional[str] = None
    decision: Optional[str] = None
    code: str = "unknown"


class ApprovalService:
    """Provide reusable approval callback parsing and resolution logic."""

    _DECISION_LABELS = {
        "allow": "Allowed",
        "allow_all": "Allowed (all for session)",
        "deny": "Denied",
    }

    def resolve_callback(
        self,
        *,
        param: str,
        user_id: int,
        permission_manager: Any,
    ) -> ApprovalResolution:
        """Resolve callback payload against PermissionManager."""
        if not param or ":" not in param:
            return ApprovalResolution(
                ok=False,
                code="invalid_param",
                message="Invalid permission callback data.",
            )

        decision, request_id = param.split(":", 1)
        if not permission_manager:
            return ApprovalResolution(
                ok=False,
                code="missing_manager",
                message="Permission manager not available.",
            )

        resolved = permission_manager.resolve_permission(
            request_id,
            decision,
            user_id=user_id,
        )
        if not resolved:
            return ApprovalResolution(
                ok=False,
                code="expired",
                request_id=request_id,
                decision=decision,
                parse_mode="Markdown",
                message=(
                    "**Permission Request Expired**\n\n"
                    "This permission request has already been handled or timed out."
                ),
            )

        label = self._DECISION_LABELS.get(decision, decision)
        return ApprovalResolution(
            ok=True,
            code="resolved",
            request_id=request_id,
            decision=decision,
            parse_mode="Markdown",
            message=f"**Permission {label}**\n\nYour choice has been applied.",
        )
