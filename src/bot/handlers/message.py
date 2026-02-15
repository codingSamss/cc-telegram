"""Message handlers for non-command inputs."""

import asyncio
import base64
import binascii
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional
from uuid import uuid4

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ...claude.exceptions import ClaudeToolValidationError
from ...claude.task_registry import TaskRegistry
from ...config.settings import Settings
from ...security.audit import AuditLogger
from ...security.rate_limiter import RateLimiter
from ...security.validators import SecurityValidator
from ...services.session_service import SessionService
from ...utils.codex_rate_limits import format_rate_limit_summary
from ..utils.cli_engine import (
    ENGINE_CLAUDE,
    ENGINE_CODEX,
    get_cli_integration,
    get_engine_primary_status_command,
    normalize_cli_engine,
)
from ..utils.scope_state import get_scope_state_from_update

logger = structlog.get_logger()

_IMAGE_STATUS_TOTAL_STEPS = 6
_TELEGRAM_MESSAGE_LIMIT = 4096
_TELEGRAM_SAFE_SPLIT_LIMIT = 3900


def _escape_md(text: str) -> str:
    """Escape special characters for Telegram legacy Markdown."""
    for ch in ("_", "*", "`", "["):
        text = text.replace(ch, f"\\{ch}")
    return text


def _extract_tool_summary(tool_name: str, tool_input: dict) -> str:
    """Extract a concise summary of what a tool is doing from its input."""
    if not tool_input:
        return tool_name

    if tool_name == "Bash" and "command" in tool_input:
        cmd = tool_input["command"].strip()
        # Show first line, truncate long commands
        first_line = cmd.split("\n")[0]
        if len(first_line) > 80:
            first_line = first_line[:77] + "..."
        return f"Bash: `{first_line}`"

    if tool_name in ("Read", "ReadFile") and "file_path" in tool_input:
        return f"Read: `{tool_input['file_path']}`"

    if tool_name == "Write" and "file_path" in tool_input:
        return f"Write: `{tool_input['file_path']}`"

    if tool_name == "Edit" and "file_path" in tool_input:
        return f"Edit: `{tool_input['file_path']}`"

    if tool_name == "MultiEdit" and "file_path" in tool_input:
        return f"MultiEdit: `{tool_input['file_path']}`"

    if tool_name in ("Glob", "Grep") and "pattern" in tool_input:
        pattern = tool_input["pattern"]
        if len(pattern) > 60:
            pattern = pattern[:57] + "..."
        return f"{tool_name}: `{pattern}`"

    if tool_name == "WebFetch" and "url" in tool_input:
        url = tool_input["url"]
        if len(url) > 60:
            url = url[:57] + "..."
        return f"WebFetch: `{url}`"

    if tool_name == "Task" and "description" in tool_input:
        desc = tool_input["description"]
        if len(desc) > 60:
            desc = desc[:57] + "..."
        return f"Task: {desc}"

    # Generic: show tool name with first key hint
    for key in ("path", "file_path", "query", "command", "name"):
        if key in tool_input:
            val = str(tool_input[key])
            if len(val) > 60:
                val = val[:57] + "..."
            return f"{tool_name}: `{val}`"

    return tool_name


def _stream_engine_label(update_obj: Any) -> str:
    """Resolve engine label from stream update metadata."""
    metadata = getattr(update_obj, "metadata", None) or {}
    engine = str(metadata.get("engine") or "").strip().lower()
    if engine == "codex":
        return "Codex"
    return "Claude"


def _engine_label(engine: str | None) -> str:
    """Render normalized engine label for user-facing messages."""
    normalized = normalize_cli_engine(engine)
    if normalized == ENGINE_CODEX:
        return "Codex"
    return "Claude"


def _engine_badge(engine: str | None) -> str:
    """Render a compact engine badge for Telegram message bubbles."""
    normalized = normalize_cli_engine(engine)
    marker = "🟦" if normalized == ENGINE_CODEX else "🟩"
    return f"{marker} `{_engine_label(normalized)} CLI`"


def _with_engine_badge(text: str, engine: str | None) -> str:
    """Attach engine badge to a bubble text, keeping payload readable."""
    body = str(text or "").strip()
    badge = _engine_badge(engine)
    if not body:
        return badge
    return f"{badge}\n{body}"


def _is_markdown_parse_error(error: Exception) -> bool:
    """Whether a Telegram send failure is caused by Markdown entity parsing."""
    error_text = str(error).lower()
    return "can't parse entities" in error_text or "cannot parse entities" in error_text


def _is_message_too_long_error(error: Exception) -> bool:
    """Whether a Telegram send failure is caused by message length overflow."""
    error_text = str(error).lower()
    return (
        "message is too long" in error_text
        or "text is too long" in error_text
        or "entity is too long" in error_text
    )


