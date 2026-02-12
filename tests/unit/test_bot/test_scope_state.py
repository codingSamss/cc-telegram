"""Tests for per-scope state helpers."""

from pathlib import Path
from types import SimpleNamespace

from src.bot.utils.scope_state import (
    get_scope_key_from_update,
    get_scope_state,
    get_scope_state_from_query,
)


def test_get_scope_key_from_update_includes_chat_and_topic() -> None:
    """Scope key should include user, chat, and topic(thread) id."""
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=7),
        effective_chat=SimpleNamespace(id=-100_123),
        effective_message=SimpleNamespace(message_thread_id=55),
    )

    scope_key = get_scope_key_from_update(update)

    assert scope_key == "7:-100123:55"


def test_get_scope_state_seeds_from_legacy_user_data() -> None:
    """New scoped state should inherit legacy root keys once."""
    user_data = {
        "current_directory": Path("/tmp/project"),
        "claude_session_id": "sess-123",
        "claude_model": "sonnet",
        "force_new_session": True,
    }

    state = get_scope_state(
        user_data=user_data,
        scope_key="1:2:3",
        default_directory=Path("/approved"),
    )

    assert state["current_directory"] == Path("/tmp/project")
    assert state["claude_session_id"] == "sess-123"
    assert state["claude_model"] == "sonnet"
    assert state["force_new_session"] is True

    # Re-fetch should return the same scoped state object.
    state_again = get_scope_state(
        user_data=user_data,
        scope_key="1:2:3",
        default_directory=Path("/approved"),
    )
    assert state_again is state


def test_get_scope_state_from_query_uses_query_context() -> None:
    """Callback query scope should default chat_id to user_id when missing."""
    user_data: dict = {}
    query = SimpleNamespace(
        from_user=SimpleNamespace(id=9),
        message=SimpleNamespace(message_thread_id=None),
    )

    scope_key, state = get_scope_state_from_query(
        user_data=user_data,
        query=query,
        default_directory=Path("/approved"),
    )

    assert scope_key == "9:9:0"
    assert state["current_directory"] == Path("/approved")
