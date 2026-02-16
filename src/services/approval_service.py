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

    @staticmethod
    def _escape_markdown_text(value: Any) -> str:
        """Escape Telegram legacy Markdown control characters."""
        text = str(value)
        for ch in ("\\", "`", "*", "_", "["):
            text = text.replace(ch, f"\\{ch}")
        return text

    @staticmethod
    def _format_tool_input_summary(tool_name: str, tool_input: dict[str, Any]) -> str:
        """Build a concise tool input summary for callback responses."""
        if not tool_input:
            return ""

        def _clip(value: Any, limit: int) -> str:
            # Inline code in Telegram Markdown cannot safely contain raw newlines.
            text = " ".join(str(value).split()).replace("`", "'")
            if len(text) > limit:
                return text[:limit] + "..."
            return text

        if tool_name in {"Read", "Write", "Edit"} and "file_path" in tool_input:
            return f"File: `{_clip(tool_input['file_path'], 120)}`"
        if tool_name == "Bash" and "command" in tool_input:
            return f"Command: `{_clip(tool_input['command'], 160)}`"
        if tool_name == "WebFetch" and "url" in tool_input:
            return f"URL: `{_clip(tool_input['url'], 180)}`"

        for key, value in list(tool_input.items())[:2]:
            safe_key = ApprovalService._escape_markdown_text(key)
            return f"{safe_key}: `{_clip(value, 120)}`"
        return ""

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

        pending = None
        get_pending = getattr(permission_manager, "get_pending_request", None)
        if callable(get_pending):
            pending = get_pending(request_id, user_id=user_id)
        snapshot = None
        get_snapshot = getattr(permission_manager, "get_resolution_snapshot", None)
        if callable(get_snapshot):
            snapshot = get_snapshot(request_id, user_id=user_id)

        resolved = permission_manager.resolve_permission(
            request_id,
            decision,
            user_id=user_id,
        )
        if not resolved:
            decision_label = self._DECISION_LABELS.get(decision, decision)
            status_label = str((snapshot or {}).get("status") or "").strip().lower()
            if status_label == "expired":
                reason_text = "This permission request has timed out."
            elif status_label in {"approved", "denied"}:
                reason_text = "This permission request has already been handled."
            else:
                reason_text = (
                    "This permission request has already been handled or timed out."
                )
            context_lines = []
            tool_name = (
                str(pending.tool_name).strip()
                if pending
                else (snapshot or {}).get("tool_name")
            )
            tool_input = (
                pending.tool_input
                if pending
                else (snapshot or {}).get("tool_input") or {}
            )
            if tool_name:
                safe_tool_name = str(tool_name).replace("`", "'")
                context_lines.append(f"Tool: `{safe_tool_name}`")
                summary = self._format_tool_input_summary(
                    str(tool_name),
                    tool_input,
                )
                if summary:
                    context_lines.append(summary)
            snapshot_decision = (snapshot or {}).get("decision")
            if snapshot_decision:
                decision_text = self._DECISION_LABELS.get(
                    str(snapshot_decision),
                    str(snapshot_decision),
                )
                context_lines.append(f"Latest decision: `{decision_text}`")
            if status_label:
                context_lines.append(f"Latest status: `{status_label}`")
            context_text = ""
            if context_lines:
                context_text = "\n" + "\n".join(context_lines) + "\n"
            return ApprovalResolution(
                ok=False,
                code="expired",
                request_id=request_id,
                decision=decision,
                parse_mode="Markdown",
                message=(
                    "**Permission Request Expired**\n\n"
                    f"{reason_text}\n\n"
                    f"Request: `{request_id}`\n"
                    f"Action: `{decision_label}`"
                    f"{context_text}\n"
                    "Please re-run your request if approval is still needed."
                ),
            )

        label = self._DECISION_LABELS.get(decision, decision)
        suffix = ""
        if pending:
            safe_tool_name = str(pending.tool_name).replace("`", "'")
            summary = self._format_tool_input_summary(
                pending.tool_name,
                pending.tool_input or {},
            )
            details = [f"Tool: `{safe_tool_name}`"]
            if summary:
                details.append(summary)
            suffix = "\n\n" + "\n".join(details)
        return ApprovalResolution(
            ok=True,
            code="resolved",
            request_id=request_id,
            decision=decision,
            parse_mode="Markdown",
            message=f"**Permission {label}**\n\nYour choice has been applied.{suffix}",
        )
