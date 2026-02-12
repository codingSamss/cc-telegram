"""Command handlers for bot operations."""

import asyncio
import re
import sys
from pathlib import Path

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ...claude.facade import ClaudeIntegration
from ...claude.task_registry import TaskRegistry
from ...config.settings import Settings
from ...security.audit import AuditLogger
from ...security.validators import SecurityValidator
from ..utils.resume_ui import build_resume_project_selector
from ..utils.status_usage import (
    build_model_usage_status_lines,
    build_precise_context_status_lines,
)
from .message import build_permission_handler

logger = structlog.get_logger()


def _is_context_full_mode(context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Whether `/context` should render full detail output."""
    args = getattr(context, "args", None) or []
    normalized = [str(arg).strip().lower() for arg in args if str(arg).strip()]
    if not normalized:
        return False

    return normalized[0] in {"full", "all", "verbose", "detail"}


def _split_status_text(text: str, max_length: int = 3900) -> list[str]:
    """Split long status text into Telegram-safe chunks."""
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_length:
        split_at = remaining.rfind("\n", 0, max_length)
        if split_at <= 0:
            split_at = max_length
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n")

    if remaining:
        chunks.append(remaining)
    return chunks


def _parse_token_count(value: str | None) -> int | None:
    """Parse token string such as `1.4k`, `33,600`, `2k`."""
    if not value:
        return None

    normalized = str(value).strip().lower().replace(",", "").replace("_", "")
    if not normalized:
        return None

    match = re.search(r"(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>[kmb])?", normalized)
    if not match:
        return None

    number = float(match.group("num"))
    if number < 0:
        return None

    unit = match.group("unit") or ""
    multiplier = 1
    if unit == "k":
        multiplier = 1_000
    elif unit == "m":
        multiplier = 1_000_000
    elif unit == "b":
        multiplier = 1_000_000_000

    return int(round(number * multiplier))


def _parse_percent_value(value: str | None) -> float | None:
    """Parse percent text like `17%` or `33.7 %`."""
    if not value:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", str(value))
    if not match:
        return None
    return float(match.group(1))


def _split_markdown_row(line: str) -> list[str]:
    """Split a markdown table row into cells."""
    raw = line.strip()
    if not raw.startswith("|") or not raw.endswith("|"):
        return []
    return [cell.strip() for cell in raw.strip("|").split("|")]


def _is_markdown_separator_row(cells: list[str]) -> bool:
    """Check whether cells are markdown table separator (--- style)."""
    if not cells:
        return False
    for cell in cells:
        marker = cell.replace("-", "").replace(":", "").replace(" ", "")
        if marker:
            return False
    return True


def _extract_context_table_sections(raw_text: str) -> dict[str, list[dict[str, str]]]:
    """Extract markdown table rows grouped by `###` section title."""
    sections: dict[str, list[dict[str, str]]] = {}
    lines = [line.rstrip() for line in str(raw_text or "").splitlines()]
    current_section = "General"
    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        if line.startswith("### "):
            current_section = line[4:].strip() or "General"
            idx += 1
            continue

        if idx + 1 < len(lines) and line.startswith("|"):
            headers = _split_markdown_row(line)
            separators = _split_markdown_row(lines[idx + 1].strip())
            if (
                headers
                and separators
                and len(headers) == len(separators)
                and _is_markdown_separator_row(separators)
            ):
                rows: list[dict[str, str]] = []
                idx += 2
                while idx < len(lines):
                    row_line = lines[idx].strip()
                    if not row_line.startswith("|"):
                        break
                    cells = _split_markdown_row(row_line)
                    if len(cells) != len(headers):
                        break
                    rows.append({headers[i]: cells[i] for i in range(len(headers))})
                    idx += 1

                if rows:
                    sections.setdefault(current_section, []).extend(rows)
                continue

        idx += 1

    return sections


def _find_section_rows(
    sections: dict[str, list[dict[str, str]]],
    expected_name: str,
) -> list[dict[str, str]]:
    """Find section rows by name, case-insensitive."""
    target = expected_name.strip().lower()
    for section_name, rows in sections.items():
        if section_name.strip().lower() == target:
            return rows
    return []


def _build_context_table_summary_lines(raw_text: str) -> list[str]:
    """Build concise summary lines from `/context` markdown tables."""
    sections = _extract_context_table_sections(raw_text)
    if not sections:
        return []

    lines: list[str] = []

    category_rows = _find_section_rows(sections, "Estimated usage by category")
    if category_rows:
        entries: list[dict[str, object]] = []
        for row in category_rows:
            entries.append(
                {
                    "name": (row.get("Category") or "unknown").strip(),
                    "tokens_raw": (row.get("Tokens") or "").strip(),
                    "tokens": _parse_token_count(row.get("Tokens")),
                    "percent_raw": (row.get("Percentage") or "").strip(),
                    "percent": _parse_percent_value(row.get("Percentage")),
                }
            )

        entries = sorted(
            entries,
            key=lambda item: int(item.get("tokens") or 0),
            reverse=True,
        )
        top_entries = entries[:8]
        lines.append("[Estimated Usage by Category]")
        for entry in top_entries:
            token_value = entry.get("tokens")
            token_display = (
                f"{int(token_value):,}"
                if isinstance(token_value, int)
                else entry["tokens_raw"] or "n/a"
            )
            percent_value = entry.get("percent")
            percent_display = (
                f"{float(percent_value):.1f}%"
                if isinstance(percent_value, float)
                else entry["percent_raw"] or "n/a"
            )
            lines.append(f"- {entry['name']}: {token_display} ({percent_display})")
        if len(entries) > len(top_entries):
            lines.append(f"... and {len(entries) - len(top_entries)} more categories")

    mcp_rows = _find_section_rows(sections, "MCP Tools")
    if mcp_rows:
        entries: list[dict[str, object]] = []
        server_totals: dict[str, dict[str, int]] = {}
        for row in mcp_rows:
            tool = (row.get("Tool") or "unknown").strip()
            server = (row.get("Server") or "unknown").strip()
            token_raw = (row.get("Tokens") or "").strip()
            token_value = _parse_token_count(token_raw)
            entries.append(
                {
                    "tool": tool,
                    "server": server,
                    "tokens_raw": token_raw,
                    "tokens": token_value,
                }
            )
            stats = server_totals.setdefault(server, {"tokens": 0, "count": 0})
            stats["count"] += 1
            if isinstance(token_value, int):
                stats["tokens"] += token_value

        entries = sorted(
            entries,
            key=lambda item: int(item.get("tokens") or 0),
            reverse=True,
        )
        top_tools = entries[:10]
        top_servers = sorted(
            server_totals.items(),
            key=lambda item: (item[1]["tokens"], item[1]["count"]),
            reverse=True,
        )[:6]

        if lines:
            lines.append("")
        lines.append("[MCP Tools Summary]")
        lines.append(f"tool_count: {len(entries)}")
        lines.append(f"server_count: {len(server_totals)}")
        lines.append("top_servers:")
        for server, stats in top_servers:
            lines.append(
                f"- {server}: {stats['tokens']:,} tokens / {stats['count']} tools"
            )
        lines.append("top_tools:")
        for item in top_tools:
            token_value = item.get("tokens")
            token_display = (
                f"{int(token_value):,}"
                if isinstance(token_value, int)
                else item["tokens_raw"] or "n/a"
            )
            lines.append(f"- {item['tool']} ({item['server']}): {token_display}")
        if len(entries) > len(top_tools):
            lines.append(f"... and {len(entries) - len(top_tools)} more tools")

    excluded_sections = {"Estimated usage by category", "MCP Tools"}
    extra_sections: list[tuple[str, int, int]] = []
    for section_name, rows in sections.items():
        if section_name in excluded_sections or not rows:
            continue
        if "Tokens" not in rows[0]:
            continue
        total_tokens = 0
        for row in rows:
            parsed = _parse_token_count(row.get("Tokens"))
            if isinstance(parsed, int):
                total_tokens += parsed
        extra_sections.append((section_name, len(rows), total_tokens))

    if extra_sections:
        extra_sections.sort(key=lambda item: item[2], reverse=True)
        if lines:
            lines.append("")
        lines.append("[Other Token Sections]")
        for section_name, row_count, total_tokens in extra_sections:
            lines.append(
                f"- {section_name}: {row_count} rows, approx {total_tokens:,} tokens"
            )

    return lines


def _build_status_full_payload(
    *,
    relative_path: Path,
    current_model: str | None,
    claude_session_id: str | None,
    precise_context: dict | None,
    info: dict | None,
    resumable_payload: dict | None,
) -> dict:
    """Build full status payload."""
    return {
        "mode": "full",
        "directory": f"{relative_path}/",
        "model": current_model or "default",
        "session": {
            "active": bool(claude_session_id),
            "id": claude_session_id,
            "id_short": f"{claude_session_id[:8]}..." if claude_session_id else None,
        },
        "context_payload": precise_context,
        "session_info": info,
        "resumable": resumable_payload,
    }


def _render_model_usage_lines(model_usage: dict | None) -> list[str]:
    """Render model usage breakdown for full status output."""
    if not isinstance(model_usage, dict) or not model_usage:
        return ["model_usage: none"]

    lines: list[str] = []
    for model_name, usage in model_usage.items():
        if not isinstance(usage, dict):
            lines.append(f"- {model_name}: {usage}")
            continue

        input_tokens = int(usage.get("inputTokens", 0) or 0)
        output_tokens = int(usage.get("outputTokens", 0) or 0)
        cache_read = int(usage.get("cacheReadInputTokens", 0) or 0)
        cache_create = int(usage.get("cacheCreationInputTokens", 0) or 0)
        total_tokens = input_tokens + output_tokens + cache_read + cache_create
        context_window = int(usage.get("contextWindow", 0) or 0)
        window_source = usage.get("contextWindowSource")

        lines.append(f"- {model_name}")
        lines.append(f"  resolved_model: {usage.get('resolvedModel') or 'n/a'}")
        lines.append(f"  input_tokens: {input_tokens:,}")
        lines.append(f"  output_tokens: {output_tokens:,}")
        lines.append(f"  cache_read_input_tokens: {cache_read:,}")
        lines.append(f"  cache_creation_input_tokens: {cache_create:,}")
        lines.append(f"  total_tokens: {total_tokens:,}")

        if context_window > 0:
            used_percent = total_tokens / context_window * 100
            remaining = max(context_window - total_tokens, 0)
            lines.append(f"  context_window: {context_window:,}")
            lines.append(f"  context_window_source: {window_source or 'unknown'}")
            lines.append(f"  usage_percent: {used_percent:.2f}%")
            lines.append(f"  remaining_tokens: {remaining:,}")
        else:
            lines.append("  context_window: n/a")
            lines.append(f"  context_window_source: {window_source or 'n/a'}")

        if "costUSD" in usage:
            lines.append(f"  cost_usd: {usage.get('costUSD')}")
        if "maxOutputTokens" in usage:
            lines.append(f"  max_output_tokens: {usage.get('maxOutputTokens')}")

    return lines


def _render_status_full_text(payload: dict) -> str:
    """Render readable full status plus raw payload JSON."""
    session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
    context_payload = (
        payload.get("context_payload")
        if isinstance(payload.get("context_payload"), dict)
        else None
    )
    session_info = (
        payload.get("session_info")
        if isinstance(payload.get("session_info"), dict)
        else None
    )

    lines = [
        "Session Status (full)",
        "",
        "[Summary]",
        f"directory: {payload.get('directory')}",
        f"model: {payload.get('model')}",
        f"session_active: {session.get('active')}",
        f"session_id: {session.get('id') or 'none'}",
        f"session_id_short: {session.get('id_short') or 'none'}",
    ]

    if context_payload:
        lines.extend(
            [
                "",
                "[Context Payload]",
                f"used_tokens: {int(context_payload.get('used_tokens', 0) or 0):,}",
                f"total_tokens: {int(context_payload.get('total_tokens', 0) or 0):,}",
                f"remaining_tokens: {int(context_payload.get('remaining_tokens', 0) or 0):,}",
                f"used_percent: {float(context_payload.get('used_percent', 0.0) or 0.0):.2f}%",
                f"cached: {bool(context_payload.get('cached', False))}",
                f"context_session_id: {context_payload.get('session_id') or 'n/a'}",
            ]
        )

        raw_text = str(context_payload.get("raw_text") or "")
        if raw_text:
            structured_lines = _build_context_table_summary_lines(raw_text)
            if structured_lines:
                lines.extend(["", "[/context Structured Summary]", *structured_lines])
            else:
                lines.extend(
                    [
                        "",
                        "[/context Structured Summary]",
                        "No markdown table summary detected in /context output.",
                    ]
                )
    else:
        lines.extend(["", "[Context Payload]", "context_payload: none"])

    if session_info:
        tools_used = session_info.get("tools_used")
        tools_count = len(tools_used) if isinstance(tools_used, list) else 0
        lines.extend(
            [
                "",
                "[Session Info]",
                f"project: {session_info.get('project')}",
                f"created: {session_info.get('created')}",
                f"last_used: {session_info.get('last_used')}",
                f"cost_usd: {session_info.get('cost')}",
                f"turns: {session_info.get('turns')}",
                f"messages: {session_info.get('messages')}",
                f"expired: {session_info.get('expired')}",
                f"tools_used_count: {tools_count}",
                "",
                "[Model Usage]",
            ]
        )
        lines.extend(_render_model_usage_lines(session_info.get("model_usage")))
    else:
        lines.extend(["", "[Session Info]", "session_info: none"])

    return "\n".join(lines)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    user = update.effective_user

    welcome_message = (
        f"👋 Welcome to Claude Code Telegram Bot, {user.first_name}!\n\n"
        f"🤖 I help you access Claude Code remotely through Telegram.\n\n"
        f"**Available Commands:**\n"
        f"• `/help` - Show detailed help\n"
        f"• `/new` - Start a new Claude session\n"
        f"• `/ls` - List files in current directory\n"
        f"• `/cd <dir>` - Change directory\n"
        f"• `/projects` - Show available projects\n"
        f"• `/context [full]` - Show session status\n"
        f"• `/actions` - Show quick actions\n"
        f"• `/git` - Git repository commands\n"
        f"• `/codexdiag` - Diagnose codex MCP status\n\n"
        f"**Quick Start:**\n"
        f"1. Use `/projects` to see available projects\n"
        f"2. Use `/cd <project>` to navigate to a project\n"
        f"3. Send any message to start coding with Claude!\n\n"
        f"🔒 Your access is secured and all actions are logged.\n"
        f"📊 Use `/context` to check your usage limits."
    )

    # Add quick action buttons
    keyboard = [
        [
            InlineKeyboardButton(
                "📁 Show Projects", callback_data="action:show_projects"
            ),
            InlineKeyboardButton("❓ Get Help", callback_data="action:help"),
        ],
        [
            InlineKeyboardButton("🆕 New Session", callback_data="action:new_session"),
            InlineKeyboardButton("📊 Check Context", callback_data="action:status"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        welcome_message, parse_mode="Markdown", reply_markup=reply_markup
    )

    # Log command
    audit_logger: AuditLogger = context.bot_data.get("audit_logger")
    if audit_logger:
        await audit_logger.log_command(
            user_id=user.id, command="start", args=[], success=True
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    help_text = (
        "🤖 **Claude Code Telegram Bot Help**\n\n"
        "**Navigation Commands:**\n"
        "• `/ls` - List files and directories\n"
        "• `/cd <directory>` - Change to directory\n"
        "• `/pwd` - Show current directory\n"
        "• `/projects` - Show available projects\n\n"
        "**Session Commands:**\n"
        "• `/new` - Clear context and start a fresh session\n"
        "• `/continue [message]` - Explicitly continue last session\n"
        "• `/end` - End current session and clear context\n"
        "• `/context [full]` - Show session and usage status\n"
        "• `/export` - Export session history\n"
        "• `/actions` - Show context-aware quick actions\n"
        "• `/git` - Git repository information\n\n"
        "**Diagnostics:**\n"
        "• `/codexdiag` - Diagnose latest codex MCP call in current directory\n"
        "• `/codexdiag root` - Diagnose codex MCP call under approved root\n"
        "• `/codexdiag <session_id>` - Diagnose a specific Claude session\n\n"
        "**Session Behavior:**\n"
        "• Sessions are automatically maintained per project directory\n"
        "• Switching directories with `/cd` resumes the session for that project\n"
        "• Use `/new` or `/end` to explicitly clear session context\n"
        "• Sessions persist across bot restarts\n\n"
        "**Usage Examples:**\n"
        "• `cd myproject` - Enter project directory\n"
        "• `ls` - See what's in current directory\n"
        "• `Create a simple Python script` - Ask Claude to code\n"
        "• Send a file to have Claude review it\n\n"
        "**File Operations:**\n"
        "• Send text files (.py, .js, .md, etc.) for review\n"
        "• Claude can read, modify, and create files\n"
        "• All file operations are within your approved directory\n\n"
        "**Security Features:**\n"
        "• 🔒 Path traversal protection\n"
        "• ⏱️ Rate limiting to prevent abuse\n"
        "• 📊 Usage tracking and limits\n"
        "• 🛡️ Input validation and sanitization\n\n"
        "**Tips:**\n"
        "• Use specific, clear requests for best results\n"
        "• Check `/context` to monitor your usage\n"
        "• Use quick action buttons when available\n"
        "• File uploads are automatically processed by Claude\n\n"
        "Need more help? Contact your administrator."
    )

    await update.message.reply_text(help_text, parse_mode="Markdown")


async def new_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /new command - explicitly starts a fresh session, clearing previous context."""
    settings: Settings = context.bot_data["settings"]

    # Get current directory (default to approved directory)
    current_dir = context.user_data.get(
        "current_directory", settings.approved_directory
    )
    relative_path = current_dir.relative_to(settings.approved_directory)

    # Track what was cleared for user feedback
    old_session_id = context.user_data.get("claude_session_id")

    # Clear existing session data - this is the explicit way to reset context
    context.user_data["claude_session_id"] = None
    context.user_data["session_started"] = True
    context.user_data["force_new_session"] = True

    cleared_info = ""
    if old_session_id:
        cleared_info = f"\n🗑️ Previous session `{old_session_id[:8]}...` cleared."

    keyboard = [
        [
            InlineKeyboardButton(
                "📝 Start Coding", callback_data="action:start_coding"
            ),
            InlineKeyboardButton(
                "📁 Change Project", callback_data="action:show_projects"
            ),
        ],
        [
            InlineKeyboardButton(
                "📋 Quick Actions", callback_data="action:quick_actions"
            ),
            InlineKeyboardButton("❓ Help", callback_data="action:help"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"🆕 **New Claude Code Session**\n\n"
        f"📂 Working directory: `{relative_path}/`{cleared_info}\n\n"
        f"Context has been cleared. Send a message to start fresh, "
        f"or use the buttons below:",
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )


async def continue_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /continue command with optional prompt."""
    user_id = update.effective_user.id
    settings: Settings = context.bot_data["settings"]
    claude_integration: ClaudeIntegration = context.bot_data.get("claude_integration")
    audit_logger: AuditLogger = context.bot_data.get("audit_logger")

    # Parse optional prompt from command arguments
    # If no prompt provided, use a default to continue the conversation
    prompt = " ".join(context.args) if context.args else None
    default_prompt = "Please continue where we left off"

    current_dir = context.user_data.get(
        "current_directory", settings.approved_directory
    )

    try:
        if not claude_integration:
            await update.message.reply_text(
                "❌ **Claude Integration Not Available**\n\n"
                "Claude integration is not properly configured."
            )
            return

        # Check if there's an existing session in user context
        claude_session_id = context.user_data.get("claude_session_id")

        if claude_session_id:
            # We have a session in context, continue it directly
            status_msg = await update.message.reply_text(
                f"🔄 **Continuing Session**\n\n"
                f"Session ID: `{claude_session_id[:8]}...`\n"
                f"Directory: `{current_dir.relative_to(settings.approved_directory)}/`\n\n"
                f"{'Processing your message...' if prompt else 'Continuing where you left off...'}",
                parse_mode="Markdown",
            )

            # Continue with the existing session
            # Use default prompt if none provided (Claude CLI requires a prompt)
            claude_response = await claude_integration.run_command(
                prompt=prompt or default_prompt,
                working_directory=current_dir,
                user_id=user_id,
                session_id=claude_session_id,
                permission_handler=build_permission_handler(
                    bot=context.bot,
                    chat_id=update.effective_chat.id,
                    settings=settings,
                ),
            )
        else:
            # No session in context, try to find the most recent session
            status_msg = await update.message.reply_text(
                "🔍 **Looking for Recent Session**\n\n"
                "Searching for your most recent session in this directory...",
                parse_mode="Markdown",
            )

            # Use default prompt if none provided
            claude_response = await claude_integration.continue_session(
                user_id=user_id,
                working_directory=current_dir,
                prompt=prompt or default_prompt,
            )

        if claude_response:
            # Update session ID in context
            context.user_data["claude_session_id"] = claude_response.session_id

            # Delete status message and send response
            await status_msg.delete()

            # Format and send Claude's response
            from ..utils.formatting import ResponseFormatter

            formatter = ResponseFormatter(settings)
            formatted_messages = formatter.format_claude_response(
                claude_response.content
            )

            for msg in formatted_messages:
                await update.message.reply_text(
                    msg.text,
                    parse_mode=msg.parse_mode,
                    reply_markup=msg.reply_markup,
                )

            # Log successful continue
            if audit_logger:
                await audit_logger.log_command(
                    user_id=user_id,
                    command="continue",
                    args=context.args or [],
                    success=True,
                )

        else:
            # No session found to continue
            await status_msg.edit_text(
                "❌ **No Session Found**\n\n"
                f"No recent Claude session found in this directory.\n"
                f"Directory: `{current_dir.relative_to(settings.approved_directory)}/`\n\n"
                f"**What you can do:**\n"
                f"• Use `/new` to start a fresh session\n"
                f"• Use `/context` to check your sessions\n"
                f"• Navigate to a different directory with `/cd`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "🆕 New Session", callback_data="action:new_session"
                            ),
                            InlineKeyboardButton(
                                "📊 Context", callback_data="action:status"
                            ),
                        ]
                    ]
                ),
            )

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in continue command", error=error_msg, user_id=user_id)

        # Delete status message if it exists
        try:
            if "status_msg" in locals():
                await status_msg.delete()
        except Exception:
            pass

        # Send error response
        await update.message.reply_text(
            f"❌ **Error Continuing Session**\n\n"
            f"An error occurred while trying to continue your session:\n\n"
            f"`{error_msg}`\n\n"
            f"**Suggestions:**\n"
            f"• Try starting a new session with `/new`\n"
            f"• Check your session status with `/context`\n"
            f"• Contact support if the issue persists",
            parse_mode="Markdown",
        )

        # Log failed continue
        if audit_logger:
            await audit_logger.log_command(
                user_id=user_id,
                command="continue",
                args=context.args or [],
                success=False,
            )


async def list_files(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /ls command."""
    user_id = update.effective_user.id
    settings: Settings = context.bot_data["settings"]
    audit_logger: AuditLogger = context.bot_data.get("audit_logger")

    # Get current directory
    current_dir = context.user_data.get(
        "current_directory", settings.approved_directory
    )

    try:
        # List directory contents
        items = []
        directories = []
        files = []

        for item in sorted(current_dir.iterdir()):
            # Skip hidden files (starting with .)
            if item.name.startswith("."):
                continue

            # Escape markdown special characters in filenames
            safe_name = _escape_markdown(item.name)

            if item.is_dir():
                directories.append(f"📁 {safe_name}/")
            else:
                # Get file size
                try:
                    size = item.stat().st_size
                    size_str = _format_file_size(size)
                    files.append(f"📄 {safe_name} ({size_str})")
                except OSError:
                    files.append(f"📄 {safe_name}")

        # Combine directories first, then files
        items = directories + files

        # Format response
        relative_path = current_dir.relative_to(settings.approved_directory)
        if not items:
            message = f"📂 `{relative_path}/`\n\n_(empty directory)_"
        else:
            message = f"📂 `{relative_path}/`\n\n"

            # Limit items shown to prevent message being too long
            max_items = 50
            if len(items) > max_items:
                shown_items = items[:max_items]
                message += "\n".join(shown_items)
                message += f"\n\n_... and {len(items) - max_items} more items_"
            else:
                message += "\n".join(items)

        # Add navigation buttons if not at root
        keyboard = []
        if current_dir != settings.approved_directory:
            keyboard.append(
                [
                    InlineKeyboardButton("⬆️ Go Up", callback_data="cd:.."),
                    InlineKeyboardButton("🏠 Go to Root", callback_data="cd:/"),
                ]
            )

        keyboard.append(
            [
                InlineKeyboardButton("🔄 Refresh", callback_data="action:refresh_ls"),
                InlineKeyboardButton(
                    "📁 Projects", callback_data="action:show_projects"
                ),
            ]
        )

        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

        await update.message.reply_text(
            message, parse_mode="Markdown", reply_markup=reply_markup
        )

        # Log successful command
        if audit_logger:
            await audit_logger.log_command(user_id, "ls", [], True)

    except Exception as e:
        error_msg = f"❌ Error listing directory: {str(e)}"
        await update.message.reply_text(error_msg)

        # Log failed command
        if audit_logger:
            await audit_logger.log_command(user_id, "ls", [], False)

        logger.error("Error in list_files command", error=str(e), user_id=user_id)


async def change_directory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /cd command."""
    user_id = update.effective_user.id
    settings: Settings = context.bot_data["settings"]
    security_validator: SecurityValidator = context.bot_data.get("security_validator")
    audit_logger: AuditLogger = context.bot_data.get("audit_logger")

    # Parse arguments
    if not context.args:
        await update.message.reply_text(
            "**Usage:** `/cd <directory>`\n\n"
            "**Examples:**\n"
            "• `/cd myproject` - Enter subdirectory\n"
            "• `/cd ..` - Go up one level\n"
            "• `/cd /` - Go to root of approved directory\n\n"
            "**Tips:**\n"
            "• Use `/ls` to see available directories\n"
            "• Use `/projects` to see all projects",
            parse_mode="Markdown",
        )
        return

    target_path = " ".join(context.args)
    current_dir = context.user_data.get(
        "current_directory", settings.approved_directory
    )

    try:
        # Validate path using security validator
        if security_validator:
            valid, resolved_path, error = security_validator.validate_path(
                target_path, current_dir
            )

            if not valid:
                await update.message.reply_text(f"❌ **Access Denied**\n\n{error}")

                # Log security violation
                if audit_logger:
                    await audit_logger.log_security_violation(
                        user_id=user_id,
                        violation_type="path_traversal_attempt",
                        details=f"Attempted path: {target_path}",
                        severity="medium",
                    )
                return
        else:
            # Fallback validation without security validator
            if target_path == "/":
                resolved_path = settings.approved_directory
            elif target_path == "..":
                resolved_path = current_dir.parent
                if not str(resolved_path).startswith(str(settings.approved_directory)):
                    resolved_path = settings.approved_directory
            else:
                resolved_path = current_dir / target_path
                resolved_path = resolved_path.resolve()

        # Check if directory exists and is actually a directory
        if not resolved_path.exists():
            await update.message.reply_text(
                f"❌ **Directory Not Found**\n\n`{target_path}` does not exist."
            )
            return

        if not resolved_path.is_dir():
            await update.message.reply_text(
                f"❌ **Not a Directory**\n\n`{target_path}` is not a directory."
            )
            return

        # Update current directory in user data
        context.user_data["current_directory"] = resolved_path

        # Look up existing session for the new directory instead of clearing
        claude_integration: ClaudeIntegration = context.bot_data.get(
            "claude_integration"
        )
        resumed_session_info = ""
        if claude_integration:
            existing_session = await claude_integration._find_resumable_session(
                user_id, resolved_path
            )
            if existing_session:
                context.user_data["claude_session_id"] = existing_session.session_id
                resumed_session_info = (
                    f"\n🔄 Resumed session `{existing_session.session_id[:8]}...` "
                    f"({existing_session.message_count} messages)"
                )
            else:
                # No session for this directory - clear the current one
                context.user_data["claude_session_id"] = None
                resumed_session_info = (
                    "\n🆕 No existing session. Send a message to start a new one."
                )

        # Send confirmation
        relative_path = resolved_path.relative_to(settings.approved_directory)
        await update.message.reply_text(
            f"✅ **Directory Changed**\n\n"
            f"📂 Current directory: `{relative_path}/`"
            f"{resumed_session_info}",
            parse_mode="Markdown",
        )

        # Log successful command
        if audit_logger:
            await audit_logger.log_command(user_id, "cd", [target_path], True)

    except Exception as e:
        error_msg = f"❌ **Error changing directory**\n\n{str(e)}"
        await update.message.reply_text(error_msg, parse_mode="Markdown")

        # Log failed command
        if audit_logger:
            await audit_logger.log_command(user_id, "cd", [target_path], False)

        logger.error("Error in change_directory command", error=str(e), user_id=user_id)


async def print_working_directory(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /pwd command."""
    settings: Settings = context.bot_data["settings"]
    current_dir = context.user_data.get(
        "current_directory", settings.approved_directory
    )

    relative_path = current_dir.relative_to(settings.approved_directory)
    absolute_path = str(current_dir)

    # Add quick navigation buttons
    keyboard = [
        [
            InlineKeyboardButton("📁 List Files", callback_data="action:ls"),
            InlineKeyboardButton("📋 Projects", callback_data="action:show_projects"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"📍 **Current Directory**\n\n"
        f"Relative: `{relative_path}/`\n"
        f"Absolute: `{absolute_path}`",
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )


async def show_projects(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /projects command."""
    settings: Settings = context.bot_data["settings"]

    try:
        # Get directories in approved directory (these are "projects")
        projects = []
        for item in sorted(settings.approved_directory.iterdir()):
            if item.is_dir() and not item.name.startswith("."):
                projects.append(item.name)

        if not projects:
            await update.message.reply_text(
                "📁 **No Projects Found**\n\n"
                "No subdirectories found in your approved directory.\n"
                "Create some directories to organize your projects!"
            )
            return

        # Create inline keyboard with project buttons
        keyboard = []
        for i in range(0, len(projects), 2):
            row = []
            for j in range(2):
                if i + j < len(projects):
                    project = projects[i + j]
                    row.append(
                        InlineKeyboardButton(
                            f"📁 {project}", callback_data=f"cd:{project}"
                        )
                    )
            keyboard.append(row)

        # Add navigation buttons
        keyboard.append(
            [
                InlineKeyboardButton("🏠 Go to Root", callback_data="cd:/"),
                InlineKeyboardButton(
                    "🔄 Refresh", callback_data="action:show_projects"
                ),
            ]
        )

        reply_markup = InlineKeyboardMarkup(keyboard)

        project_list = "\n".join([f"• `{project}/`" for project in projects])

        await update.message.reply_text(
            f"📁 **Available Projects**\n\n"
            f"{project_list}\n\n"
            f"Click a project below to navigate to it:",
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Error loading projects: {str(e)}")
        logger.error("Error in show_projects command", error=str(e))


async def session_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /context command - show real CLI session data."""
    user_id = update.effective_user.id
    settings: Settings = context.bot_data["settings"]
    full_mode = _is_context_full_mode(context)
    status_msg = await update.message.reply_text("⏳ 正在获取会话状态，请稍候...")

    try:
        claude_session_id = context.user_data.get("claude_session_id")
        current_dir = context.user_data.get(
            "current_directory", settings.approved_directory
        )
        relative_path = current_dir.relative_to(settings.approved_directory)
        current_model = context.user_data.get("claude_model")

        status_lines = [
            "**Session Status**\n",
            f"Directory: `{relative_path}/`",
            f"Model: `{current_model or 'default'}`",
        ]
        claude_integration: ClaudeIntegration = context.bot_data.get(
            "claude_integration"
        )
        precise_context = None
        info = None
        resumable_payload = None

        if claude_session_id:
            status_lines.append(f"Session: `{claude_session_id[:8]}...`")
            if claude_integration:
                precise_context = await claude_integration.get_precise_context_usage(
                    session_id=claude_session_id,
                    working_directory=current_dir,
                    model=current_model,
                )
                if precise_context:
                    status_lines.extend(
                        build_precise_context_status_lines(precise_context)
                    )

                info = await claude_integration.get_session_info(claude_session_id)
                if info:
                    status_lines.append(f"Messages: {info.get('messages', 0)}")
                    status_lines.append(f"Turns: {info.get('turns', 0)}")
                    status_lines.append(f"Cost: `${info.get('cost', 0.0):.4f}`")

                    # Model usage details
                    model_usage = info.get("model_usage")
                    if model_usage and not precise_context:
                        status_lines.extend(
                            build_model_usage_status_lines(
                                model_usage=model_usage,
                                current_model=current_model,
                                allow_estimated_ratio=True,
                            )
                        )
        else:
            status_lines.append("Session: none")

            # Check for resumable session
            if claude_integration:
                existing = await claude_integration._find_resumable_session(
                    user_id, current_dir
                )
                if existing:
                    resumable_payload = {
                        "session_id": existing.session_id,
                        "message_count": existing.message_count,
                    }
                    status_lines.append(
                        f"Resumable: `{existing.session_id[:8]}...` "
                        f"({existing.message_count} msgs)"
                    )

        if full_mode:
            payload = _build_status_full_payload(
                relative_path=relative_path,
                current_model=current_model,
                claude_session_id=claude_session_id,
                precise_context=precise_context,
                info=info,
                resumable_payload=resumable_payload,
            )
            full_text = _render_status_full_text(payload)
            chunks = _split_status_text(full_text)
            await status_msg.edit_text(chunks[0], parse_mode=None)
            for extra_chunk in chunks[1:]:
                await update.message.reply_text(extra_chunk, parse_mode=None)
        else:
            await status_msg.edit_text(
                "\n".join(status_lines),
                parse_mode="Markdown",
            )
    except Exception as e:
        logger.error("Error in status command", error=str(e), user_id=user_id)
        try:
            await status_msg.edit_text("❌ 获取状态失败，请稍后重试。")
        except Exception:
            await update.message.reply_text("❌ 获取状态失败，请稍后重试。")


async def export_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /export command."""
    user_id = update.effective_user.id
    features = context.bot_data.get("features")

    # Check if session export is available
    session_exporter = features.get_session_export() if features else None

    if not session_exporter:
        await update.message.reply_text(
            "📤 **Export Session**\n\n"
            "Session export functionality is not available.\n\n"
            "**Planned features:**\n"
            "• Export conversation history\n"
            "• Save session state\n"
            "• Share conversations\n"
            "• Create session backups"
        )
        return

    # Get current session
    claude_session_id = context.user_data.get("claude_session_id")

    if not claude_session_id:
        await update.message.reply_text(
            "❌ **No Active Session**\n\n"
            "There's no active Claude session to export.\n\n"
            "**What you can do:**\n"
            "• Start a new session with `/new`\n"
            "• Continue an existing session with `/continue`\n"
            "• Check your status with `/context`"
        )
        return

    # Create export format selection keyboard
    keyboard = [
        [
            InlineKeyboardButton("📝 Markdown", callback_data="export:markdown"),
            InlineKeyboardButton("🌐 HTML", callback_data="export:html"),
        ],
        [
            InlineKeyboardButton("📋 JSON", callback_data="export:json"),
            InlineKeyboardButton("❌ Cancel", callback_data="export:cancel"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "📤 **Export Session**\n\n"
        f"Ready to export session: `{claude_session_id[:8]}...`\n\n"
        "**Choose export format:**",
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )


async def end_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /end command to terminate the current session."""
    user_id = update.effective_user.id
    settings: Settings = context.bot_data["settings"]

    # Check if there's an active session
    claude_session_id = context.user_data.get("claude_session_id")

    if not claude_session_id:
        await update.message.reply_text(
            "ℹ️ **No Active Session**\n\n"
            "There's no active Claude session to end.\n\n"
            "**What you can do:**\n"
            "• Use `/new` to start a new session\n"
            "• Use `/context` to check your session status\n"
            "• Send any message to start a conversation"
        )
        return

    # Get current directory for display
    current_dir = context.user_data.get(
        "current_directory", settings.approved_directory
    )
    relative_path = current_dir.relative_to(settings.approved_directory)

    # Clear session data
    context.user_data["claude_session_id"] = None
    context.user_data["session_started"] = False
    context.user_data["last_message"] = None

    # Create quick action buttons
    keyboard = [
        [
            InlineKeyboardButton("🆕 New Session", callback_data="action:new_session"),
            InlineKeyboardButton(
                "📁 Change Project", callback_data="action:show_projects"
            ),
        ],
        [
            InlineKeyboardButton("📊 Context", callback_data="action:status"),
            InlineKeyboardButton("❓ Help", callback_data="action:help"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "✅ **Session Ended**\n\n"
        f"Your Claude session has been terminated.\n\n"
        f"**Current Status:**\n"
        f"• Directory: `{relative_path}/`\n"
        f"• Session: None\n"
        f"• Ready for new commands\n\n"
        f"**Next Steps:**\n"
        f"• Start a new session with `/new`\n"
        f"• Check status with `/context`\n"
        f"• Send any message to begin a new conversation",
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )

    logger.info("Session ended by user", user_id=user_id, session_id=claude_session_id)


async def quick_actions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /actions command to show quick actions."""
    user_id = update.effective_user.id
    settings: Settings = context.bot_data["settings"]
    features = context.bot_data.get("features")

    if not features or not features.is_enabled("quick_actions"):
        await update.message.reply_text(
            "❌ **Quick Actions Disabled**\n\n"
            "Quick actions feature is not enabled.\n"
            "Contact your administrator to enable this feature."
        )
        return

    # Get current directory
    current_dir = context.user_data.get(
        "current_directory", settings.approved_directory
    )

    try:
        quick_action_manager = features.get_quick_actions()
        if not quick_action_manager:
            await update.message.reply_text(
                "❌ **Quick Actions Unavailable**\n\n"
                "Quick actions service is not available."
            )
            return

        # Get context-aware actions
        actions = await quick_action_manager.get_suggestions(
            session_data={"working_directory": str(current_dir), "user_id": user_id}
        )

        if not actions:
            await update.message.reply_text(
                "🤖 **No Actions Available**\n\n"
                "No quick actions are available for the current context.\n\n"
                "**Try:**\n"
                "• Navigating to a project directory with `/cd`\n"
                "• Creating some code files\n"
                "• Starting a Claude session with `/new`"
            )
            return

        # Create inline keyboard
        keyboard = quick_action_manager.create_inline_keyboard(actions, max_columns=2)

        relative_path = current_dir.relative_to(settings.approved_directory)
        await update.message.reply_text(
            f"⚡ **Quick Actions**\n\n"
            f"📂 Context: `{relative_path}/`\n\n"
            f"Select an action to execute:",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

    except Exception as e:
        await update.message.reply_text(f"❌ **Error Loading Actions**\n\n{str(e)}")
        logger.error("Error in quick_actions command", error=str(e), user_id=user_id)


async def git_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /git command to show git repository information."""
    user_id = update.effective_user.id
    settings: Settings = context.bot_data["settings"]
    features = context.bot_data.get("features")

    if not features or not features.is_enabled("git"):
        await update.message.reply_text(
            "❌ **Git Integration Disabled**\n\n"
            "Git integration feature is not enabled.\n"
            "Contact your administrator to enable this feature."
        )
        return

    # Get current directory
    current_dir = context.user_data.get(
        "current_directory", settings.approved_directory
    )

    try:
        git_integration = features.get_git_integration()
        if not git_integration:
            await update.message.reply_text(
                "❌ **Git Integration Unavailable**\n\n"
                "Git integration service is not available."
            )
            return

        # Check if current directory is a git repository
        if not (current_dir / ".git").exists():
            await update.message.reply_text(
                f"📂 **Not a Git Repository**\n\n"
                f"Current directory `{current_dir.relative_to(settings.approved_directory)}/` is not a git repository.\n\n"
                f"**Options:**\n"
                f"• Navigate to a git repository with `/cd`\n"
                f"• Initialize a new repository (ask Claude to help)\n"
                f"• Clone an existing repository (ask Claude to help)"
            )
            return

        # Get git status
        git_status = await git_integration.get_status(current_dir)

        # Format status message
        relative_path = current_dir.relative_to(settings.approved_directory)
        status_message = f"🔗 **Git Repository Status**\n\n"
        status_message += f"📂 Directory: `{relative_path}/`\n"
        status_message += f"🌿 Branch: `{git_status.branch}`\n"

        if git_status.ahead > 0:
            status_message += f"⬆️ Ahead: {git_status.ahead} commits\n"
        if git_status.behind > 0:
            status_message += f"⬇️ Behind: {git_status.behind} commits\n"

        # Show file changes
        if not git_status.is_clean:
            status_message += f"\n**Changes:**\n"
            if git_status.modified:
                status_message += f"📝 Modified: {len(git_status.modified)} files\n"
            if git_status.added:
                status_message += f"➕ Added: {len(git_status.added)} files\n"
            if git_status.deleted:
                status_message += f"➖ Deleted: {len(git_status.deleted)} files\n"
            if git_status.untracked:
                status_message += f"❓ Untracked: {len(git_status.untracked)} files\n"
        else:
            status_message += "\n✅ Working directory clean\n"

        # Create action buttons
        keyboard = [
            [
                InlineKeyboardButton("📊 Show Diff", callback_data="git:diff"),
                InlineKeyboardButton("📜 Show Log", callback_data="git:log"),
            ],
            [
                InlineKeyboardButton("🔄 Refresh", callback_data="git:status"),
                InlineKeyboardButton("📁 Files", callback_data="action:ls"),
            ],
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            status_message, parse_mode="Markdown", reply_markup=reply_markup
        )

    except Exception as e:
        await update.message.reply_text(f"❌ **Git Error**\n\n{str(e)}")
        logger.error("Error in git_command", error=str(e), user_id=user_id)


async def cancel_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /cancel command - cancel the active Claude task."""
    user_id = update.effective_user.id

    task_registry: TaskRegistry = context.bot_data.get("task_registry")
    if not task_registry:
        await update.message.reply_text("Task registry not available.")
        return

    cancelled = await task_registry.cancel(user_id)
    if cancelled:
        await update.message.reply_text("Task cancellation requested.")
    else:
        await update.message.reply_text("No active task to cancel.")

    audit_logger: AuditLogger = context.bot_data.get("audit_logger")
    if audit_logger:
        await audit_logger.log_command(
            user_id=user_id, command="cancel", args=[], success=cancelled
        )


def _split_text_chunks(text: str, max_chars: int = 3500) -> list[str]:
    """Split long text into Telegram-safe chunks while preserving line boundaries."""
    stripped = text.strip()
    if not stripped:
        return ["(empty output)"]

    lines = stripped.splitlines(keepends=True)
    chunks: list[str] = []
    current = ""

    for line in lines:
        if len(current) + len(line) <= max_chars:
            current += line
            continue

        if current:
            chunks.append(current.rstrip())
            current = ""

        # Handle single lines that are still too long.
        if len(line) > max_chars:
            start = 0
            while start < len(line):
                part = line[start : start + max_chars]
                chunks.append(part.rstrip())
                start += max_chars
        else:
            current = line

    if current:
        chunks.append(current.rstrip())

    return chunks


async def codex_diag_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /codexdiag command to diagnose codex MCP calls without manual shell."""
    user_id = update.effective_user.id
    settings: Settings = context.bot_data["settings"]
    audit_logger: AuditLogger = context.bot_data.get("audit_logger")

    current_dir = context.user_data.get(
        "current_directory", settings.approved_directory
    )
    project_dir = current_dir
    explicit_session_id = None

    args = [arg.strip() for arg in context.args if arg and arg.strip()]
    if args:
        if args[0].lower() in {"root", "/"}:
            project_dir = settings.approved_directory
            if len(args) > 1:
                explicit_session_id = args[1]
        else:
            explicit_session_id = args[0]

    script_path = (
        Path(__file__).resolve().parents[3] / "scripts" / "cc_codex_diagnose.py"
    )
    if not script_path.exists():
        await update.message.reply_text(
            f"❌ 诊断脚本不存在：{script_path}\n"
            "请检查项目是否包含 `scripts/cc_codex_diagnose.py`。"
        )
        if audit_logger:
            await audit_logger.log_command(
                user_id=user_id,
                command="codexdiag",
                args=context.args or [],
                success=False,
            )
        return

    status_msg = await update.message.reply_text(
        "🔎 正在诊断 codex MCP 调用状态，请稍候..."
    )

    cmd = [
        sys.executable,
        str(script_path),
        "--project",
        str(project_dir),
    ]
    if explicit_session_id:
        cmd.extend(["--session-id", explicit_session_id])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=45)
    except asyncio.TimeoutError:
        if "proc" in locals():
            proc.kill()
            await proc.communicate()
        await status_msg.edit_text(
            "⏰ 诊断超时（45 秒）。\n"
            "建议稍后重试，或先检查 `~/.claude/debug/*.txt` 是否持续写入。"
        )
        if audit_logger:
            await audit_logger.log_command(
                user_id=user_id,
                command="codexdiag",
                args=context.args or [],
                success=False,
            )
        return
    except Exception as e:
        await status_msg.edit_text(f"❌ 执行诊断失败：{e}")
        if audit_logger:
            await audit_logger.log_command(
                user_id=user_id,
                command="codexdiag",
                args=context.args or [],
                success=False,
            )
        return

    stdout_text = stdout.decode("utf-8", errors="replace").strip()
    stderr_text = stderr.decode("utf-8", errors="replace").strip()

    if proc.returncode != 0:
        err_body = stderr_text or stdout_text or "无可用输出"
        err_chunks = _split_text_chunks(err_body, max_chars=3200)
        await status_msg.edit_text(
            "❌ codex 诊断执行失败。\n"
            f"项目目录: {project_dir}\n"
            f"返回码: {proc.returncode}\n\n"
            f"{err_chunks[0]}"
        )
        for chunk in err_chunks[1:]:
            await update.message.reply_text(chunk)
        if audit_logger:
            await audit_logger.log_command(
                user_id=user_id,
                command="codexdiag",
                args=context.args or [],
                success=False,
            )
        return

    output_chunks = _split_text_chunks(stdout_text)
    total = len(output_chunks)
    header = (
        "✅ codex 诊断完成。\n"
        f"项目目录: {project_dir}\n"
        f"会话范围: {'指定会话' if explicit_session_id else '自动选择最近会话'}\n\n"
    )
    await status_msg.edit_text(f"{header}{output_chunks[0]}")
    for idx, chunk in enumerate(output_chunks[1:], start=2):
        await update.message.reply_text(f"[{idx}/{total}]\n{chunk}")

    if audit_logger:
        await audit_logger.log_command(
            user_id=user_id,
            command="codexdiag",
            args=context.args or [],
            success=True,
        )


def _format_file_size(size: int) -> str:
    """Format file size in human-readable format."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f}{unit}" if unit != "B" else f"{size}B"
        size /= 1024
    return f"{size:.1f}TB"


def _escape_markdown(text: str) -> str:
    """Escape special markdown characters in text for Telegram."""
    # Escape characters that have special meaning in Telegram Markdown
    special_chars = [
        "_",
        "*",
        "[",
        "]",
        "(",
        ")",
        "~",
        "`",
        ">",
        "#",
        "+",
        "-",
        "=",
        "|",
        "{",
        "}",
        ".",
        "!",
    ]
    for char in special_chars:
        text = text.replace(char, f"\\{char}")
    return text


async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /model command - show inline keyboard to select Claude model."""
    current = context.user_data.get("claude_model")

    keyboard = [
        [
            InlineKeyboardButton(
                f"{'> ' if current == 'sonnet' else ''}Sonnet",
                callback_data="model:sonnet",
            ),
            InlineKeyboardButton(
                f"{'> ' if current == 'opus' else ''}Opus",
                callback_data="model:opus",
            ),
            InlineKeyboardButton(
                f"{'> ' if current == 'haiku' else ''}Haiku",
                callback_data="model:haiku",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{'> ' if not current else ''}Default",
                callback_data="model:default",
            ),
        ],
    ]

    await update.message.reply_text(
        f"Current model: `{current or 'default'}`\nSelect a model:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /resume command - resume a desktop Claude Code session."""
    user_id = update.effective_user.id
    settings: Settings = context.bot_data["settings"]

    # Lazy import to avoid circular deps
    from ...bot.resume_tokens import ResumeTokenManager
    from ...claude.desktop_scanner import DesktopSessionScanner

    # Get or create scanner and token manager
    scanner = context.bot_data.get("desktop_scanner")
    if scanner is None:
        scanner = DesktopSessionScanner(
            approved_directory=settings.approved_directory,
            cache_ttl_sec=settings.resume_scan_cache_ttl_seconds,
        )
        context.bot_data["desktop_scanner"] = scanner

    token_mgr = context.bot_data.get("resume_token_manager")
    if token_mgr is None:
        token_mgr = ResumeTokenManager()
        context.bot_data["resume_token_manager"] = token_mgr

    try:
        # S0 -> scan projects
        projects = await scanner.list_projects()

        current_dir = context.user_data.get("current_directory")

        if not projects:
            await update.message.reply_text(
                "No desktop Claude Code sessions found.\n\n"
                "Make sure you have used Claude Code CLI "
                "in a project under your approved directory.",
                parse_mode="Markdown",
            )
            return

        message_text, keyboard = build_resume_project_selector(
            projects=projects,
            approved_root=settings.approved_directory,
            token_mgr=token_mgr,
            user_id=user_id,
            current_directory=Path(current_dir) if current_dir else None,
            show_all=False,
        )

        await update.message.reply_text(
            message_text,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

    except Exception as e:
        logger.error("Error in resume command", error=str(e))
        await update.message.reply_text(f"Failed to scan desktop sessions: {e}")
