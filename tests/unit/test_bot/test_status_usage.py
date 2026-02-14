"""Tests for status context-usage formatting helpers."""

from src.bot.utils.status_usage import (
    build_model_usage_status_lines,
    build_precise_context_status_lines,
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
                "contextWindowSource": "exact",
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


def test_build_model_usage_status_lines_marks_unknown_source_as_estimated():
    """Context window without explicit exact source should be labeled estimated."""
    lines = build_model_usage_status_lines(
        model_usage={
            "claude-opus-4-6": {
                "inputTokens": 32_000,
                "outputTokens": 500,
                "cacheReadInputTokens": 0,
                "cacheCreationInputTokens": 0,
                "contextWindow": 200_000,
            }
        },
        current_model="opus",
    )

    joined = "\n".join(lines)
    assert "Usage: `32,500` / `200,000` (16.2%) _(estimated)_" in joined


def test_build_model_usage_status_lines_can_hide_estimated_ratio():
    """Estimated ratio should be suppressible when exact /context exists."""
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
        allow_estimated_ratio=False,
    )

    joined = "\n".join(lines)
    assert "Usage:" not in joined
    assert "Tokens: `100,000`" in joined


def test_build_precise_context_status_lines_marks_exact_source():
    """Precise context lines should include exact marker and cached hint."""
    lines = build_precise_context_status_lines(
        {
            "used_tokens": 55_000,
            "total_tokens": 200_000,
            "remaining_tokens": 145_000,
            "used_percent": 27.5,
            "cached": True,
        }
    )

    joined = "\n".join(lines)
    assert "Context (/context, cached)" in joined
    assert "Usage: `55,000` / `200,000` (27.5%) _(exact)_" in joined


def test_build_precise_context_status_lines_supports_status_probe_label():
    """Precise context lines should reflect probe command when provided."""
    lines = build_precise_context_status_lines(
        {
            "used_tokens": 84_000,
            "total_tokens": 200_000,
            "remaining_tokens": 116_000,
            "used_percent": 42.0,
            "probe_command": "/status",
            "cached": False,
        }
    )

    joined = "\n".join(lines)
    assert "Context (/status)" in joined
    assert "Usage: `84,000` / `200,000` (42.0%) _(exact)_" in joined


def test_build_model_usage_status_lines_supports_codex_flat_usage_payload():
    """Codex turn usage payload (snake_case flat dict) should be rendered."""
    lines = build_model_usage_status_lines(
        model_usage={
            "input_tokens": 120,
            "cached_input_tokens": 40,
            "output_tokens": 15,
            "model": "gpt-5",
        },
        current_model="gpt-5",
    )

    joined = "\n".join(lines)
    assert "Context (gpt-5)" in joined
    assert "Tokens: `175`" in joined
    assert "Input: `120` | Output: `15`" in joined
