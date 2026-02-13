"""Permission management for Claude tool usage via Telegram buttons."""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Coroutine, Dict, Optional, Protocol, Set

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


class ApprovalRequestStore(Protocol):
    """Storage contract for approval request persistence."""

    async def create_request(
        self,
        *,
        request_id: str,
        user_id: int,
        session_id: str,
        tool_name: str,
        tool_input: Dict[str, Any],
        expires_at: datetime,
    ) -> None: ...

    async def resolve_request(
        self,
        *,
        request_id: str,
        status: str,
        decision: Optional[str],
        resolved_at: datetime,
    ) -> bool: ...

    async def expire_all_pending(self, *, resolved_at: datetime) -> int: ...


class PermissionManager:
    """Manage tool permission requests bridging SDK callbacks to Telegram buttons."""

    def __init__(
        self,
        timeout_seconds: int = 120,
        approval_repository: Optional[ApprovalRequestStore] = None,
    ):
        self.timeout_seconds = timeout_seconds
        self.pending_requests: Dict[str, PendingPermission] = {}
        # Tools allowed for the rest of the session (per session_id)
        self.session_allowed_tools: Dict[str, Set[str]] = {}
        self.approval_repository = approval_repository

    async def initialize(self) -> None:
        """Run startup recovery for persisted pending approvals."""
        if not self.approval_repository:
            return

        try:
            expired_count = await self.approval_repository.expire_all_pending(
                resolved_at=datetime.utcnow()
            )
            if expired_count > 0:
                logger.info(
                    "Expired stale pending approval requests on startup",
                    count=expired_count,
                )
        except Exception as exc:
            logger.warning(
                "Failed to recover persisted approval requests on startup",
                error=str(exc),
            )

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
            await self._persist_pending_request(
                request_id=request_id,
                tool_name=tool_name,
                tool_input=tool_input,
                user_id=user_id,
                session_id=session_id,
            )

            # Send Telegram buttons to user
            await send_buttons_callback(request_id, tool_name, tool_input, session_id)

            # Wait for user response with timeout
            result = await asyncio.wait_for(future, timeout=self.timeout_seconds)
            return result

        except asyncio.TimeoutError:
            logger.warning(
                "Permission request timed out",
                request_id=request_id,
                tool_name=tool_name,
            )
            await self._persist_resolution(
                request_id=request_id,
                status="expired",
                decision=None,
            )
            return False

        except asyncio.CancelledError:
            await self._persist_resolution(
                request_id=request_id,
                status="expired",
                decision=None,
            )
            raise

        except Exception as exc:
            logger.error(
                "Permission request failed before user decision",
                request_id=request_id,
                tool_name=tool_name,
                error=str(exc),
            )
            await self._persist_resolution(
                request_id=request_id,
                status="denied",
                decision="deny",
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

        allowed = False
        status = "denied"
        resolved_decision: Optional[str]

        if decision == "allow":
            allowed = True
            status = "approved"
            resolved_decision = "allow"
        elif decision == "allow_all":
            # Allow this tool for the rest of the session
            self._add_session_allowed(pending.session_id, pending.tool_name)
            allowed = True
            status = "approved"
            resolved_decision = "allow_all"
        elif decision == "deny":
            resolved_decision = "deny"
        else:
            logger.warning(
                "Permission decision not recognized, coercing to deny",
                request_id=request_id,
                decision=decision,
            )
            resolved_decision = "deny"

        pending.future.set_result(allowed)
        self._schedule_persist_resolution(
            request_id=request_id,
            status=status,
            decision=resolved_decision,
        )

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

    async def _persist_pending_request(
        self,
        *,
        request_id: str,
        tool_name: str,
        tool_input: Dict[str, Any],
        user_id: int,
        session_id: str,
    ) -> None:
        """Persist pending approval request state."""
        if not self.approval_repository:
            return

        try:
            await self.approval_repository.create_request(
                request_id=request_id,
                user_id=user_id,
                session_id=session_id,
                tool_name=tool_name,
                tool_input=tool_input,
                expires_at=datetime.utcnow() + timedelta(seconds=self.timeout_seconds),
            )
        except Exception as exc:
            logger.warning(
                "Failed to persist pending approval request",
                request_id=request_id,
                tool_name=tool_name,
                error=str(exc),
            )

    async def _persist_resolution(
        self,
        *,
        request_id: str,
        status: str,
        decision: Optional[str],
    ) -> None:
        """Persist approval request transition."""
        if not self.approval_repository:
            return

        try:
            await self.approval_repository.resolve_request(
                request_id=request_id,
                status=status,
                decision=decision,
                resolved_at=datetime.utcnow(),
            )
        except Exception as exc:
            logger.warning(
                "Failed to persist approval request resolution",
                request_id=request_id,
                status=status,
                decision=decision,
                error=str(exc),
            )

    def _schedule_persist_resolution(
        self,
        *,
        request_id: str,
        status: str,
        decision: Optional[str],
    ) -> None:
        """Persist resolution asynchronously from sync callback context."""
        if not self.approval_repository:
            return

        asyncio.create_task(
            self._persist_resolution(
                request_id=request_id,
                status=status,
                decision=decision,
            )
        )