def _split_text_for_telegram(
    text: str, limit: int = _TELEGRAM_SAFE_SPLIT_LIMIT
) -> list[str]:
    """Split long plain text into Telegram-safe chunks."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        split_at = remaining.rfind("\n", 0, limit + 1)
        if split_at <= 0:
            split_at = remaining.rfind(" ", 0, limit + 1)
        if split_at <= 0:
            split_at = limit

        chunk = remaining[:split_at].rstrip()
        if not chunk:
            chunk = remaining[:limit]
            split_at = len(chunk)

        chunks.append(chunk)
        remaining = remaining[split_at:].lstrip("\n")

    return chunks


async def _reply_text_resilient(
    telegram_message: Any,
    text: str,
    *,
    parse_mode: Optional[str] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    reply_to_message_id: Optional[int] = None,
) -> None:
    """Send reply text with fallback for Markdown parse and long text errors."""
    send_kwargs: dict[str, Any] = {}
    if parse_mode:
        send_kwargs["parse_mode"] = parse_mode
    if reply_markup is not None:
        send_kwargs["reply_markup"] = reply_markup
    if reply_to_message_id is not None:
        send_kwargs["reply_to_message_id"] = reply_to_message_id

    try:
        await telegram_message.reply_text(text, **send_kwargs)
        return
    except Exception as send_error:
        final_error: Exception = send_error

    # Markdown parsing can fail with raw stack traces or unescaped symbols.
    if parse_mode and _is_markdown_parse_error(final_error):
        no_md_kwargs = dict(send_kwargs)
        no_md_kwargs.pop("parse_mode", None)
        try:
            await telegram_message.reply_text(text, **no_md_kwargs)
            return
        except Exception as no_md_error:
            final_error = no_md_error

    if _is_message_too_long_error(final_error) or len(text) > _TELEGRAM_MESSAGE_LIMIT:
        chunks = _split_text_for_telegram(text)
        for idx, chunk in enumerate(chunks):
            chunk_kwargs: dict[str, Any] = {}
            if idx == 0 and reply_markup is not None:
                chunk_kwargs["reply_markup"] = reply_markup
            if idx == 0 and reply_to_message_id is not None:
                chunk_kwargs["reply_to_message_id"] = reply_to_message_id
            await telegram_message.reply_text(chunk, **chunk_kwargs)
        return

    raise final_error


def _integration_supports_image_analysis(cli_integration: Any) -> bool:
    """Whether the integration can process multimodal image requests."""
    if not cli_integration:
        return False
    config = getattr(cli_integration, "config", None)
    sdk_manager = getattr(cli_integration, "sdk_manager", None)
    if getattr(config, "use_sdk", False) and sdk_manager is not None:
        return True
    process_manager = getattr(cli_integration, "process_manager", None)
    supports_images = getattr(process_manager, "supports_image_inputs", None)
    if callable(supports_images):
        try:
            return bool(supports_images())
        except Exception:
            return False
    return False


def _integration_uses_cli_image_files(cli_integration: Any) -> bool:
    """Whether integration needs local image files for subprocess image input."""
    if not cli_integration:
        return False
    config = getattr(cli_integration, "config", None)
    if getattr(config, "use_sdk", False):
        return False
    process_manager = getattr(cli_integration, "process_manager", None)
    supports_images = getattr(process_manager, "supports_image_inputs", None)
    if callable(supports_images):
        try:
            return bool(supports_images())
        except Exception:
            return False
    return False


def _persist_cli_image_file(
    *,
    base64_data: str,
    image_format: str,
    working_directory: Path,
) -> Path:
    """Persist uploaded image bytes to local file for Codex CLI --image."""
    try:
        payload = base64.b64decode(base64_data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("图片编码无效，无法提交给 Codex。") from exc

    images_dir = working_directory / ".claude-images"
    images_dir.mkdir(parents=True, exist_ok=True)

    normalized = (image_format or "jpeg").strip().lower()
    ext_map = {"jpeg": "jpg", "jpg": "jpg", "png": "png", "gif": "gif", "webp": "webp"}
    extension = ext_map.get(normalized, "jpg")
    image_path = images_dir / f"tg-upload-{uuid4().hex}.{extension}"
    image_path.write_bytes(payload)
    return image_path


def _cleanup_cli_image_file(image_path: Optional[Path]) -> None:
    """Best-effort deletion for temporary CLI image file."""
    if not image_path:
        return
    try:
        image_path.unlink(missing_ok=True)
    except Exception as e:
        logger.warning(
            "Failed to cleanup temporary CLI image file",
            image_path=str(image_path),
            error=str(e),
        )


async def _format_progress_update(update_obj) -> Optional[str]:
    """Format progress updates with enhanced context and visual indicators."""
    if update_obj.type == "tool_result":
        # Show tool completion status
        tool_name = "Unknown"
        if update_obj.metadata and update_obj.metadata.get("tool_use_id"):
            # Try to extract tool name from context if available
            tool_name = update_obj.metadata.get("tool_name", "Tool")

        safe_tool_name = _escape_md(tool_name)

        if update_obj.is_error():
            safe_error = _escape_md(update_obj.get_error_message())
            return f"❌ *{safe_tool_name} failed*\n\n{safe_error}"
        else:
            execution_time = ""
            if update_obj.metadata and update_obj.metadata.get("execution_time_ms"):
                time_ms = update_obj.metadata["execution_time_ms"]
                execution_time = f" ({time_ms}ms)"
            return f"✅ *{safe_tool_name} completed*{execution_time}"

    elif update_obj.type == "progress":
        # Handle progress updates
        metadata = update_obj.metadata or {}
        if metadata.get("item_type") == "command_execution":
            status = str(metadata.get("status") or "").strip().lower()
            command = str(metadata.get("command") or update_obj.content or "").strip()
            first_line = command.split("\n")[0] if command else ""
            if len(first_line) > 100:
                first_line = first_line[:97] + "..."
            safe_command = _escape_md(first_line or "(empty)")
            if status == "in_progress":
                return f"🔧 *Running command*\n\n`{safe_command}`"
            if status == "completed":
                exit_code = metadata.get("exit_code")
                suffix = (
                    f" \\(exit {int(exit_code)}\\)"
                    if isinstance(exit_code, int)
                    else ""
                )
                return f"✅ *Command completed*{suffix}\n\n`{safe_command}`"
            if status in {"failed", "error", "cancelled"}:
                exit_code = metadata.get("exit_code")
                suffix = (
                    f" \\(exit {int(exit_code)}\\)"
                    if isinstance(exit_code, int)
                    else ""
                )
                return f"❌ *Command {status}*{suffix}\n\n`{safe_command}`"

        safe_content = _escape_md(update_obj.content or "Working...")
        progress_text = f"🔄 *{safe_content}*"

        percentage = update_obj.get_progress_percentage()
        if percentage is not None:
            # Create a simple progress bar
            filled = int(percentage / 10)  # 0-10 scale
            bar = "█" * filled + "░" * (10 - filled)
            progress_text += f"\n\n`{bar}` {percentage}%"

        if update_obj.progress:
            step = update_obj.progress.get("step")
            total_steps = update_obj.progress.get("total_steps")
            if step and total_steps:
                progress_text += f"\n\nStep {step} of {total_steps}"

        return progress_text

    elif update_obj.type == "error":
        # Handle error messages
        safe_error = _escape_md(update_obj.get_error_message())
        return f"❌ *Error*\n\n{safe_error}"

    elif update_obj.type == "assistant" and update_obj.tool_calls:
        # Show when tools are being called with operation details
        summaries = []
        for tc in update_obj.tool_calls:
            name = tc.get("name", "unknown")
            inp = tc.get("input", {})
            summaries.append(_escape_md(_extract_tool_summary(name, inp)))
        if summaries:
            return "\n".join(f"🔧 {s}" for s in summaries)

    elif update_obj.type == "assistant" and update_obj.content:
        # Regular content updates with preview
        content_preview = (
            update_obj.content[:150] + "..."
            if len(update_obj.content) > 150
            else update_obj.content
        )
        safe_preview = _escape_md(content_preview)
        engine_label = _stream_engine_label(update_obj)
        return f"🤖 *{engine_label} is working...*\n\n{safe_preview}"

    elif update_obj.type == "system":
        # System initialization or other system messages
        if update_obj.metadata and update_obj.metadata.get("subtype") == "init":
            tools_count = len(update_obj.metadata.get("tools", []))
            # Avoid showing potentially stale requested/default model names here.
            # Actual model should be shown only after resolution.
            engine_label = _stream_engine_label(update_obj)
            return f"🚀 *Starting {engine_label}* with {tools_count} tools available"
        if (
            update_obj.metadata
            and update_obj.metadata.get("subtype") == "model_resolved"
        ):
            model = _escape_md(update_obj.metadata.get("model", "Claude"))
            return f"🧠 *Using model:* {model}"

    return None


def _format_error_message(error_str: str, *, engine: str = ENGINE_CLAUDE) -> str:
    """Format error messages for user-friendly display."""
    normalized_engine = normalize_cli_engine(engine)
    engine_label = _engine_label(normalized_engine)
    status_command = get_engine_primary_status_command(normalized_engine)

    if "usage limit reached" in error_str.lower():
        # Usage limit error - already user-friendly from integration.py
        return error_str
    elif "tool not allowed" in error_str.lower():
        # Tool validation error - already handled in facade.py
        return error_str
    elif "no conversation found" in error_str.lower():
        return (
            f"🔄 **Session Not Found**\n\n"
            f"The {engine_label} session could not be found or has expired.\n\n"
            f"**What you can do:**\n"
            f"• Use `/new` to start a fresh session\n"
            f"• Try your request again\n"
            f"• Use `/{status_command}` to check your current session"
        )
    elif "rate limit" in error_str.lower():
        return (
            f"⏱️ **Rate Limit Reached**\n\n"
            f"Too many requests in a short time period.\n\n"
            f"**What you can do:**\n"
            f"• Wait a moment before trying again\n"
            f"• Use simpler requests\n"
            f"• Check your current usage with `/{status_command}`"
        )
    elif "timeout" in error_str.lower():
        return (
            f"⏰ **Request Timeout**\n\n"
            f"Your request took too long to process and timed out.\n\n"
            f"**What you can do:**\n"
            f"• Try breaking down your request into smaller parts\n"
            f"• Use simpler commands\n"
            f"• Try again in a moment"
        )
    else:
        # Generic error handling
        # Escape special markdown characters in error message
        # Replace problematic chars that break Telegram markdown
        safe_error = (
            error_str.replace("_", "\\_")
            .replace("*", "\\*")
            .replace("`", "\\`")
            .replace("[", "\\[")
        )
        # Truncate very long errors
        if len(safe_error) > 200:
            safe_error = safe_error[:200] + "..."

        return (
            f"❌ **{engine_label} CLI Error**\n\n"
            f"Failed to process your request: {safe_error}\n\n"
            f"Please try again or contact the administrator if the problem persists."
        )


def _is_timeout_error(error: Exception | str | None) -> bool:
    """Detect if a Telegram API error was caused by a timeout."""

    if error is None:
        return False
    raw = error if isinstance(error, str) else str(error)
    return "timeout" in raw.lower()


def _get_stream_merge_key(update_obj: Any) -> Optional[str]:
    """Return merge key for high-frequency stream updates, or None if not mergeable."""
    if (
        update_obj.type == "assistant"
        and update_obj.content
        and not update_obj.tool_calls
    ):
        return "assistant_content"
    if update_obj.type == "progress":
        return "progress"
    return None


def _is_high_priority_stream_update(update_obj: Any) -> bool:
    """Whether a stream update should bypass debounce and flush immediately."""
    if update_obj.type in {"error", "tool_result"}:
        return True

    if update_obj.type == "assistant" and update_obj.tool_calls:
        return True

    if update_obj.type == "system" and update_obj.metadata:
        return update_obj.metadata.get("subtype") in {"init", "model_resolved"}

    return False


def _is_noop_edit_error(error: Exception) -> bool:
    """Check whether Telegram rejected edit because content is unchanged."""
    return "message is not modified" in str(error).lower()


def _append_progress_line_with_merge(
    progress_lines: list[str],
    progress_merge_keys: list[Optional[str]],
    progress_text: str,
    merge_key: Optional[str],
) -> None:
    """Append progress line or merge into previous line when merge key matches."""
    if (
        merge_key
        and progress_lines
        and progress_merge_keys
        and progress_merge_keys[-1] == merge_key
    ):
        progress_lines[-1] = progress_text
        progress_merge_keys[-1] = merge_key
        return

    # Skip exact consecutive duplicates to reduce noisy UI refreshes.
    if progress_lines and progress_lines[-1] == progress_text:
        return

    progress_lines.append(progress_text)
    progress_merge_keys.append(merge_key)


def _build_context_tag(
    scope_state: dict,
    approved_directory: Path,
    active_engine: str,
    session_id: Optional[str],
    session_context_summary: Optional[str] = None,
    rate_limit_summary: Optional[str] = None,
) -> str:
    """Build a compact context tag line for display in thinking summary or reply header.

    Format: engine_badge | project_name | sid_short
    """
    current_dir = scope_state.get("current_directory", approved_directory)
    project_name = current_dir.name if current_dir and current_dir.name else "~"
    sid_short = (session_id or "no-session")[:8]
    lines = [f"{_engine_badge(active_engine)} | `{project_name}` | `{sid_short}`"]
    if session_context_summary:
        lines.append(session_context_summary)
    if rate_limit_summary:
        lines.append(f"🔋 {rate_limit_summary}")
    return "\n".join(lines)


def _build_session_context_summary(snapshot: Optional[dict[str, Any]]) -> Optional[str]:
    """Render current session context usage summary from cached Codex snapshot."""
    if not isinstance(snapshot, dict):
        return None

    used_percent: Optional[float] = None
    try:
        used_percent = float(snapshot.get("used_percent"))
    except (TypeError, ValueError):
        used_percent = None

    total_tokens_raw = snapshot.get("total_tokens")
    remaining_tokens_raw = snapshot.get("remaining_tokens")
    remaining_percent: Optional[float] = None
    try:
        total_tokens = int(total_tokens_raw or 0)
        remaining_tokens = int(remaining_tokens_raw or 0)
        if total_tokens > 0:
            remaining_percent = max(
                min(remaining_tokens / total_tokens * 100, 100.0), 0.0
            )
    except (TypeError, ValueError):
        remaining_percent = None

    if remaining_percent is None and used_percent is not None:
        remaining_percent = max(min(100.0 - used_percent, 100.0), 0.0)

    if remaining_percent is None:
        return None

    return "🧠 Session context: " f"`{remaining_percent:.1f}%` remaining"


def _generate_thinking_summary(all_progress_lines: list[str]) -> str:
    """Generate a one-line summary from progress lines."""
    # Match both old format "Using tools:" and new format "🔧 ToolName:"
    tool_count = sum(
        1
        for line in all_progress_lines
        if "Using tools:" in line or (line.startswith("🔧") and ":" in line)
    )
    complete_count = sum(1 for line in all_progress_lines if "completed" in line)
    error_count = sum(
        1 for line in all_progress_lines if "failed" in line or "Error" in line
    )

    parts = []
    if tool_count:
        parts.append(f"{tool_count} tools called")
    if complete_count:
        parts.append(f"{complete_count} completed")
    if error_count:
        parts.append(f"{error_count} errors")

    summary = "Thinking done"
    if parts:
        summary += " -- " + ", ".join(parts)
    return summary


def _cache_thinking_data(
    context: ContextTypes.DEFAULT_TYPE,
    message_id: int,
    lines: list[str],
    summary: str,
    max_cache: int = 5,
) -> None:
    """Cache thinking process into context.user_data, keep latest max_cache entries."""
    cache_key = f"thinking:{message_id}"
    context.user_data[cache_key] = {
        "lines": list(lines),
        "summary": summary,
    }

    # Clean old cache: only keep latest max_cache entries
    thinking_keys = sorted(
        [k for k in context.user_data if k.startswith("thinking:")],
        key=lambda k: int(k.split(":")[1]),
    )
    while len(thinking_keys) > max_cache:
        oldest = thinking_keys.pop(0)
        context.user_data.pop(oldest, None)


def _format_elapsed_time(total_seconds: int) -> str:
    """Format elapsed seconds as mm:ss."""
    minutes = max(total_seconds, 0) // 60
    seconds = max(total_seconds, 0) % 60
    return f"{minutes:02d}:{seconds:02d}"


def _image_heartbeat_interval_seconds(elapsed_seconds: int) -> int:
    """Adaptive heartbeat interval for image analysis status updates."""
    if elapsed_seconds < 30:
        return 6
    if elapsed_seconds < 90:
        return 12
    return 20


def _build_image_stage_status(
    step: int,
    title: str,
    detail: Optional[str] = None,
) -> str:
    """Build a user-friendly status message for image processing."""
    lines = [
        "📸 **图片分析中**",
        "",
        f"`{step}/{_IMAGE_STATUS_TOTAL_STEPS}` {title}",
    ]
    if detail:
        lines.extend(["", detail])
    return "\n".join(lines)


def _build_image_analyzing_status(
    elapsed_seconds: int, engine_label: str = "当前引擎"
) -> str:
    """Build analysis-stage status with elapsed-time heartbeat text."""
    detail = f"已等待 `{_format_elapsed_time(elapsed_seconds)}`"
    if elapsed_seconds >= 90:
        detail += f"\n⏳ 响应时间较长，但 {engine_label} 仍在处理中。"
    return _build_image_stage_status(
        5, f"{engine_label} 正在分析图片...", detail=detail
    )


async def _run_with_image_analysis_heartbeat(
    *,
    run_coro: Awaitable[Any],
    update_status: Callable[[str], Awaitable[None]],
    engine_label: str = "当前引擎",
) -> Any:
    """Run image analysis while sending adaptive heartbeat updates."""
    task = asyncio.create_task(run_coro)
    loop = asyncio.get_event_loop()
    start_time = loop.time()
    last_heartbeat_at = 0

    while True:
        done, _ = await asyncio.wait({task}, timeout=1)
        if task in done:
            return await task

        elapsed = int(loop.time() - start_time)
        interval = _image_heartbeat_interval_seconds(elapsed)
        if elapsed > 0 and (elapsed - last_heartbeat_at) >= interval:
            await update_status(
                _build_image_analyzing_status(elapsed, engine_label=engine_label)
            )
            last_heartbeat_at = elapsed


async def handle_text_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle regular text messages as Claude prompts."""
    user_id = update.effective_user.id
    message_text = update.message.text
    settings: Settings = context.bot_data["settings"]
    scope_key, scope_state = get_scope_state_from_update(
        user_data=context.user_data,
        update=update,
        default_directory=settings.approved_directory,
    )

    # Get services
    rate_limiter: Optional[RateLimiter] = context.bot_data.get("rate_limiter")
    audit_logger: Optional[AuditLogger] = context.bot_data.get("audit_logger")

    logger.info(
        "Processing text message", user_id=user_id, message_length=len(message_text)
    )

    try:
        # Check rate limit with estimated cost for text processing
        estimated_cost = _estimate_text_processing_cost(message_text)

        if rate_limiter:
            allowed, limit_message = await rate_limiter.check_rate_limit(
                user_id, estimated_cost
            )
            if not allowed:
                await update.message.reply_text(f"⏱️ {limit_message}")
                return

        # Check if user already has an active task
        task_registry: Optional[TaskRegistry] = context.bot_data.get("task_registry")
        if task_registry and await task_registry.is_busy(user_id, scope_key=scope_key):
            await update.message.reply_text(
                "A task is already running. Use /cancel to cancel it."
            )
            return

        # Send typing indicator
        await update.message.chat.send_action("typing")

        # Resolve active CLI engine integration and storage from context
        active_engine, cli_integration = get_cli_integration(
            bot_data=context.bot_data,
            scope_state=scope_state,
        )
        storage = context.bot_data.get("storage")

        if not cli_integration:
            await update.message.reply_text(
                _with_engine_badge(
                    "❌ **CLI 引擎不可用**\n\n"
                    "当前 CLI 引擎未正确配置。"
                    " "
                    "Please contact the administrator.",
                    active_engine,
                ),
                parse_mode="Markdown",
            )
            return

        # Create progress message with Cancel button
        cancel_keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Cancel", callback_data="cancel:task")]]
        )
        progress_msg = await update.message.reply_text(
            _with_engine_badge("🤔 正在处理你的请求...", active_engine),
            parse_mode="Markdown",
            reply_to_message_id=update.message.message_id,
            reply_markup=cancel_keyboard,
        )

        # Get current directory
        current_dir = scope_state.get("current_directory", settings.approved_directory)

        # Get existing session ID
        session_id = scope_state.get("claude_session_id")
        # Read but don't consume yet -- consume only after successful execution
        # so that the protection survives retries on failure.
        force_new_session = scope_state.get("force_new_session", False)

        # Enhanced stream updates handler with accumulated progress tracking
        progress_lines: list[str] = []
        progress_merge_keys: list[Optional[str]] = []
        all_progress_lines: list[str] = []  # 完整思考过程（不受溢出 clear 影响）
        frozen_messages: list = []  # 被冻结的旧进度消息
        last_progress_text = ""
        pending_progress_text: Optional[str] = None
        progress_flush_task: Optional[asyncio.Task] = None
        progress_flush_lock = asyncio.Lock()
        stream_loop = asyncio.get_event_loop()
        debounce_seconds = max(settings.stream_render_debounce_ms, 0) / 1000
        min_edit_interval_seconds = (
            max(settings.stream_render_min_edit_interval_ms, 0) / 1000
        )
        last_progress_edit_ts = stream_loop.time()
        progress_edit_attempts = 0
        PROGRESS_EDIT_RETRY_LIMIT = 3
        progress_edit_attempts = 0
        PROGRESS_EDIT_RETRY_LIMIT = 3

        async def _flush_pending_progress(force: bool = False) -> None:
            nonlocal progress_msg, last_progress_text, pending_progress_text, last_progress_edit_ts

            async with progress_flush_lock:
                if not pending_progress_text:
                    return

                now = stream_loop.time()
                wait_seconds = 0.0
                if not force:
                    wait_seconds = max(
                        0.0, min_edit_interval_seconds - (now - last_progress_edit_ts)
                    )
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)

                # Always use latest pending content (it may have changed while waiting).
                text_to_send = pending_progress_text
                if not text_to_send or text_to_send == last_progress_text:
                    return

                async def _refresh_with_new_message() -> None:
                    nonlocal progress_msg, last_progress_edit_ts
                    try:
                        await progress_msg.edit_reply_markup(reply_markup=None)
                    except Exception:
                        pass
                    progress_msg = await progress_msg.reply_text(
                        text_to_send,
                        parse_mode="Markdown",
                        reply_markup=cancel_keyboard,
                    )
                    last_progress_edit_ts = stream_loop.time()

                try:
                    await progress_msg.edit_text(
                        text_to_send,
                        parse_mode="Markdown",
                        reply_markup=cancel_keyboard,
                    )
                    last_progress_text = text_to_send
                    last_progress_edit_ts = stream_loop.time()
                except Exception as e:
                    if _is_noop_edit_error(e):
                        last_progress_text = text_to_send
                        last_progress_edit_ts = stream_loop.time()
                        return

                    fallback_error: Exception | None = None
                    timeout_error = _is_timeout_error(e)
                    try:
                        await progress_msg.edit_text(
                            text_to_send,
                            reply_markup=cancel_keyboard,
                        )
                        last_progress_text = text_to_send
                        last_progress_edit_ts = stream_loop.time()
                    except Exception as exc:
                        fallback_error = exc
                        if _is_noop_edit_error(exc):
                            last_progress_text = text_to_send
                            last_progress_edit_ts = stream_loop.time()
                            return
                        timeout_error = timeout_error or _is_timeout_error(exc)
                    if timeout_error:
                        await _refresh_with_new_message()
                        last_progress_text = text_to_send
                        return
                    logger.warning(
                        "Failed to update progress message",
                        error=str(e),
                        fallback_error=str(fallback_error) if fallback_error else None,
                    )

        def _schedule_progress_flush() -> None:
            nonlocal progress_flush_task

            if progress_flush_task and not progress_flush_task.done():
                return

            async def _runner():
                try:
                    if debounce_seconds > 0:
                        await asyncio.sleep(debounce_seconds)
                    await _flush_pending_progress(force=False)
                except asyncio.CancelledError:
                    return

            progress_flush_task = asyncio.create_task(_runner())

        async def _cancel_progress_flush_task() -> None:
            nonlocal progress_flush_task
            if progress_flush_task and not progress_flush_task.done():
                progress_flush_task.cancel()
                try:
                    await progress_flush_task
                except asyncio.CancelledError:
                    pass
            progress_flush_task = None

        async def stream_handler(update_obj):
            nonlocal progress_msg, last_progress_text, pending_progress_text
            nonlocal last_progress_edit_ts
            try:
                progress_text = await _format_progress_update(update_obj)
                if not progress_text:
                    return

                merge_key = _get_stream_merge_key(update_obj)
                _append_progress_line_with_merge(
                    progress_lines=progress_lines,
                    progress_merge_keys=progress_merge_keys,
                    progress_text=progress_text,
                    merge_key=merge_key,
                )
                # Only collect non-content updates as thinking process
                if not (
                    update_obj.type == "assistant"
                    and update_obj.content
                    and not update_obj.tool_calls
                ):
                    all_progress_lines.append(progress_text)
                full_text = _with_engine_badge("\n".join(progress_lines), active_engine)

                # If accumulated text exceeds Telegram limit, freeze current
                # message and start a new one
                if len(full_text) > 3800:
                    await _cancel_progress_flush_task()
                    pending_progress_text = None
                    frozen_messages.append(progress_msg)
                    progress_lines.clear()
                    progress_merge_keys.clear()
                    _append_progress_line_with_merge(
                        progress_lines=progress_lines,
                        progress_merge_keys=progress_merge_keys,
                        progress_text=progress_text,
                        merge_key=merge_key,
                    )
                    full_text = _with_engine_badge(progress_text, active_engine)
                    last_progress_text = ""
                    # Remove cancel button from old message
                    try:
                        await progress_msg.edit_reply_markup(reply_markup=None)
                    except Exception:
                        pass
                    progress_msg = await progress_msg.reply_text(
                        full_text,
                        parse_mode="Markdown",
                        reply_markup=cancel_keyboard,
                    )
                    last_progress_text = full_text
                    last_progress_edit_ts = stream_loop.time()
                    return

                # Skip edit if content hasn't changed
                if full_text == last_progress_text:
                    return

                pending_progress_text = full_text
                if _is_high_priority_stream_update(update_obj):
                    await _cancel_progress_flush_task()
                    await _flush_pending_progress(force=True)
                else:
                    _schedule_progress_flush()
            except Exception as e:
                logger.warning("Failed to process stream update", error=str(e))

        # Build permission handler only when SDK is active
        settings_obj: Settings = context.bot_data["settings"]
        permission_handler = build_permission_handler(
            bot=context.bot, chat_id=update.effective_chat.id, settings=settings_obj
        )

        # Run Claude command as cancellable task

        async def _run_claude():
            return await cli_integration.run_command(
                prompt=message_text,
                working_directory=current_dir,
                user_id=user_id,
                session_id=session_id,
                on_stream=stream_handler,
                force_new_session=force_new_session,
                permission_handler=permission_handler,
                model=scope_state.get("claude_model"),
            )

        task = asyncio.create_task(_run_claude())

        # Register task for cancel support
        if task_registry:
            await task_registry.register(
                user_id,
                task,
                prompt_summary=message_text,
                progress_message_id=progress_msg.message_id,
                chat_id=update.effective_chat.id,
                scope_key=scope_key,
            )

        claude_response = None
        try:
            claude_response = await task

            # Mark task as completed
            if task_registry:
                await task_registry.complete(user_id, scope_key=scope_key)

            # Update session ID
            scope_state["claude_session_id"] = claude_response.session_id
            # Consume force_new_session only after success
            scope_state.pop("force_new_session", None)

            # Check if Claude changed the working directory and update our tracking
            _update_working_directory_from_claude_response(
                claude_response, scope_state, settings, user_id
            )

            # Log interaction to storage
            if storage:
                try:
                    await storage.save_claude_interaction(
                        user_id=user_id,
                        session_id=claude_response.session_id,
                        prompt=message_text,
                        response=claude_response,
                        ip_address=None,  # Telegram doesn't provide IP
                    )
                except Exception as e:
                    logger.warning("Failed to log interaction to storage", error=str(e))

            # Format response
            from ..utils.formatting import ResponseFormatter

            formatter = ResponseFormatter(settings)
            formatted_messages = formatter.format_claude_response(
                claude_response.content
            )

        except asyncio.CancelledError:
            logger.info("Claude task cancelled by user", user_id=user_id)
            await _cancel_progress_flush_task()
            if task_registry:
                await task_registry.remove(user_id, scope_key=scope_key)
            # Preserve thinking process with cancelled label
            if all_progress_lines:
                summary_text = "[Cancelled] " + _generate_thinking_summary(
                    all_progress_lines
                )
                thinking_keyboard = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "View thinking process",
                                callback_data=f"thinking:expand:{progress_msg.message_id}",
                            )
                        ]
                    ]
                )
                try:
                    await progress_msg.edit_text(
                        summary_text,
                        parse_mode="Markdown",
                        reply_markup=thinking_keyboard,
                    )
                    _cache_thinking_data(
                        context,
                        progress_msg.message_id,
                        all_progress_lines,
                        summary_text,
                    )
                except Exception:
                    pass
            else:
                try:
                    await progress_msg.edit_text("Task cancelled.", reply_markup=None)
                except Exception:
                    pass
            # Clean up frozen messages
            for frozen_msg in frozen_messages:
                try:
                    await frozen_msg.delete()
                except Exception:
                    pass
            return
        except ClaudeToolValidationError as e:
            # Tool validation error with detailed instructions
            logger.error(
                "Tool validation error",
                error=str(e),
                user_id=user_id,
                blocked_tools=e.blocked_tools,
            )
            # Error message already formatted, create FormattedMessage
            from ..utils.formatting import FormattedMessage

            formatted_messages = [FormattedMessage(str(e), parse_mode="Markdown")]
        except Exception as e:
            logger.error(
                "CLI integration failed",
                error=str(e),
                user_id=user_id,
                engine=active_engine,
            )
            if task_registry:
                await task_registry.fail(user_id, scope_key=scope_key)
            # Format error and create FormattedMessage
            from ..utils.formatting import FormattedMessage

            formatted_messages = [
                FormattedMessage(
                    _format_error_message(str(e), engine=active_engine),
                    parse_mode="Markdown",
                )
            ]

        # Clean up task registry
        if task_registry:
            await task_registry.remove(user_id, scope_key=scope_key)
        await _cancel_progress_flush_task()

        # Build context tag for display in thinking summary or reply header
        rate_limit_summary: Optional[str] = None
        session_context_summary: Optional[str] = None
        session_id = claude_response.session_id if claude_response else None
        codex_snapshot = None
        if active_engine == ENGINE_CODEX and session_id:
            codex_snapshot = SessionService.get_cached_codex_snapshot(session_id)
            if codex_snapshot is None:
                codex_snapshot = SessionService._probe_codex_session_snapshot(
                    session_id
                )
        if codex_snapshot:
            session_context_summary = _build_session_context_summary(codex_snapshot)
            rate_limit_summary = format_rate_limit_summary(
                codex_snapshot.get("rate_limits")
            )
        context_tag = _build_context_tag(
            scope_state=scope_state,
            approved_directory=settings.approved_directory,
            active_engine=active_engine,
            session_id=scope_state.get("claude_session_id"),
            session_context_summary=session_context_summary,
            rate_limit_summary=rate_limit_summary,
        )
        has_thinking_summary = False

        # Collapse progress message into summary with expand button
        if all_progress_lines:
            summary_text = (
                context_tag + "\n\n" + _generate_thinking_summary(all_progress_lines)
            )
            has_thinking_summary = True
            thinking_keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "View thinking process",
                            callback_data=f"thinking:expand:{progress_msg.message_id}",
                        )
                    ]
                ]
            )
            try:
                await progress_msg.edit_text(
                    summary_text,
                    parse_mode="Markdown",
                    reply_markup=thinking_keyboard,
                )
                _cache_thinking_data(
                    context, progress_msg.message_id, all_progress_lines, summary_text
                )
            except Exception as e:
                logger.warning("Failed to edit progress to summary", error=str(e))
                try:
                    await progress_msg.delete()
                except Exception:
                    pass
        else:
            try:
                await progress_msg.delete()
            except Exception:
                pass

        # Delete frozen progress messages (from overflow)
        for frozen_msg in frozen_messages:
            try:
                await frozen_msg.delete()
            except Exception:
                pass

        # Send formatted responses (may be multiple messages)
        for i, message in enumerate(formatted_messages):
            try:
                msg_text = message.text
                reply_to_id = update.message.message_id if i == 0 else None
                # Prepend context tag to the first message when no thinking summary
                if i == 0 and not has_thinking_summary and context_tag:
                    context_prefix = context_tag + "\n\n"
                    if len(context_prefix) + len(msg_text) <= _TELEGRAM_MESSAGE_LIMIT:
                        msg_text = context_prefix + msg_text
                    else:
                        await _reply_text_resilient(
                            update.message,
                            context_tag,
                            parse_mode="Markdown",
                            reply_to_message_id=reply_to_id,
                        )
                        reply_to_id = None

                await _reply_text_resilient(
                    update.message,
                    msg_text,
                    parse_mode=message.parse_mode,
                    reply_markup=message.reply_markup,
                    reply_to_message_id=reply_to_id,
                )

                # Small delay between messages to avoid rate limits
                if i < len(formatted_messages) - 1:
                    await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(
                    "Failed to send response message", error=str(e), message_index=i
                )
                # Try to send error message
                await update.message.reply_text(
                    _with_engine_badge(
                        f"❌ {_engine_label(active_engine)} 响应发送失败，请重试。",
                        active_engine,
                    ),
                    reply_to_message_id=update.message.message_id if i == 0 else None,
                )

        # Update session info
        scope_state["last_message"] = update.message.text

        # Add conversation enhancements if available
        features = context.bot_data.get("features")
        conversation_enhancer = (
            features.get_conversation_enhancer() if features else None
        )

        if conversation_enhancer and claude_response:
            try:
                # Update conversation context
                conversation_enhancer.update_context(
                    user_id=user_id,
                    response=claude_response,
                )
                # 关闭自动会话建议按钮，避免额外 UI 干扰。
                # 保留上下文更新，后续如需恢复可在此处重新启用发送逻辑。

            except Exception as e:
                logger.warning(
                    "Conversation enhancement failed", error=str(e), user_id=user_id
                )

        # Log successful message processing
        if audit_logger:
            await audit_logger.log_command(
                user_id=user_id,
                command="text_message",
                args=[update.message.text[:100]],  # First 100 chars
                success=True,
            )

        logger.info("Text message processed successfully", user_id=user_id)

    except Exception as e:
        # Clean up progress message: collapse to summary if possible
        try:
            if all_progress_lines:
                summary_text = "[Error] " + _generate_thinking_summary(
                    all_progress_lines
                )
                thinking_keyboard = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "View thinking process",
                                callback_data=f"thinking:expand:{progress_msg.message_id}",
                            )
                        ]
                    ]
                )
                await progress_msg.edit_text(
                    summary_text,
                    parse_mode="Markdown",
                    reply_markup=thinking_keyboard,
                )
                _cache_thinking_data(
                    context, progress_msg.message_id, all_progress_lines, summary_text
                )
            else:
                await progress_msg.delete()
        except:
            pass

        # Clean up frozen messages
        for frozen_msg in frozen_messages:
            try:
                await frozen_msg.delete()
            except:
                pass

        error_msg = _format_error_message(
            str(e),
            engine=locals().get("active_engine", ENGINE_CLAUDE),
        )
        await update.message.reply_text(
            _with_engine_badge(error_msg, locals().get("active_engine", ENGINE_CLAUDE)),
            parse_mode="Markdown",
        )

        # Log failed processing
        if audit_logger:
            await audit_logger.log_command(
                user_id=user_id,
                command="text_message",
                args=[update.message.text[:100]],
                success=False,
            )

        logger.error("Error processing text message", error=str(e), user_id=user_id)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle file uploads."""
    user_id = update.effective_user.id
    document = update.message.document
    settings: Settings = context.bot_data["settings"]
    _, scope_state = get_scope_state_from_update(
        user_data=context.user_data,
        update=update,
        default_directory=settings.approved_directory,
    )
    active_engine, cli_integration = get_cli_integration(
        bot_data=context.bot_data,
        scope_state=scope_state,
    )

    # Get services
    security_validator: Optional[SecurityValidator] = context.bot_data.get(
        "security_validator"
    )
    audit_logger: Optional[AuditLogger] = context.bot_data.get("audit_logger")
    rate_limiter: Optional[RateLimiter] = context.bot_data.get("rate_limiter")

    logger.info(
        "Processing document upload",
        user_id=user_id,
        filename=document.file_name,
        file_size=document.file_size,
    )

    try:
        # Validate filename using security validator
        if security_validator:
            valid, error = security_validator.validate_filename(document.file_name)
            if not valid:
                await update.message.reply_text(
                    f"❌ **File Upload Rejected**\n\n{error}"
                )

                # Log security violation
                if audit_logger:
                    await audit_logger.log_security_violation(
                        user_id=user_id,
                        violation_type="invalid_file_upload",
                        details=f"Filename: {document.file_name}, Error: {error}",
                        severity="medium",
                    )
                return

        # Check file size limits
        max_size = 10 * 1024 * 1024  # 10MB
        if document.file_size > max_size:
            await update.message.reply_text(
                f"❌ **File Too Large**\n\n"
                f"Maximum file size: {max_size // 1024 // 1024}MB\n"
                f"Your file: {document.file_size / 1024 / 1024:.1f}MB"
            )
            return

        # Check rate limit for file processing
        file_cost = _estimate_file_processing_cost(document.file_size)
        if rate_limiter:
            allowed, limit_message = await rate_limiter.check_rate_limit(
                user_id, file_cost
            )
            if not allowed:
                await update.message.reply_text(f"⏱️ {limit_message}")
                return

        # Send processing indicator
        await update.message.chat.send_action("upload_document")

        progress_msg = await update.message.reply_text(
            _with_engine_badge(
                f"📄 Processing file: `{document.file_name}`...",
                active_engine,
            ),
            parse_mode="Markdown",
        )

        # Check if enhanced file handler is available
        features = context.bot_data.get("features")
        file_handler = features.get_file_handler() if features else None

        if file_handler:
            # Use enhanced file handler
            try:
                processed_file = await file_handler.handle_document_upload(
                    document,
                    user_id,
                    update.message.caption or "Please review this file:",
                )
                prompt = processed_file.prompt

                # Update progress message with file type info
                await progress_msg.edit_text(
                    _with_engine_badge(
                        f"📄 Processing {processed_file.type} file: `{document.file_name}`...",
                        active_engine,
                    ),
                    parse_mode="Markdown",
                )

            except Exception as e:
                logger.warning(
                    "Enhanced file handler failed, falling back to basic handler",
                    error=str(e),
                )
                file_handler = None  # Fall back to basic handling

        if not file_handler:
            # Fall back to basic file handling
            file = await document.get_file()
            file_bytes = await file.download_as_bytearray()

            # Try to decode as text
            try:
                content = file_bytes.decode("utf-8")

                # Check content length
                max_content_length = 50000  # 50KB of text
                if len(content) > max_content_length:
                    content = (
                        content[:max_content_length]
                        + "\n... (file truncated for processing)"
                    )

                # Create prompt with file content
                caption = update.message.caption or "Please review this file:"
                prompt = f"{caption}\n\n**File:** `{document.file_name}`\n\n```\n{content}\n```"

            except UnicodeDecodeError:
                await progress_msg.edit_text(
                    _with_engine_badge(
                        "❌ **File Format Not Supported**\n\n"
                        "File must be text-based and UTF-8 encoded.\n\n"
                        "**Supported formats:**\n"
                        "• Source code files (.py, .js, .ts, etc.)\n"
                        "• Text files (.txt, .md)\n"
                        "• Configuration files (.json, .yaml, .toml)\n"
                        "• Documentation files",
                        active_engine,
                    )
                )
                return

        # Delete progress message
        await progress_msg.delete()

        # Create a new progress message for CLI processing
        claude_progress_msg = await update.message.reply_text(
            _with_engine_badge("🤖 正在处理文件...", active_engine),
            parse_mode="Markdown",
        )

        if not cli_integration:
            await claude_progress_msg.edit_text(
                _with_engine_badge(
                    "❌ **CLI 引擎不可用**\n\n" "当前 CLI 引擎未正确配置。",
                    active_engine,
                ),
                parse_mode="Markdown",
            )
            return

        # Get current directory and session
        current_dir = scope_state.get("current_directory", settings.approved_directory)
        session_id = scope_state.get("claude_session_id")
        force_new_session = scope_state.get("force_new_session", False)
        permission_handler = build_permission_handler(
            bot=context.bot, chat_id=update.effective_chat.id, settings=settings
        )

        # Process with Claude
        try:
            claude_response = await cli_integration.run_command(
                prompt=prompt,
                working_directory=current_dir,
                user_id=user_id,
                session_id=session_id,
                force_new_session=force_new_session,
                permission_handler=permission_handler,
                model=scope_state.get("claude_model"),
            )

            # Update session ID
            scope_state["claude_session_id"] = claude_response.session_id
            scope_state.pop("force_new_session", None)

            # Check if Claude changed the working directory and update our tracking
            _update_working_directory_from_claude_response(
                claude_response, scope_state, settings, user_id
            )

            # Format and send response
            from ..utils.formatting import ResponseFormatter

            formatter = ResponseFormatter(settings)
            formatted_messages = formatter.format_claude_response(
                claude_response.content
            )

            # Delete progress message
            await claude_progress_msg.delete()

            # Build context tag for CLI mode reply header
            cli_context_tag = _build_context_tag(
                scope_state=scope_state,
                approved_directory=settings.approved_directory,
                active_engine=active_engine,
                session_id=scope_state.get("claude_session_id"),
            )

            # Send responses
            for i, message in enumerate(formatted_messages):
                msg_text = message.text
                reply_to_id = update.message.message_id if i == 0 else None
                if i == 0 and cli_context_tag:
                    context_prefix = cli_context_tag + "\n\n"
                    if len(context_prefix) + len(msg_text) <= _TELEGRAM_MESSAGE_LIMIT:
                        msg_text = context_prefix + msg_text
                    else:
                        await _reply_text_resilient(
                            update.message,
                            cli_context_tag,
                            parse_mode="Markdown",
                            reply_to_message_id=reply_to_id,
                        )
                        reply_to_id = None

                await _reply_text_resilient(
                    update.message,
                    msg_text,
                    parse_mode=message.parse_mode,
                    reply_markup=message.reply_markup,
                    reply_to_message_id=reply_to_id,
                )

                if i < len(formatted_messages) - 1:
                    await asyncio.sleep(0.5)

        except Exception as e:
            await claude_progress_msg.edit_text(
                _with_engine_badge(
                    _format_error_message(str(e), engine=active_engine),
                    active_engine,
                ),
                parse_mode="Markdown",
            )
            logger.error(
                "CLI file processing failed",
                error=str(e),
                user_id=user_id,
                engine=active_engine,
            )

        # Log successful file processing
        if audit_logger:
            await audit_logger.log_file_access(
                user_id=user_id,
                file_path=document.file_name,
                action="upload_processed",
                success=True,
                file_size=document.file_size,
            )

    except Exception as e:
        try:
            await progress_msg.delete()
        except:
            pass

        error_msg = _with_engine_badge(
            _format_error_message(str(e), engine=active_engine),
            active_engine,
        )
        await update.message.reply_text(error_msg, parse_mode="Markdown")

        # Log failed file processing
        if audit_logger:
            await audit_logger.log_file_access(
                user_id=user_id,
                file_path=document.file_name,
                action="upload_failed",
                success=False,
                file_size=document.file_size,
            )

        logger.error("Error processing document", error=str(e), user_id=user_id)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle photo uploads."""
    user_id = update.effective_user.id
    settings: Settings = context.bot_data["settings"]
    scope_key, scope_state = get_scope_state_from_update(
        user_data=context.user_data,
        update=update,
        default_directory=settings.approved_directory,
    )

    # Check if enhanced image handler is available
    features = context.bot_data.get("features")
    image_handler = features.get_image_handler() if features else None

    if image_handler:
        task_registry: Optional[TaskRegistry] = context.bot_data.get("task_registry")
        if task_registry and await task_registry.is_busy(user_id, scope_key=scope_key):
            await update.message.reply_text(
                "A task is already running. Use /cancel to cancel it."
            )
            return

        try:
            last_status_text = ""
            thinking_lines: list[str] = []
            cancel_keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("Cancel", callback_data="cancel:task")]]
            )
            active_engine, cli_integration = get_cli_integration(
                bot_data=context.bot_data,
                scope_state=scope_state,
            )

            async def _set_image_status(text: str) -> None:
                nonlocal progress_msg, last_status_text
                bubble_text = _with_engine_badge(text, active_engine)

                if bubble_text == last_status_text:
                    return

                last_status_text = bubble_text
                try:
                    await progress_msg.edit_text(
                        bubble_text,
                        parse_mode="Markdown",
                        reply_markup=cancel_keyboard,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to update image status message",
                        error=str(e),
                        user_id=user_id,
                    )
                    try:
                        progress_msg = await update.message.reply_text(
                            bubble_text,
                            parse_mode="Markdown",
                            reply_to_message_id=update.message.message_id,
                            reply_markup=cancel_keyboard,
                        )
                    except Exception as send_error:
                        logger.warning(
                            "Failed to send fallback image status message",
                            error=str(send_error),
                            user_id=user_id,
                        )

            async def _image_stream_handler(update_obj) -> None:
                try:
                    progress_text = await _format_progress_update(update_obj)
                    if not progress_text:
                        return

                    # Keep behavior aligned with text flow:
                    # assistant plain content is not part of thinking details.
                    if not (
                        update_obj.type == "assistant"
                        and update_obj.content
                        and not update_obj.tool_calls
                    ):
                        thinking_lines.append(progress_text)
                except Exception as e:
                    logger.warning(
                        "Failed to collect image stream progress",
                        error=str(e),
                        user_id=user_id,
                    )

            # Send processing indicator (single message that will be updated)
            initial_status = _with_engine_badge(
                _build_image_stage_status(1, "已接收图片"),
                active_engine,
            )
            progress_msg = await update.message.reply_text(
                initial_status,
                parse_mode="Markdown",
                reply_to_message_id=update.message.message_id,
                reply_markup=cancel_keyboard,
            )
            last_status_text = initial_status

            if not cli_integration:
                await _set_image_status(
                    "❌ **CLI 引擎不可用**\n\n"
                    "当前 CLI 引擎未正确配置，请检查服务配置。"
                )
                return

            if not _integration_supports_image_analysis(cli_integration):
                integrations = context.bot_data.get("cli_integrations") or {}
                claude_integration = integrations.get(ENGINE_CLAUDE)
                if (
                    active_engine != ENGINE_CLAUDE
                    and _integration_supports_image_analysis(claude_integration)
                ):
                    await _set_image_status(
                        "📸 **当前引擎不支持图片分析**\n\n"
                        f"当前引擎：`{active_engine}`\n"
                        "图片分析仅在 `claude` 引擎（SDK 模式）可用。\n\n"
                        "**处理方式：**先执行 `/engine claude`，再重新上传图片。"
                    )
                    return

                await _set_image_status(
                    "📸 **图片分析需要 SDK 模式**\n\n"
                    "当前运行模式不支持图片多模态输入。\n\n"
                    "**处理方式：**将 `.env` 中 `USE_SDK` 设为 `true` 并重启机器人。"
                )
                return

            # Get the largest photo size
            photo = update.message.photo[-1]

            async def _image_progress(stage: str) -> None:
                if stage == "downloading":
                    await _set_image_status(
                        _build_image_stage_status(2, "正在从 Telegram 下载图片...")
                    )
                elif stage == "validating":
                    await _set_image_status(
                        _build_image_stage_status(3, "正在校验图片格式与大小...")
                    )
                elif stage == "encoding":
                    await _set_image_status(
                        _build_image_stage_status(3, "正在编码图片数据...")
                    )

            # Process image with enhanced handler
            processed_image = await image_handler.process_image(
                photo,
                update.message.caption,
                on_progress=_image_progress,
            )

            # Get current directory and session
            current_dir = Path(
                scope_state.get("current_directory", settings.approved_directory)
            )
            session_id = scope_state.get("claude_session_id")
            force_new_session = scope_state.get("force_new_session", False)
            permission_handler = build_permission_handler(
                bot=context.bot, chat_id=update.effective_chat.id, settings=settings
            )

            # Process with Claude
            cli_image_file: Optional[Path] = None
            try:
                # Build image data for multimodal input
                img_format = processed_image.metadata.get("format", "jpeg")
                if img_format == "unknown":
                    img_format = "jpeg"  # Default to JPEG for unknown formats
                images = [
                    {
                        "base64_data": processed_image.base64_data,
                        "media_type": f"image/{img_format}",
                    }
                ]
                if _integration_uses_cli_image_files(cli_integration):
                    cli_image_file = _persist_cli_image_file(
                        base64_data=processed_image.base64_data,
                        image_format=img_format,
                        working_directory=current_dir,
                    )
                    images[0]["file_path"] = str(cli_image_file)
                engine_label = "Codex" if active_engine == "codex" else "Claude"
                await _set_image_status(
                    _build_image_stage_status(
                        4,
                        f"正在提交图片给 {engine_label}...",
                    )
                )
                await _set_image_status(
                    _build_image_analyzing_status(0, engine_label=engine_label)
                )

                async def _run_image_claude():
                    return await _run_with_image_analysis_heartbeat(
                        run_coro=cli_integration.run_command(
                            prompt=processed_image.prompt,
                            working_directory=current_dir,
                            user_id=user_id,
                            session_id=session_id,
                            on_stream=_image_stream_handler,
                            force_new_session=force_new_session,
                            permission_handler=permission_handler,
                            model=scope_state.get("claude_model"),
                            images=images,
                        ),
                        update_status=_set_image_status,
                        engine_label=engine_label,
                    )

                image_task = asyncio.create_task(_run_image_claude())
                if task_registry:
                    await task_registry.register(
                        user_id,
                        image_task,
                        prompt_summary=processed_image.prompt,
                        progress_message_id=progress_msg.message_id,
                        chat_id=update.effective_chat.id,
                        scope_key=scope_key,
                    )

                try:
                    claude_response = await image_task
                    if task_registry:
                        await task_registry.complete(user_id, scope_key=scope_key)
                except asyncio.CancelledError:
                    logger.info("Image Claude task cancelled by user", user_id=user_id)
                    if thinking_lines:
                        summary_text = "[Cancelled] " + _generate_thinking_summary(
                            thinking_lines
                        )
                        thinking_keyboard = InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton(
                                        "View thinking process",
                                        callback_data=f"thinking:expand:{progress_msg.message_id}",
                                    )
                                ]
                            ]
                        )
                        try:
                            await progress_msg.edit_text(
                                summary_text,
                                parse_mode="Markdown",
                                reply_markup=thinking_keyboard,
                            )
                            _cache_thinking_data(
                                context,
                                progress_msg.message_id,
                                thinking_lines,
                                summary_text,
                            )
                        except Exception:
                            pass
                    else:
                        try:
                            await progress_msg.edit_text(
                                "Task cancelled.", reply_markup=None
                            )
                        except Exception:
                            pass
                    return
                except Exception:
                    if task_registry:
                        await task_registry.fail(user_id, scope_key=scope_key)
                    raise
                finally:
                    if task_registry:
                        await task_registry.remove(user_id, scope_key=scope_key)

                # Update session ID
                scope_state["claude_session_id"] = claude_response.session_id
                scope_state.pop("force_new_session", None)

                # Format and send response
                from ..utils.formatting import ResponseFormatter

                await _set_image_status(
                    _build_image_stage_status(6, "正在整理回复内容...")
                )
                formatter = ResponseFormatter(settings)
                formatted_messages = formatter.format_claude_response(
                    claude_response.content
                )

                # Build context tag for image response
                img_context_tag = _build_context_tag(
                    scope_state=scope_state,
                    approved_directory=settings.approved_directory,
                    active_engine=active_engine,
                    session_id=scope_state.get("claude_session_id"),
                )
                img_has_thinking = False

                # Collapse progress message into thinking summary when available
                if thinking_lines:
                    summary_text = (
                        img_context_tag
                        + "\n"
                        + _generate_thinking_summary(thinking_lines)
                    )
                    img_has_thinking = True
                    thinking_keyboard = InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "View thinking process",
                                    callback_data=f"thinking:expand:{progress_msg.message_id}",
                                )
                            ]
                        ]
                    )
                    try:
                        await progress_msg.edit_text(
                            summary_text,
                            parse_mode="Markdown",
                            reply_markup=thinking_keyboard,
                        )
                        _cache_thinking_data(
                            context,
                            progress_msg.message_id,
                            thinking_lines,
                            summary_text,
                        )
                    except Exception as e:
                        logger.warning(
                            "Failed to collapse image progress to summary",
                            error=str(e),
                            user_id=user_id,
                        )
                        try:
                            await progress_msg.delete()
                        except Exception:
                            pass
                else:
                    try:
                        await progress_msg.delete()
                    except Exception:
                        pass

                # Send responses
                for i, message in enumerate(formatted_messages):
                    msg_text = message.text
                    reply_to_id = update.message.message_id if i == 0 else None
                    if i == 0 and not img_has_thinking and img_context_tag:
                        context_prefix = img_context_tag + "\n\n"
                        if (
                            len(context_prefix) + len(msg_text)
                            <= _TELEGRAM_MESSAGE_LIMIT
                        ):
                            msg_text = context_prefix + msg_text
                        else:
                            await _reply_text_resilient(
                                update.message,
                                img_context_tag,
                                parse_mode="Markdown",
                                reply_to_message_id=reply_to_id,
                            )
                            reply_to_id = None

                    await _reply_text_resilient(
                        update.message,
                        msg_text,
                        parse_mode=message.parse_mode,
                        reply_markup=message.reply_markup,
                        reply_to_message_id=reply_to_id,
                    )

                    if i < len(formatted_messages) - 1:
                        await asyncio.sleep(0.5)

            except Exception as e:
                error_text = _format_error_message(str(e), engine=active_engine)
                error_bubble = _with_engine_badge(error_text, active_engine)
                try:
                    if thinking_lines:
                        summary_text = "[Error] " + _generate_thinking_summary(
                            thinking_lines
                        )
                        thinking_keyboard = InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton(
                                        "View thinking process",
                                        callback_data=f"thinking:expand:{progress_msg.message_id}",
                                    )
                                ]
                            ]
                        )
                        await progress_msg.edit_text(
                            summary_text,
                            parse_mode="Markdown",
                            reply_markup=thinking_keyboard,
                        )
                        _cache_thinking_data(
                            context,
                            progress_msg.message_id,
                            thinking_lines,
                            summary_text,
                        )
                        await update.message.reply_text(
                            error_bubble,
                            parse_mode="Markdown",
                            reply_to_message_id=update.message.message_id,
                        )
                    else:
                        await progress_msg.edit_text(
                            error_bubble,
                            parse_mode="Markdown",
                            reply_markup=None,
                        )
                except Exception as send_error:
                    logger.warning(
                        "Failed to edit image progress message with error",
                        error=str(send_error),
                        original_error=str(e),
                        user_id=user_id,
                    )
                    await update.message.reply_text(
                        error_bubble,
                        parse_mode="Markdown",
                        reply_to_message_id=update.message.message_id,
                    )
                logger.error(
                    "CLI image processing failed",
                    error=str(e),
                    user_id=user_id,
                    engine=active_engine,
                )
            finally:
                _cleanup_cli_image_file(cli_image_file)

        except Exception as e:
            logger.error("Image processing failed", error=str(e), user_id=user_id)
            await update.message.reply_text(
                _with_engine_badge(
                    _format_error_message(
                        str(e),
                        engine=locals().get("active_engine", ENGINE_CLAUDE),
                    ),
                    locals().get("active_engine", ENGINE_CLAUDE),
                ),
                parse_mode="Markdown",
            )
    else:
        # Fall back to unsupported message
        await update.message.reply_text(
            "📸 **Photo Upload**\n\n"
            "Photo processing is not yet supported.\n\n"
            "**Currently supported:**\n"
            "• Text files (.py, .js, .md, etc.)\n"
            "• Configuration files\n"
            "• Documentation files\n\n"
            "**Coming soon:**\n"
            "• Image analysis\n"
            "• Screenshot processing\n"
            "• Diagram interpretation"
        )


