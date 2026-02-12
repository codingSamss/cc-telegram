"""Message handlers for non-command inputs."""

import asyncio
from typing import Any, Callable, Optional

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ...claude.task_registry import TaskRegistry

from ...claude.exceptions import ClaudeToolValidationError
from ...config.settings import Settings
from ...security.audit import AuditLogger
from ...security.rate_limiter import RateLimiter
from ...security.validators import SecurityValidator

logger = structlog.get_logger()


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
        return f"🤖 *Claude is working...*\n\n{safe_preview}"

    elif update_obj.type == "system":
        # System initialization or other system messages
        if update_obj.metadata and update_obj.metadata.get("subtype") == "init":
            tools_count = len(update_obj.metadata.get("tools", []))
            model = _escape_md(update_obj.metadata.get("model", "Claude"))
            return f"🚀 *Starting {model}* with {tools_count} tools available"
        if update_obj.metadata and update_obj.metadata.get("subtype") == "model_resolved":
            model = _escape_md(update_obj.metadata.get("model", "Claude"))
            return f"🧠 *Resolved model:* {model}"

    return None


def _format_error_message(error_str: str) -> str:
    """Format error messages for user-friendly display."""
    if "usage limit reached" in error_str.lower():
        # Usage limit error - already user-friendly from integration.py
        return error_str
    elif "tool not allowed" in error_str.lower():
        # Tool validation error - already handled in facade.py
        return error_str
    elif "no conversation found" in error_str.lower():
        return (
            f"🔄 **Session Not Found**\n\n"
            f"The Claude session could not be found or has expired.\n\n"
            f"**What you can do:**\n"
            f"• Use `/new` to start a fresh session\n"
            f"• Try your request again\n"
            f"• Use `/status` to check your current session"
        )
    elif "rate limit" in error_str.lower():
        return (
            f"⏱️ **Rate Limit Reached**\n\n"
            f"Too many requests in a short time period.\n\n"
            f"**What you can do:**\n"
            f"• Wait a moment before trying again\n"
            f"• Use simpler requests\n"
            f"• Check your current usage with `/status`"
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
            f"❌ **Claude Code Error**\n\n"
            f"Failed to process your request: {safe_error}\n\n"
            f"Please try again or contact the administrator if the problem persists."
        )


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


