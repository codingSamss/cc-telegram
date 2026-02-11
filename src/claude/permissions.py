"""Permission management for Claude tool usage via Telegram buttons."""

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, Optional, Set

import structlog

logger = structlog.get_logger()

# Type alias for the callback that sends Telegram permission buttons
PermissionRequestCallback = Callable[
    [str, str, Dict[str, Any], str],  # request_id, tool_name, tool_input, session_id
    Coroutine[Any, Any, None],
]


@dataclass
class PendingPermission:
    """A pending permission request waiting for user response."""

    request_id: str
    tool_name: str
    tool_input: Dict[str, Any]
    future: asyncio.Future
    user_id: int
    session_id: str


class PermissionManager:
    """Manage tool permission requests bridging SDK callbacks to Telegram buttons."""

    def __init__(self, timeout_seconds: int = 120):
        self.timeout_seconds = timeout_seconds
        self.pending_requests: Dict[str, PendingPermission] = {}
        # Tools allowed for the rest of the session (per session_id)
        self.session_allowed_tools: Dict[str, Set[str]] = {}

    async def request_permission(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        user_id: int,
        session_id: str,
        send_buttons_callback: PermissionRequestCallback,
    ) -> bool:
        """Request permission from user via Telegram buttons.

        Returns True if allowed, False if denied.
        """
        # Check if tool is already allowed for this session
        if self._is_session_allowed(session_id, tool_name):
            logger.info(
                "Tool already allowed for session",
                tool_name=tool_name,
                session_id=session_id,
            )
            return True

        request_id = str(uuid.uuid4())[:8]
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()

        pending = PendingPermission(
            request_id=request_id,
            tool_name=tool_name,
            tool_input=tool_input,
            future=future,
            user_id=user_id,
            session_id=session_id,
        )
        self.pending_requests[request_id] = pending

        logger.info(
            "Permission requested",
            request_id=request_id,
            tool_name=tool_name,
            user_id=user_id,
        )

        try:
            # Send Telegram buttons to user
            await send_buttons_callback(
                request_id, tool_name, tool_input, session_id
            )

            # Wait for user response with timeout
            result = await asyncio.wait_for(
                future, timeout=self.timeout_seconds
            )
            return result

        except asyncio.TimeoutError:
            logger.warning(
                "Permission request timed out",
                request_id=request_id,
                tool_name=tool_name,
            )
            return False

        finally:
            self.pending_requests.pop(request_id, None)

    def resolve_permission(
        self, request_id: str, decision: str, user_id: Optional[int] = None
    ) -> bool:
        """Resolve a pending permission request.

        decision: 'allow', 'allow_all', or 'deny'
        user_id: if provided, must match the original requester
        Returns True if the request was found and resolved.
        """
        pending = self.pending_requests.get(request_id)
        if not pending:
            logger.warning(
                "Permission request not found",
                request_id=request_id,
            )
            return False

        if user_id is not None and pending.user_id != user_id:
            logger.warning(
                "Permission resolve rejected: user mismatch",
                request_id=request_id,
                expected_user=pending.user_id,
                actual_user=user_id,
            )
            return False

        if pending.future.done():
            return False

        if decision == "allow":
            pending.future.set_result(True)
        elif decision == "allow_all":
            # Allow this tool for the rest of the session
            self._add_session_allowed(
                pending.session_id, pending.tool_name
            )
            pending.future.set_result(True)
        else:
            pending.future.set_result(False)

        logger.info(
            "Permission resolved",
            request_id=request_id,
            tool_name=pending.tool_name,
            decision=decision,
        )
        return True

    def _is_session_allowed(self, session_id: str, tool_name: str) -> bool:
        allowed = self.session_allowed_tools.get(session_id, set())
        return tool_name in allowed

    def _add_session_allowed(self, session_id: str, tool_name: str) -> None:
        if session_id not in self.session_allowed_tools:
            self.session_allowed_tools[session_id] = set()
        self.session_allowed_tools[session_id].add(tool_name)

    def clear_session(self, session_id: str) -> None:
        """Clear session-level permissions."""
        self.session_allowed_tools.pop(session_id, None)

    def get_pending_count(self) -> int:
        return len(self.pending_requests)