def _estimate_text_processing_cost(text: str) -> float:
    """Estimate cost for processing text message."""
    # Base cost
    base_cost = 0.001

    # Additional cost based on length
    length_cost = len(text) * 0.00001

    # Additional cost for complex requests
    complex_keywords = [
        "analyze",
        "generate",
        "create",
        "build",
        "implement",
        "refactor",
        "optimize",
        "debug",
        "explain",
        "document",
    ]

    text_lower = text.lower()
    complexity_multiplier = 1.0

    for keyword in complex_keywords:
        if keyword in text_lower:
            complexity_multiplier += 0.5

    return (base_cost + length_cost) * min(complexity_multiplier, 3.0)


def _estimate_file_processing_cost(file_size: int) -> float:
    """Estimate cost for processing uploaded file."""
    # Base cost for file handling
    base_cost = 0.005

    # Additional cost based on file size (per KB)
    size_cost = (file_size / 1024) * 0.0001

    return base_cost + size_cost


async def _generate_placeholder_response(
    message_text: str, context: ContextTypes.DEFAULT_TYPE
) -> dict:
    """Generate placeholder response until Claude integration is implemented."""
    settings: Settings = context.bot_data["settings"]
    current_dir = getattr(
        context.user_data, "current_directory", settings.approved_directory
    )
    relative_path = current_dir.relative_to(settings.approved_directory)

    # Analyze the message for intent
    message_lower = message_text.lower()

    if any(
        word in message_lower for word in ["list", "show", "see", "directory", "files"]
    ):
        response_text = (
            f"🤖 **Claude Code Response** _(Placeholder)_\n\n"
            f"I understand you want to see files. Try using the `/ls` command to list files "
            f"in your current directory (`{relative_path}/`).\n\n"
            f"**Available commands:**\n"
            f"• `/ls` - List files\n"
            f"• `/cd <dir>` - Change directory\n"
            f"• `/projects` - Show projects\n\n"
            f"_Note: Full Claude Code integration will be available in the next phase._"
        )

    elif any(word in message_lower for word in ["create", "generate", "make", "build"]):
        response_text = (
            f"🤖 **Claude Code Response** _(Placeholder)_\n\n"
            f"I understand you want to create something! Once the Claude Code integration "
            f"is complete, I'll be able to:\n\n"
            f"• Generate code files\n"
            f"• Create project structures\n"
            f"• Write documentation\n"
            f"• Build complete applications\n\n"
            f"**Current directory:** `{relative_path}/`\n\n"
            f"_Full functionality coming soon!_"
        )

    elif any(word in message_lower for word in ["help", "how", "what", "explain"]):
        response_text = (
            f"🤖 **Claude Code Response** _(Placeholder)_\n\n"
            f"I'm here to help! Try using `/help` for available commands.\n\n"
            f"**What I can do now:**\n"
            f"• Navigate directories (`/cd`, `/ls`, `/pwd`)\n"
            f"• Show projects (`/projects`)\n"
            f"• Manage sessions (`/new`, `/context`)\n\n"
            f"**Coming soon:**\n"
            f"• Full Claude Code integration\n"
            f"• Code generation and editing\n"
            f"• File operations\n"
            f"• Advanced programming assistance"
        )

    else:
        response_text = (
            f"🤖 **Claude Code Response** _(Placeholder)_\n\n"
            f"I received your message: \"{message_text[:100]}{'...' if len(message_text) > 100 else ''}\"\n\n"
            f"**Current Status:**\n"
            f"• Directory: `{relative_path}/`\n"
            f"• Bot core: ✅ Active\n"
            f"• Claude integration: 🔄 Coming soon\n\n"
            f"Once Claude Code integration is complete, I'll be able to process your "
            f"requests fully and help with coding tasks!\n\n"
            f"For now, try the available commands like `/ls`, `/cd`, and `/help`."
        )

    return {"text": response_text, "parse_mode": "Markdown"}


