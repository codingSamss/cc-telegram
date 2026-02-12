"""Tests for SDK model usage mapping in status data."""

from src.claude.sdk_integration import ClaudeSDKManager
from src.config.settings import Settings


def test_build_model_usage_includes_resolved_model_and_context_window(tmp_path):
    """SDK usage payload should include resolved model and context window estimate."""
    settings = Settings(
        telegram_bot_token="test:token",
        telegram_bot_username="testbot",
        approved_directory=tmp_path,
        use_sdk=True,
    )
    manager = ClaudeSDKManager(settings)

    usage = manager._build_model_usage(
        sdk_usage={
            "input_tokens": 1234,
            "output_tokens": 567,
            "cache_read_input_tokens": 10,
            "cache_creation_input_tokens": 20,
        },
        cost=0.01,
        resolved_model="claude-sonnet-4-20250514",
    )

    assert usage is not None
    assert "claude-sonnet-4-20250514" in usage
    payload = usage["claude-sonnet-4-20250514"]
    assert payload["resolvedModel"] == "claude-sonnet-4-20250514"
    assert payload["contextWindow"] == 200_000
