"""Helpers for formatting status context/token usage."""

from typing import Any, Dict, List, Optional


def estimate_context_window_tokens(model_name: Optional[str]) -> Optional[int]:
    """Estimate context window size from model name/alias.

    Returns None when the model is unknown.
    """
    if not model_name:
        return None

    lower = str(model_name).strip().lower()
    if not lower:
        return None

    # Claude Code aliases exposed by /model command.
    if lower in {"sonnet", "opus", "haiku"}:
        return 200_000

    # Common Claude model identifiers.
    if "claude" in lower or "sonnet" in lower or "opus" in lower or "haiku" in lower:
        return 200_000

    return None


def build_model_usage_status_lines(
    model_usage: Dict[str, Any],
    current_model: Optional[str] = None,
    allow_estimated_ratio: bool = True,
) -> List[str]:
    """Build context/token usage lines for /status output."""
    status_lines: List[str] = []

    for model_name, usage in model_usage.items():
        if not isinstance(usage, dict):
            continue

        input_t = int(usage.get("inputTokens", 0) or 0)
        output_t = int(usage.get("outputTokens", 0) or 0)
        cache_read = int(usage.get("cacheReadInputTokens", 0) or 0)
        cache_create = int(usage.get("cacheCreationInputTokens", 0) or 0)
        total_tokens = input_t + output_t + cache_read + cache_create

        resolved_model = usage.get("resolvedModel")
        display_model = resolved_model or (
            current_model if model_name == "sdk" and current_model else model_name
        )

        raw_ctx_window = usage.get("contextWindow", 0) or 0
        ctx_window_source = str(usage.get("contextWindowSource") or "").strip().lower()
        inferred_ctx_window = estimate_context_window_tokens(
            resolved_model or (None if model_name == "sdk" else model_name) or current_model
        )
        ctx_window = int(raw_ctx_window or inferred_ctx_window or 0)
        estimated = bool(
            (ctx_window > 0 and ctx_window_source != "exact")
            or (not raw_ctx_window and inferred_ctx_window)
        )

        status_lines.append(f"\n*Context ({display_model})*")
        if ctx_window > 0 and (allow_estimated_ratio or not estimated):
            used_pct = total_tokens / ctx_window * 100
            remaining = max(ctx_window - total_tokens, 0)
            usage_line = (
                f"Usage: `{total_tokens:,}` / `{ctx_window:,}` ({used_pct:.1f}%)"
            )
            if estimated:
                usage_line += " _(estimated)_"
            status_lines.append(usage_line)
            status_lines.append(f"Remaining: `{remaining:,}` tokens")
        else:
            status_lines.append(f"Tokens: `{total_tokens:,}`")

        status_lines.append(f"  Input: `{input_t:,}` | Output: `{output_t:,}`")
        status_lines.append(
            f"  Cache read: `{cache_read:,}` | Cache create: `{cache_create:,}`"
        )
        max_output = int(usage.get("maxOutputTokens", 0) or 0)
        if max_output:
            status_lines.append(f"  Max output: `{max_output:,}`")

    return status_lines


def build_precise_context_status_lines(context_usage: Dict[str, Any]) -> List[str]:
    """Build status lines from exact /context probe output."""
    used_tokens = int(context_usage.get("used_tokens", 0) or 0)
    total_tokens = int(context_usage.get("total_tokens", 0) or 0)
    if total_tokens <= 0:
        return []

    used_percent = float(
        context_usage.get("used_percent", used_tokens / total_tokens * 100)
    )
    remaining_tokens = int(
        context_usage.get("remaining_tokens", max(total_tokens - used_tokens, 0))
    )
    cached = bool(context_usage.get("cached", False))

    header = "\n*Context (/context)*"
    if cached:
        header = "\n*Context (/context, cached)*"

    return [
        header,
        f"Usage: `{used_tokens:,}` / `{total_tokens:,}` ({used_percent:.1f}%) _(exact)_",
        f"Remaining: `{remaining_tokens:,}` tokens",
    ]
