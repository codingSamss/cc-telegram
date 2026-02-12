"""Tests for status context-usage formatting helpers."""

from src.bot.utils.status_usage import (
    build_model_usage_status_lines,
    estimate_context_window_tokens,
)


def test_estimate_context_window_tokens_for_alias():
    """Common /model aliases should map to a known context window."""
    assert estimate_context_window_tokens("sonnet") == 200_000
    assert estimate_context_window_tokens("opus") == 200_000
    assert estimate_context_window_tokens("haiku") == 200_000


def test_build_model_usage_status_lines_with_explicit_window():
    """When context window is provided, usage ratio should be exact."""
    lines = build_model_usage_status_lines(
        model_usage={
            "claude-sonnet-4-20250514": {
                "inputTokens": 40_000,
                "outputTokens": 10_000,
                "cacheReadInputTokens": 5_000,
                "cacheCreationInputTokens": 0,
                "contextWindow": 200_000,
            }
        },
        current_model="sonnet",
    )

    joined = "\n".join(lines)
    assert "Usage: `55,000` / `200,000` (27.5%)" in joined
    assert "estimated" not in joined


def test_build_model_usage_status_lines_with_estimated_window():
    """When window is missing, helper should provide estimated ratio."""
    lines = build_model_usage_status_lines(
        model_usage={
            "sdk": {
                "inputTokens": 80_000,
                "outputTokens": 20_000,
                "cacheReadInputTokens": 0,
                "cacheCreationInputTokens": 0,
            }
        },
        current_model="sonnet",
    )

    joined = "\n".join(lines)
    assert "Usage: `100,000` / `200,000` (50.0%) _(estimated)_" in joined