def _update_working_directory_from_claude_response(
    claude_response,
    scope_state: dict[str, Any],
    settings,
    user_id,
):
    """Update the working directory based on Claude's response content."""
    import re
    from pathlib import Path

    # Look for directory changes in Claude's response
    # This searches for common patterns that indicate directory changes
    patterns = [
        r"(?:^|\n).*?cd\s+([^\s\n]+)",  # cd command
        r"(?:^|\n).*?Changed directory to:?\s*([^\s\n]+)",  # explicit directory change
        r"(?:^|\n).*?Current directory:?\s*([^\s\n]+)",  # current directory indication
        r"(?:^|\n).*?Working directory:?\s*([^\s\n]+)",  # working directory indication
    ]

    content = claude_response.content.lower()
    current_dir = scope_state.get("current_directory", settings.approved_directory)

    for pattern in patterns:
        matches = re.findall(pattern, content, re.MULTILINE | re.IGNORECASE)
        for match in matches:
            try:
                # Clean up the path
                new_path = match.strip().strip("\"'`")

                # Handle relative paths
                if new_path.startswith("./") or new_path.startswith("../"):
                    new_path = (current_dir / new_path).resolve()
                elif not new_path.startswith("/"):
                    # Relative path without ./
                    new_path = (current_dir / new_path).resolve()
                else:
                    # Absolute path
                    new_path = Path(new_path).resolve()

                # Validate that the new path is within the approved directory
                if (
                    new_path.is_relative_to(settings.approved_directory)
                    and new_path.exists()
                ):
                    scope_state["current_directory"] = new_path
                    logger.info(
                        "Updated working directory from Claude response",
                        old_dir=str(current_dir),
                        new_dir=str(new_path),
                        user_id=user_id,
                    )
                    return  # Take the first valid match

            except (ValueError, OSError) as e:
                # Invalid path, skip this match
                logger.debug(
                    "Invalid path in Claude response", path=match, error=str(e)
                )
                continue


