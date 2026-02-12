"""Tests for Claude subprocess integration parsing behavior."""

from pathlib import Path

from src.claude.integration import ClaudeProcessManager
from src.config.settings import Settings


def _build_manager(tmp_path: Path) -> ClaudeProcessManager:
    config = Settings(
        telegram_bot_token="test:token",
        telegram_bot_username="testbot",
        approved_directory=tmp_path,
        claude_timeout_seconds=5,
    )
    return ClaudeProcessManager(config)


def test_parse_result_uses_local_command_stdout_fallback(tmp_path):
    """When result text is empty, parser should use local-command stdout payload."""
    manager = _build_manager(tmp_path)
    result = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "duration_ms": 100,
        "num_turns": 1,
        "session_id": "session-1",
        "total_cost_usd": 0.0,
        "result": "",
        "modelUsage": {},
    }
    messages = [
        {
            "type": "user",
            "message": {
                "content": (
                    "<local-command-stdout>\n"
                    "## Context Usage\n"
                    "**Tokens:** 28.8k / 200k (14%)\n"
                    "</local-command-stdout>"
                )
            },
        }
    ]

    response = manager._parse_result(result, messages)

    assert "28.8k / 200k" in response.content


def test_extract_local_command_output_ignores_plain_user_text(tmp_path):
    """Regular user message text should not be treated as local command output."""
    manager = _build_manager(tmp_path)

    extracted = manager._extract_local_command_output("hello world")

    assert extracted == ""
