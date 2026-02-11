"""Task registry for managing active Claude tasks per user.

Enables task cancellation by tracking asyncio.Task instances
and providing thread-safe state transitions.
"""

import asyncio
import copy
import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional

import structlog

logger = structlog.get_logger()


class TaskState(enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class ActiveTask:
    task: asyncio.Task
    state: TaskState = TaskState.RUNNING
    created_at: datetime = field(default_factory=datetime.now)
    prompt_summary: str = ""
    progress_message_id: Optional[int] = None
    chat_id: Optional[int] = None


class TaskRegistry:
    """Manage active Claude tasks per user. Thread-safe via asyncio.Lock."""

    def __init__(self):
        self._tasks: Dict[int, ActiveTask] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        user_id: int,
        task: asyncio.Task,
        prompt_summary: str = "",
        progress_message_id: Optional[int] = None,
        chat_id: Optional[int] = None,
    ) -> None:
        async with self._lock:
            self._tasks[user_id] = ActiveTask(
                task=task,
                prompt_summary=prompt_summary[:100],
                progress_message_id=progress_message_id,
                chat_id=chat_id,
            )

    async def cancel(self, user_id: int) -> bool:
        """Cancel the user's active task. Returns True if cancelled."""
        async with self._lock:
            active = self._tasks.get(user_id)
            if not active or active.state != TaskState.RUNNING:
                return False
            active.state = TaskState.CANCELLED
            active.task.cancel()
            logger.info("Task cancelled", user_id=user_id)
            return True

    async def complete(self, user_id: int) -> None:
        async with self._lock:
            active = self._tasks.get(user_id)
            if active and active.state == TaskState.RUNNING:
                active.state = TaskState.COMPLETED

    async def fail(self, user_id: int) -> None:
        async with self._lock:
            active = self._tasks.get(user_id)
            if active and active.state == TaskState.RUNNING:
                active.state = TaskState.FAILED

    async def remove(self, user_id: int) -> None:
        async with self._lock:
            self._tasks.pop(user_id, None)

    async def get(self, user_id: int) -> Optional[ActiveTask]:
        async with self._lock:
            active = self._tasks.get(user_id)
            return copy.copy(active) if active else None

    async def is_busy(self, user_id: int) -> bool:
        async with self._lock:
            active = self._tasks.get(user_id)
            return active is not None and active.state == TaskState.RUNNING