def _format_tool_input_summary(tool_name: str, tool_input: dict) -> str:
    """Format a short summary of tool input for the permission prompt."""
    if not tool_input:
        return ""

    def _safe_code(value: Any, max_len: int) -> str:
        text = str(value).replace("`", "'")
        if len(text) > max_len:
            return text[:max_len] + "..."
        return text

    parts = []
    if tool_name in ("Write", "Edit", "Read") and "file_path" in tool_input:
        parts.append(f"File: `{_safe_code(tool_input['file_path'], 140)}`")
    elif tool_name == "Bash" and "command" in tool_input:
        parts.append(f"Command: `{_safe_code(tool_input['command'], 160)}`")
    elif tool_name == "WebFetch" and "url" in tool_input:
        parts.append(f"URL: `{_safe_code(tool_input['url'], 180)}`")
    else:
        # Generic: show first key-value pair
        for key, value in list(tool_input.items())[:2]:
            parts.append(f"{key}: `{_safe_code(value, 100)}`")

    return "\n".join(parts)


def build_permission_handler(
    bot: Any,
    chat_id: int,
    settings: Any,
) -> Optional[Callable]:
    """Build a permission button sender callback for SDK tool permission requests.

    Returns None if SDK is not active. The returned callback can be passed as
    ``permission_handler`` to ``ClaudeIntegration.run_command``.
    """
    if not settings.use_sdk:
        return None

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    async def send_permission_buttons(
        request_id: str,
        tool_name: str,
        tool_input: dict,
        sess_id: str,
    ) -> None:
        input_summary = _format_tool_input_summary(tool_name, tool_input)
        tool_label = str(tool_name or "unknown").replace("`", "'")
        session_label = str(sess_id or "").replace("`", "'")
        short_session = f"{session_label[:8]}..." if session_label else "n/a"

        keyboard = [
            [
                InlineKeyboardButton(
                    "Allow",
                    callback_data=f"permission:allow:{request_id}",
                ),
                InlineKeyboardButton(
                    "Allow All",
                    callback_data=f"permission:allow_all:{request_id}",
                ),
                InlineKeyboardButton(
                    "Deny",
                    callback_data=f"permission:deny:{request_id}",
                ),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"**Tool Permission Request**\n\n"
                f"CLI wants to use: `{tool_label}`\n"
                f"Request: `{request_id}`\n"
                f"Session: `{short_session}`\n"
                f"{input_summary}\n\n"
                f"Allow this action?"
            ),
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )

    return send_permission_buttons