async def handle_text_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle regular text messages as Claude prompts."""
    user_id = update.effective_user.id
    message_text = update.message.text
    settings: Settings = context.bot_data["settings"]

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
        if task_registry and await task_registry.is_busy(user_id):
            await update.message.reply_text(
                "A task is already running. Use /cancel to cancel it."
            )
            return

        # Send typing indicator
        await update.message.chat.send_action("typing")

        # Create progress message with Cancel button
        cancel_keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Cancel", callback_data="cancel:task")]]
        )
        progress_msg = await update.message.reply_text(
            "🤔 Processing your request...",
            reply_to_message_id=update.message.message_id,
            reply_markup=cancel_keyboard,
        )

        # Get Claude integration and storage from context
        claude_integration = context.bot_data.get("claude_integration")
        storage = context.bot_data.get("storage")

        if not claude_integration:
            await update.message.reply_text(
                "❌ **Claude integration not available**\n\n"
                "The Claude Code integration is not properly configured. "
                "Please contact the administrator.",
                parse_mode="Markdown",
            )
            return

        # Get current directory
        current_dir = context.user_data.get(
            "current_directory", settings.approved_directory
        )

        # Get existing session ID
        session_id = context.user_data.get("claude_session_id")
        force_new_session = context.user_data.pop("force_new_session", False)

        # Enhanced stream updates handler with accumulated progress tracking
        progress_lines: list[str] = []
        all_progress_lines: list[str] = []  # 完整思考过程（不受溢出 clear 影响）
        frozen_messages: list = []  # 被冻结的旧进度消息
        last_progress_text = ""

        async def stream_handler(update_obj):
            nonlocal progress_msg, last_progress_text
            try:
                progress_text = await _format_progress_update(update_obj)
                if not progress_text:
                    return

                progress_lines.append(progress_text)
                # Only collect non-content updates as thinking process
                if not (
                    update_obj.type == "assistant"
                    and update_obj.content
                    and not update_obj.tool_calls
                ):
                    all_progress_lines.append(progress_text)
                full_text = "\n".join(progress_lines)

                # If accumulated text exceeds Telegram limit, freeze current
                # message and start a new one
                if len(full_text) > 3800:
                    frozen_messages.append(progress_msg)
                    progress_lines.clear()
                    progress_lines.append(progress_text)
                    full_text = progress_text
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
                    return

                # Skip edit if content hasn't changed
                if full_text == last_progress_text:
                    return

                last_progress_text = full_text
                await progress_msg.edit_text(
                    full_text,
                    parse_mode="Markdown",
                    reply_markup=cancel_keyboard,
                )
            except Exception as e:
                logger.warning("Failed to update progress message", error=str(e))

        # Build permission handler only when SDK is active
        settings_obj: Settings = context.bot_data["settings"]
        permission_handler = build_permission_handler(
            bot=context.bot, chat_id=update.effective_chat.id, settings=settings_obj
        )

        # Run Claude command as cancellable task

        async def _run_claude():
            return await claude_integration.run_command(
                prompt=message_text,
                working_directory=current_dir,
                user_id=user_id,
                session_id=session_id,
                on_stream=stream_handler,
                force_new_session=force_new_session,
                permission_handler=permission_handler,
                model=context.user_data.get("claude_model"),
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
            )

        claude_response = None
        try:
            claude_response = await task

            # Mark task as completed
            if task_registry:
                await task_registry.complete(user_id)

            # Update session ID
            context.user_data["claude_session_id"] = claude_response.session_id

            # Check if Claude changed the working directory and update our tracking
            _update_working_directory_from_claude_response(
                claude_response, context, settings, user_id
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
            if task_registry:
                await task_registry.remove(user_id)
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
            logger.error("Claude integration failed", error=str(e), user_id=user_id)
            if task_registry:
                await task_registry.fail(user_id)
            # Format error and create FormattedMessage
            from ..utils.formatting import FormattedMessage

            formatted_messages = [
                FormattedMessage(_format_error_message(str(e)), parse_mode="Markdown")
            ]

        # Clean up task registry
        if task_registry:
            await task_registry.remove(user_id)

        # Collapse progress message into summary with expand button
        if all_progress_lines:
            summary_text = _generate_thinking_summary(all_progress_lines)
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
                await update.message.reply_text(
                    message.text,
                    parse_mode=message.parse_mode,
                    reply_markup=message.reply_markup,
                    reply_to_message_id=update.message.message_id if i == 0 else None,
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
                    "❌ Failed to send response. Please try again.",
                    reply_to_message_id=update.message.message_id if i == 0 else None,
                )

        # Update session info
        context.user_data["last_message"] = update.message.text

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
                conversation_context = conversation_enhancer.get_or_create_context(
                    user_id
                )

                # Check if we should show follow-up suggestions
                if conversation_enhancer.should_show_suggestions(
                    claude_response.tools_used or [], claude_response.content
                ):
                    # Generate follow-up suggestions
                    suggestions = conversation_enhancer.generate_follow_up_suggestions(
                        claude_response.content,
                        claude_response.tools_used or [],
                        conversation_context,
                    )

                    if suggestions:
                        # Create keyboard with suggestions
                        suggestion_keyboard = (
                            conversation_enhancer.create_follow_up_keyboard(suggestions)
                        )

                        # Send follow-up suggestions
                        await update.message.reply_text(
                            "💡 **What would you like to do next?**",
                            parse_mode="Markdown",
                            reply_markup=suggestion_keyboard,
                        )

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

        error_msg = _format_error_message(str(e))
        await update.message.reply_text(error_msg, parse_mode="Markdown")

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
            f"📄 Processing file: `{document.file_name}`...", parse_mode="Markdown"
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
                    f"📄 Processing {processed_file.type} file: `{document.file_name}`...",
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
                    "❌ **File Format Not Supported**\n\n"
                    "File must be text-based and UTF-8 encoded.\n\n"
                    "**Supported formats:**\n"
                    "• Source code files (.py, .js, .ts, etc.)\n"
                    "• Text files (.txt, .md)\n"
                    "• Configuration files (.json, .yaml, .toml)\n"
                    "• Documentation files"
                )
                return

        # Delete progress message
        await progress_msg.delete()

        # Create a new progress message for Claude processing
        claude_progress_msg = await update.message.reply_text(
            "🤖 Processing file with Claude...", parse_mode="Markdown"
        )

        # Get Claude integration from context
        claude_integration = context.bot_data.get("claude_integration")

        if not claude_integration:
            await claude_progress_msg.edit_text(
                "❌ **Claude integration not available**\n\n"
                "The Claude Code integration is not properly configured.",
                parse_mode="Markdown",
            )
            return

        # Get current directory and session
        current_dir = context.user_data.get(
            "current_directory", settings.approved_directory
        )
        session_id = context.user_data.get("claude_session_id")
        force_new_session = context.user_data.pop("force_new_session", False)
        permission_handler = build_permission_handler(
            bot=context.bot, chat_id=update.effective_chat.id, settings=settings
        )

        # Process with Claude
        try:
            claude_response = await claude_integration.run_command(
                prompt=prompt,
                working_directory=current_dir,
                user_id=user_id,
                session_id=session_id,
                force_new_session=force_new_session,
                permission_handler=permission_handler,
                model=context.user_data.get("claude_model"),
            )

            # Update session ID
            context.user_data["claude_session_id"] = claude_response.session_id

            # Check if Claude changed the working directory and update our tracking
            _update_working_directory_from_claude_response(
                claude_response, context, settings, user_id
            )

            # Format and send response
            from ..utils.formatting import ResponseFormatter

            formatter = ResponseFormatter(settings)
            formatted_messages = formatter.format_claude_response(
                claude_response.content
            )

            # Delete progress message
            await claude_progress_msg.delete()

            # Send responses
            for i, message in enumerate(formatted_messages):
                await update.message.reply_text(
                    message.text,
                    parse_mode=message.parse_mode,
                    reply_markup=message.reply_markup,
                    reply_to_message_id=(update.message.message_id if i == 0 else None),
                )

                if i < len(formatted_messages) - 1:
                    await asyncio.sleep(0.5)

        except Exception as e:
            await claude_progress_msg.edit_text(
                _format_error_message(str(e)), parse_mode="Markdown"
            )
            logger.error("Claude file processing failed", error=str(e), user_id=user_id)

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

        error_msg = f"❌ **Error processing file**\n\n{str(e)}"
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

    # Check if enhanced image handler is available
    features = context.bot_data.get("features")
    image_handler = features.get_image_handler() if features else None

    if image_handler:
        try:
            # Send processing indicator
            progress_msg = await update.message.reply_text(
                "📸 Processing image...", parse_mode="Markdown"
            )

            # Get the largest photo size
            photo = update.message.photo[-1]

            # Process image with enhanced handler
            processed_image = await image_handler.process_image(
                photo, update.message.caption
            )

            # Delete progress message
            await progress_msg.delete()

            # Create Claude progress message
            claude_progress_msg = await update.message.reply_text(
                "🤖 Analyzing image with Claude...", parse_mode="Markdown"
            )

            # Multimodal image analysis requires SDK mode.
            if not settings.use_sdk:
                await claude_progress_msg.edit_text(
                    "📸 **Image Analysis Requires SDK Mode**\n\n"
                    "Current runtime is CLI subprocess mode (`USE_SDK=false`), "
                    "which cannot send image content to Claude.\n\n"
                    "**Fix:** set `USE_SDK=true` in `.env` and restart the bot.",
                    parse_mode="Markdown",
                )
                return

            # Get Claude integration
            claude_integration = context.bot_data.get("claude_integration")

            if not claude_integration:
                await claude_progress_msg.edit_text(
                    "❌ **Claude integration not available**\n\n"
                    "The Claude Code integration is not properly configured.",
                    parse_mode="Markdown",
                )
                return

            # Get current directory and session
            current_dir = context.user_data.get(
                "current_directory", settings.approved_directory
            )
            session_id = context.user_data.get("claude_session_id")
            force_new_session = context.user_data.pop("force_new_session", False)
            permission_handler = build_permission_handler(
                bot=context.bot, chat_id=update.effective_chat.id, settings=settings
            )

            # Process with Claude
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

                claude_response = await claude_integration.run_command(
                    prompt=processed_image.prompt,
                    working_directory=current_dir,
                    user_id=user_id,
                    session_id=session_id,
                    force_new_session=force_new_session,
                    permission_handler=permission_handler,
                    model=context.user_data.get("claude_model"),
                    images=images,
                )

                # Update session ID
                context.user_data["claude_session_id"] = claude_response.session_id

                # Format and send response
                from ..utils.formatting import ResponseFormatter

                formatter = ResponseFormatter(settings)
                formatted_messages = formatter.format_claude_response(
                    claude_response.content
                )

                # Delete progress message
                await claude_progress_msg.delete()

                # Send responses
                for i, message in enumerate(formatted_messages):
                    await update.message.reply_text(
                        message.text,
                        parse_mode=message.parse_mode,
                        reply_markup=message.reply_markup,
                        reply_to_message_id=(
                            update.message.message_id if i == 0 else None
                        ),
                    )

                    if i < len(formatted_messages) - 1:
                        await asyncio.sleep(0.5)

            except Exception as e:
                error_text = _format_error_message(str(e))
                try:
                    await claude_progress_msg.edit_text(
                        error_text, parse_mode="Markdown"
                    )
                except Exception as send_error:
                    logger.warning(
                        "Failed to edit image progress message with error",
                        error=str(send_error),
                        original_error=str(e),
                        user_id=user_id,
                    )
                    await update.message.reply_text(
                        error_text,
                        parse_mode="Markdown",
                        reply_to_message_id=update.message.message_id,
                    )
                logger.error(
                    "Claude image processing failed", error=str(e), user_id=user_id
                )

        except Exception as e:
            logger.error("Image processing failed", error=str(e), user_id=user_id)
            await update.message.reply_text(
                _format_error_message(str(e)), parse_mode="Markdown"
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
            f"• Manage sessions (`/new`, `/status`)\n\n"
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
    claude_response, context, settings, user_id
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
    current_dir = context.user_data.get(
        "current_directory", settings.approved_directory
    )

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
                    context.user_data["current_directory"] = new_path
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

    parts = []
    if tool_name in ("Write", "Edit", "Read") and "file_path" in tool_input:
        parts.append(f"File: `{tool_input['file_path']}`")
    elif tool_name == "Bash" and "command" in tool_input:
        cmd = tool_input["command"]
        if len(cmd) > 120:
            cmd = cmd[:120] + "..."
        parts.append(f"Command: `{cmd}`")
    elif tool_name == "WebFetch" and "url" in tool_input:
        parts.append(f"URL: `{tool_input['url']}`")
    else:
        # Generic: show first key-value pair
        for key, value in list(tool_input.items())[:2]:
            val_str = str(value)
            if len(val_str) > 80:
                val_str = val_str[:80] + "..."
            parts.append(f"{key}: `{val_str}`")

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
                f"Claude wants to use: `{tool_name}`\n"
                f"{input_summary}\n\n"
                f"Allow this action?"
            ),
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )

    return send_permission_buttons
