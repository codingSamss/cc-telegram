"""Session application service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional

import structlog

from ..bot.utils.status_usage import (
    build_model_usage_status_lines,
    build_precise_context_status_lines,
)
from ..storage.facade import Storage
from .event_service import EventService

logger = structlog.get_logger()


@dataclass
class ContextStatusSnapshot:
    """Structured snapshot for /context rendering."""

    lines: List[str]
    precise_context: Optional[Dict[str, Any]] = None
    session_info: Optional[Dict[str, Any]] = None
    resumable_payload: Optional[Dict[str, Any]] = None


class SessionService:
    """Provide session-level reusable business capabilities."""

    def __init__(self, storage: Storage, event_service: EventService):
        self.storage = storage
        self.event_service = event_service

    async def get_user_session_summary(self, user_id: int) -> Dict[str, Any]:
        """Return aggregated session summary for one user."""
        return await self.storage.get_user_session_summary(user_id)

    @staticmethod
    async def build_scope_context_snapshot(
        *,
        user_id: int,
        scope_state: Mapping[str, Any],
        approved_directory: Path,
        claude_integration: Any,
        session_service: Any = None,
        include_resumable: bool = True,
        include_event_summary: bool = True,
    ) -> ContextStatusSnapshot:
        """Build context snapshot directly from scoped state."""
        current_dir = scope_state.get("current_directory", approved_directory)
        current_model = scope_state.get("claude_model")
        session_id = scope_state.get("claude_session_id")
        event_provider = None
        if include_event_summary and session_service:
            candidate = getattr(session_service, "get_context_event_lines", None)
            if callable(candidate):
                event_provider = candidate

        return await SessionService.build_context_snapshot(
            user_id=user_id,
            session_id=session_id,
            current_dir=current_dir,
            approved_directory=approved_directory,
            current_model=current_model,
            claude_integration=claude_integration,
            include_resumable=include_resumable,
            event_lines_provider=event_provider,
        )

    @staticmethod
    async def build_context_snapshot(
        *,
        user_id: int,
        session_id: Optional[str],
        current_dir: Path,
        approved_directory: Path,
        current_model: Optional[str],
        claude_integration: Any,
        include_resumable: bool = True,
        event_lines_provider: Optional[Callable[[str], Awaitable[List[str]]]] = None,
    ) -> ContextStatusSnapshot:
        """Build a unified /context snapshot used by command and callback handlers."""
        try:
            relative_path = current_dir.relative_to(approved_directory)
        except ValueError:
            relative_path = current_dir

        lines = [
            "**Session Context**\n",
            f"Directory: `{relative_path}/`",
            f"Model: `{current_model or 'default'}`",
        ]
        precise_context = None
        session_info = None
        resumable_payload = None

        if session_id:
            lines.append(f"Session: `{session_id[:8]}...`")
            if claude_integration:
                precise_context = await claude_integration.get_precise_context_usage(
                    session_id=session_id,
                    working_directory=current_dir,
                    model=current_model,
                )
                if precise_context:
                    lines.extend(build_precise_context_status_lines(precise_context))

                session_info = await claude_integration.get_session_info(session_id)
                if session_info:
                    lines.append(f"Messages: {session_info.get('messages', 0)}")
                    lines.append(f"Turns: {session_info.get('turns', 0)}")
                    lines.append(f"Cost: `${session_info.get('cost', 0.0):.4f}`")

                    model_usage = session_info.get("model_usage")
                    if model_usage and not precise_context:
                        lines.extend(
                            build_model_usage_status_lines(
                                model_usage=model_usage,
                                current_model=current_model,
                                allow_estimated_ratio=True,
                            )
                        )

            if event_lines_provider:
                try:
                    event_lines = await event_lines_provider(session_id)
                    if event_lines:
                        lines.extend(event_lines)
                except Exception as exc:
                    logger.warning(
                        "Failed to build context event summary",
                        error=str(exc),
                        user_id=user_id,
                        session_id=session_id,
                    )
        else:
            lines.append("Session: none")
            if include_resumable and claude_integration:
                existing = await claude_integration._find_resumable_session(
                    user_id, current_dir
                )
                if existing:
                    resumable_payload = {
                        "session_id": existing.session_id,
                        "message_count": existing.message_count,
                    }
                    lines.append(
                        f"Resumable: `{existing.session_id[:8]}...` "
                        f"({existing.message_count} msgs)"
                    )

        return ContextStatusSnapshot(
            lines=lines,
            precise_context=precise_context,
            session_info=session_info,
            resumable_payload=resumable_payload,
        )

    async def get_context_event_lines(
        self,
        session_id: str,
        *,
        limit: int = 12,
    ) -> List[str]:
        """Return markdown-friendly lines for /context event summary."""
        summary = await self.event_service.get_recent_event_summary(
            session_id=session_id,
            limit=limit,
            highlight_limit=0,
        )
        if int(summary.get("count", 0)) <= 0:
            return []

        lines: List[str] = [
            "",
            "*Recent Session Events*",
            f"Count: {summary.get('count', 0)}",
        ]

        latest_at = summary.get("latest_at")
        if latest_at:
            lines.append(f"Latest: `{latest_at}`")

        by_type = summary.get("by_type") or {}
        if by_type:
            lines.append("By Type:")
            for event_type, count in list(by_type.items())[:4]:
                safe_event_type = str(event_type).replace("`", "'")
                lines.append(f"- `{safe_event_type}`: {count}")

        return lines
