"""Handle inline keyboard callbacks."""

from pathlib import Path

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ...claude.facade import ClaudeIntegration
from ...claude.task_registry import TaskRegistry
from ...config.settings import Settings
from ...security.audit import AuditLogger
from ...security.validators import SecurityValidator
from ...services import ApprovalService
from ...services.session_interaction_service import SessionInteractionService
from ...services.session_lifecycle_service import SessionLifecycleService
from ...services.session_service import SessionService
from ..features.session_export import ExportFormat
from ..utils.resume_ui import build_resume_project_selector
from ..utils.scope_state import get_scope_state_from_query
from ..utils.ui_adapter import build_reply_markup_from_spec
from .message import build_permission_handler

logger = structlog.get_logger()


def _get_scope_state_for_query(
    query, context: ContextTypes.DEFAULT_TYPE
) -> tuple[str, dict]:
    """Get per-chat/topic scoped state for callback handlers."""
    settings: Settings | None = context.bot_data.get("settings")
    default_directory = settings.approved_directory if settings else Path(".").resolve()
    return get_scope_state_from_query(
        user_data=context.user_data,
        query=query,
        default_directory=default_directory,
    )


def _parse_export_format(export_format: str) -> ExportFormat | None:
    """Parse callback export format string to enum."""
    if not export_format:
        return None

    raw = export_format.strip().lower()
    format_map = {
        ExportFormat.MARKDOWN.value: ExportFormat.MARKDOWN,
        ExportFormat.HTML.value: ExportFormat.HTML,
        ExportFormat.JSON.value: ExportFormat.JSON,
    }
    return format_map.get(raw)


async def handle_callback_query(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Route callback queries to appropriate handlers."""
    query = update.callback_query

    user_id = query.from_user.id
    data = query.data

    logger.info("Processing callback query", user_id=user_id, callback_data=data)

    try:
        # Parse callback data
        if ":" in data:
            action, param = data.split(":", 1)
        else:
            action, param = data, None

        # Handle cancel callback before the generic answer() call,
        # because cancel needs its own answer text.
        if action == "cancel" and param == "task":
            task_registry: TaskRegistry = context.bot_data.get("task_registry")
            if not task_registry:
                await query.answer("Task registry not available.")
                return
            scope_key, _ = _get_scope_state_for_query(query, context)
            cancelled = await task_registry.cancel(user_id, scope_key=scope_key)
            if cancelled:
                await query.answer("Task cancellation requested.")
            else:
                await query.answer("No active task to cancel.")
            audit_logger: AuditLogger = context.bot_data.get("audit_logger")
            if audit_logger:
                await audit_logger.log_command(
                    user_id=user_id, command="cancel_button", args=[], success=cancelled
                )
            return

        # Acknowledge the callback for all other actions
        await query.answer()

        # Route to appropriate handler
        handlers = {
            "cd": handle_cd_callback,
            "action": handle_action_callback,
            "confirm": handle_confirm_callback,
            "quick": handle_quick_action_callback,
            "followup": handle_followup_callback,
            "conversation": handle_conversation_callback,
            "git": handle_git_callback,
            "export": handle_export_callback,
            "permission": handle_permission_callback,
            "thinking": handle_thinking_callback,
            "resume": handle_resume_callback,
            "model": handle_model_callback,
        }

        handler = handlers.get(action)
        if handler:
            await handler(query, param, context)
        else:
            await query.edit_message_text(
                "❌ **Unknown Action**\n\n"
                "This button action is not recognized. "
                "The bot may have been updated since this message was sent."
            )

    except Exception as e:
        logger.error(
            "Error handling callback query",
            error=str(e),
            user_id=user_id,
            callback_data=data,
        )

        try:
            await query.edit_message_text(
                "❌ **Error Processing Action**\n\n"
                "An error occurred while processing your request.\n"
                "Please try again or use text commands."
            )
        except Exception:
            # If we can't edit the message, send a new one
            await query.message.reply_text(
                "❌ **Error Processing Action**\n\n"
                "An error occurred while processing your request."
            )


async def handle_cd_callback(
    query, project_name: str, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle directory change from inline keyboard."""
    user_id = query.from_user.id
    settings: Settings = context.bot_data["settings"]
    security_validator: SecurityValidator = context.bot_data.get("security_validator")
    audit_logger: AuditLogger = context.bot_data.get("audit_logger")
    _, scope_state = _get_scope_state_for_query(query, context)

    try:
        current_dir = scope_state.get("current_directory", settings.approved_directory)

        # Handle special paths
        if project_name == "/":
            new_path = settings.approved_directory
        elif project_name == "..":
            new_path = current_dir.parent
            # Ensure we don't go above approved directory
            if not str(new_path).startswith(str(settings.approved_directory)):
                new_path = settings.approved_directory
        else:
            new_path = settings.approved_directory / project_name

        # Validate path if security validator is available
        if security_validator:
            # Pass the absolute path for validation
            valid, resolved_path, error = security_validator.validate_path(
                str(new_path), settings.approved_directory
            )
            if not valid:
                await query.edit_message_text(f"❌ **Access Denied**\n\n{error}")
                return
            # Use the validated path
            new_path = resolved_path

        # Check if directory exists
        if not new_path.exists() or not new_path.is_dir():
            await query.edit_message_text(
                f"❌ **Directory Not Found**\n\n"
                f"The directory `{project_name}` no longer exists or is not accessible."
            )
            return

        # Update directory and clear session
        old_session_id = scope_state.get("claude_session_id")
        scope_state["current_directory"] = new_path
        scope_state["claude_session_id"] = None
        scope_state["force_new_session"] = True
        if old_session_id:
            permission_manager = context.bot_data.get("permission_manager")
            if permission_manager:
                permission_manager.clear_session(old_session_id)

        # Send confirmation with new directory info
        relative_path = new_path.relative_to(settings.approved_directory)

        # Add navigation buttons
        keyboard = [
            [
                InlineKeyboardButton("📁 List Files", callback_data="action:ls"),
                InlineKeyboardButton(
                    "🆕 New Session", callback_data="action:new_session"
                ),
            ],
            [
                InlineKeyboardButton(
                    "📋 Projects", callback_data="action:show_projects"
                ),
                InlineKeyboardButton("📊 Context", callback_data="action:context"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            f"✅ **Directory Changed**\n\n"
            f"📂 Current directory: `{relative_path}/`\n\n"
            f"🔄 Claude session cleared. You can now start coding in this directory!",
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )

        # Log successful directory change
        if audit_logger:
            await audit_logger.log_command(
                user_id=user_id, command="cd", args=[project_name], success=True
            )

    except Exception as e:
        await query.edit_message_text(f"❌ **Error changing directory**\n\n{str(e)}")

        if audit_logger:
            await audit_logger.log_command(
                user_id=user_id, command="cd", args=[project_name], success=False
            )


async def handle_action_callback(
    query, action_type: str, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle general action callbacks."""
    actions = {
        "help": _handle_help_action,
        "show_projects": _handle_show_projects_action,
        "new_session": _handle_new_session_action,
        "continue": _handle_continue_action,
        "end_session": _handle_end_session_action,
        "context": _handle_status_action,
        "refresh_context": _handle_refresh_status_action,
        # Backward compatibility for older callback buttons in history.
        "status": _handle_status_action,
        "ls": _handle_ls_action,
        "start_coding": _handle_start_coding_action,
        "quick_actions": _handle_quick_actions_action,
        "refresh_status": _handle_refresh_status_action,
        "refresh_ls": _handle_refresh_ls_action,
        "export": _handle_export_action,
    }

    handler = actions.get(action_type)
    if handler:
        await handler(query, context)
    else:
        await query.edit_message_text(
            f"❌ **Unknown Action: {action_type}**\n\n"
            "This action is not implemented yet."
        )


async def handle_confirm_callback(
    query, confirmation_type: str, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle confirmation dialogs."""
    if confirmation_type == "yes":
        await query.edit_message_text("✅ **Confirmed**\n\nAction will be processed.")
    elif confirmation_type == "no":
        await query.edit_message_text("❌ **Cancelled**\n\nAction was cancelled.")
    else:
        await query.edit_message_text("❓ **Unknown confirmation response**")


# Action handlers


async def _handle_help_action(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle help action."""
    help_text = (
        "🤖 **Quick Help**\n\n"
        "**Navigation:**\n"
        "• `/ls` - List files\n"
        "• `/cd <dir>` - Change directory\n"
        "• `/projects` - Show projects\n\n"
        "**Sessions:**\n"
        "• `/new` - New Claude session\n"
        "• `/context` - Session context\n\n"
        "**Tips:**\n"
        "• Send any text to interact with Claude\n"
        "• Upload files for code review\n"
        "• Use buttons for quick actions\n\n"
        "Use `/help` for detailed help."
    )

    keyboard = [
        [
            InlineKeyboardButton("📖 Full Help", callback_data="action:full_help"),
            InlineKeyboardButton("🏠 Main Menu", callback_data="action:main_menu"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        help_text, parse_mode="Markdown", reply_markup=reply_markup
    )


async def _handle_show_projects_action(
    query, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle show projects action."""
    settings: Settings = context.bot_data["settings"]

    try:
        # Get directories in approved directory
        projects = []
        for item in sorted(settings.approved_directory.iterdir()):
            if item.is_dir() and not item.name.startswith("."):
                projects.append(item.name)

        if not projects:
            await query.edit_message_text(
                "📁 **No Projects Found**\n\n"
                "No subdirectories found in your approved directory.\n"
                "Create some directories to organize your projects!"
            )
            return

        # Create project buttons
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
                InlineKeyboardButton("🏠 Root", callback_data="cd:/"),
                InlineKeyboardButton(
                    "🔄 Refresh", callback_data="action:show_projects"
                ),
            ]
        )

        reply_markup = InlineKeyboardMarkup(keyboard)
        project_list = "\n".join([f"• `{project}/`" for project in projects])

        await query.edit_message_text(
            f"📁 **Available Projects**\n\n"
            f"{project_list}\n\n"
            f"Click a project to navigate to it:",
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )

    except Exception as e:
        await query.edit_message_text(f"❌ Error loading projects: {str(e)}")


async def _handle_new_session_action(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle new session action."""
    settings: Settings = context.bot_data["settings"]
    _, scope_state = _get_scope_state_for_query(query, context)
    session_lifecycle = context.bot_data.get("session_lifecycle_service") or (
        SessionLifecycleService(
            permission_manager=context.bot_data.get("permission_manager")
        )
    )
    session_interaction = (
        context.bot_data.get("session_interaction_service")
        or SessionInteractionService()
    )
    reset_result = session_lifecycle.start_new_session(scope_state)
    current_dir = scope_state.get("current_directory", settings.approved_directory)
    session_message = session_interaction.build_new_session_message(
        current_dir=current_dir,
        approved_directory=settings.approved_directory,
        previous_session_id=reset_result.old_session_id,
        for_callback=True,
    )

    await query.edit_message_text(
        session_message.text,
        parse_mode="Markdown",
        reply_markup=build_reply_markup_from_spec(session_message.keyboard),
    )


async def _handle_end_session_action(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle end session action."""
    settings: Settings = context.bot_data["settings"]
    _, scope_state = _get_scope_state_for_query(query, context)
    session_lifecycle = context.bot_data.get("session_lifecycle_service") or (
        SessionLifecycleService(
            permission_manager=context.bot_data.get("permission_manager")
        )
    )
    session_interaction = (
        context.bot_data.get("session_interaction_service")
        or SessionInteractionService()
    )
    end_result = session_lifecycle.end_session(scope_state)

    if not end_result.had_active_session:
        no_active_message = session_interaction.build_end_no_active_message(
            for_callback=True
        )
        await query.edit_message_text(
            no_active_message.text,
            reply_markup=build_reply_markup_from_spec(no_active_message.keyboard),
        )
        return

    # Get current directory for display
    current_dir = scope_state.get("current_directory", settings.approved_directory)
    end_message = session_interaction.build_end_success_message(
        current_dir=current_dir,
        approved_directory=settings.approved_directory,
        for_callback=True,
        title="Session Ended",
    )

    await query.edit_message_text(
        end_message.text,
        parse_mode="Markdown",
        reply_markup=build_reply_markup_from_spec(end_message.keyboard),
    )


async def _handle_continue_action(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle continue session action."""
    user_id = query.from_user.id
    settings: Settings = context.bot_data["settings"]
    claude_integration: ClaudeIntegration = context.bot_data.get("claude_integration")
    _, scope_state = _get_scope_state_for_query(query, context)
    session_lifecycle = context.bot_data.get("session_lifecycle_service") or (
        SessionLifecycleService(
            permission_manager=context.bot_data.get("permission_manager")
        )
    )
    session_interaction = (
        context.bot_data.get("session_interaction_service")
        or SessionInteractionService()
    )
    current_dir = scope_state.get("current_directory", settings.approved_directory)

    try:
        if not claude_integration:
            await query.edit_message_text(
                session_interaction.get_integration_unavailable_text()
            )
            return

        # Check if there's an existing session in user context
        claude_session_id = session_lifecycle.get_active_session_id(scope_state)
        permission_handler = build_permission_handler(
            bot=context.bot,
            chat_id=query.message.chat_id,
            settings=settings,
        )

        progress_text = session_interaction.build_continue_progress_text(
            existing_session_id=claude_session_id,
            current_dir=current_dir,
            approved_directory=settings.approved_directory,
            prompt=None,
        )
        await query.edit_message_text(progress_text, parse_mode="Markdown")

        continue_result = await session_lifecycle.continue_session(
            user_id=user_id,
            scope_state=scope_state,
            current_dir=current_dir,
            claude_integration=claude_integration,
            prompt=None,
            default_prompt="Please continue where we left off",
            permission_handler=permission_handler,
            use_empty_prompt_when_existing=True,
            allow_none_prompt_when_discover=True,
        )
        claude_response = continue_result.response

        if continue_result.status == "continued" and claude_response:

            # Send Claude's response
            await query.message.reply_text(
                session_interaction.build_continue_callback_success_text(
                    claude_response.content
                ),
                parse_mode="Markdown",
            )
        elif continue_result.status == "not_found":
            # No session found to continue
            not_found_message = session_interaction.build_continue_not_found_message(
                current_dir=current_dir,
                approved_directory=settings.approved_directory,
                for_callback=True,
            )
            await query.edit_message_text(
                not_found_message.text,
                parse_mode="Markdown",
                reply_markup=build_reply_markup_from_spec(not_found_message.keyboard),
            )
        else:
            await query.edit_message_text(
                session_interaction.get_integration_unavailable_text()
            )

    except Exception as e:
        logger.error("Error in continue action", error=str(e), user_id=user_id)
        error_message = session_interaction.build_continue_callback_error_message(
            str(e)
        )
        await query.edit_message_text(
            error_message.text,
            parse_mode="Markdown",
            reply_markup=build_reply_markup_from_spec(error_message.keyboard),
        )


async def _handle_status_action(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle status action - synced with /context command logic."""
    settings: Settings = context.bot_data["settings"]
    user_id = int(getattr(getattr(query, "from_user", None), "id", 0) or 0)
    _, scope_state = _get_scope_state_for_query(query, context)
    session_interaction = (
        context.bot_data.get("session_interaction_service")
        or SessionInteractionService()
    )
    view_spec = session_interaction.build_context_view_spec(for_callback=True)
    loading_kwargs = {}
    if view_spec.loading_parse_mode:
        loading_kwargs["parse_mode"] = view_spec.loading_parse_mode
    await query.edit_message_text(
        view_spec.loading_text,
        **loading_kwargs,
    )

    try:
        claude_integration: ClaudeIntegration = context.bot_data.get(
            "claude_integration"
        )
        session_service = context.bot_data.get("session_service")
        snapshot = await SessionService.build_scope_context_snapshot(
            user_id=user_id,
            scope_state=scope_state,
            approved_directory=settings.approved_directory,
            claude_integration=claude_integration,
            session_service=session_service,
            include_resumable=view_spec.include_resumable,
            include_event_summary=view_spec.include_event_summary,
        )
        render_result = session_interaction.build_context_render_result(
            snapshot=snapshot,
            scope_state=scope_state,
            approved_directory=settings.approved_directory,
            full_mode=False,
        )
        await query.edit_message_text(
            render_result.primary_text,
            parse_mode=render_result.parse_mode,
        )
    except Exception as exc:
        logger.error("Error in context callback", error=str(exc), user_id=user_id)
        await query.edit_message_text(view_spec.error_text)


async def handle_model_callback(
    query, param: str, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle model selection callback from inline keyboard."""
    _, scope_state = _get_scope_state_for_query(query, context)
    if param == "default":
        scope_state.pop("claude_model", None)
        selected = "default"
    else:
        scope_state["claude_model"] = param
        selected = param

    # Rebuild keyboard with updated selection indicator
    current = scope_state.get("claude_model")
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

    await query.edit_message_text(
        f"Model switched to `{selected}`.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _handle_ls_action(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ls action."""
    settings: Settings = context.bot_data["settings"]
    _, scope_state = _get_scope_state_for_query(query, context)
    current_dir = scope_state.get("current_directory", settings.approved_directory)

    try:
        # List directory contents (similar to /ls command)
        items = []
        directories = []
        files = []

        for item in sorted(current_dir.iterdir()):
            if item.name.startswith("."):
                continue

            # Escape markdown special characters in filenames
            safe_name = _escape_markdown(item.name)

            if item.is_dir():
                directories.append(f"📁 {safe_name}/")
            else:
                try:
                    size = item.stat().st_size
                    size_str = _format_file_size(size)
                    files.append(f"📄 {safe_name} ({size_str})")
                except OSError:
                    files.append(f"📄 {safe_name}")

        items = directories + files
        relative_path = current_dir.relative_to(settings.approved_directory)

        if not items:
            message = f"📂 `{relative_path}/`\n\n_(empty directory)_"
        else:
            message = f"📂 `{relative_path}/`\n\n"
            max_items = 30  # Limit for inline display
            if len(items) > max_items:
                shown_items = items[:max_items]
                message += "\n".join(shown_items)
                message += f"\n\n_... and {len(items) - max_items} more items_"
            else:
                message += "\n".join(items)

        # Add buttons
        keyboard = []
        if current_dir != settings.approved_directory:
            keyboard.append(
                [
                    InlineKeyboardButton("⬆️ Go Up", callback_data="cd:.."),
                    InlineKeyboardButton("🏠 Root", callback_data="cd:/"),
                ]
            )

        keyboard.append(
            [
                InlineKeyboardButton("🔄 Refresh", callback_data="action:refresh_ls"),
                InlineKeyboardButton(
                    "📋 Projects", callback_data="action:show_projects"
                ),
            ]
        )

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            message, parse_mode="Markdown", reply_markup=reply_markup
        )

    except Exception as e:
        await query.edit_message_text(f"❌ Error listing directory: {str(e)}")


async def _handle_start_coding_action(
    query, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle start coding action."""
    await query.edit_message_text(
        "🚀 **Ready to Code!**\n\n"
        "Send me any message to start coding with Claude:\n\n"
        "**Examples:**\n"
        '• _"Create a Python script that..."_\n'
        '• _"Help me debug this code..."_\n'
        '• _"Explain how this file works..."_\n'
        "• Upload a file for review\n\n"
        "I'm here to help with all your coding needs!"
    )


async def _handle_quick_actions_action(
    query, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle quick actions menu."""
    keyboard = [
        [
            InlineKeyboardButton("🧪 Run Tests", callback_data="quick:test"),
            InlineKeyboardButton("📦 Install Deps", callback_data="quick:install"),
        ],
        [
            InlineKeyboardButton("🎨 Format Code", callback_data="quick:format"),
            InlineKeyboardButton("🔍 Find TODOs", callback_data="quick:find_todos"),
        ],
        [
            InlineKeyboardButton("🔨 Build", callback_data="quick:build"),
            InlineKeyboardButton("🚀 Start Server", callback_data="quick:start"),
        ],
        [
            InlineKeyboardButton("📊 Git Status", callback_data="quick:git_status"),
            InlineKeyboardButton("🔧 Lint Code", callback_data="quick:lint"),
        ],
        [InlineKeyboardButton("⬅️ Back", callback_data="action:new_session")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "🛠️ **Quick Actions**\n\n"
        "Choose a common development task:\n\n"
        "_Note: These will be fully functional once Claude Code integration is complete._",
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )


async def _handle_refresh_status_action(
    query, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle refresh status action."""
    await _handle_status_action(query, context)


async def _handle_refresh_ls_action(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle refresh ls action."""
    await _handle_ls_action(query, context)


async def _handle_export_action(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle export action."""
    _, scope_state = _get_scope_state_for_query(query, context)
    session_lifecycle = context.bot_data.get("session_lifecycle_service") or (
        SessionLifecycleService(
            permission_manager=context.bot_data.get("permission_manager")
        )
    )
    session_interaction = (
        context.bot_data.get("session_interaction_service")
        or SessionInteractionService()
    )
    features = context.bot_data.get("features")
    session_exporter = features.get_session_export() if features else None

    if not session_exporter:
        await query.edit_message_text(
            session_interaction.build_export_unavailable_text(for_callback=True),
            parse_mode="Markdown",
        )
        return

    claude_session_id = session_lifecycle.get_active_session_id(scope_state)
    if not claude_session_id:
        await query.edit_message_text(
            session_interaction.build_export_no_active_session_text(),
            parse_mode="Markdown",
        )
        return

    export_selector = session_interaction.build_export_selector_message(
        claude_session_id
    )

    await query.edit_message_text(
        export_selector.text,
        parse_mode="Markdown",
        reply_markup=build_reply_markup_from_spec(export_selector.keyboard),
    )


async def handle_quick_action_callback(
    query, action_id: str, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle quick action callbacks."""
    user_id = query.from_user.id

    # Get quick actions manager from bot data if available
    quick_actions = context.bot_data.get("quick_actions")

    if not quick_actions:
        await query.edit_message_text(
            "❌ **Quick Actions Not Available**\n\n"
            "Quick actions feature is not available."
        )
        return

    # Get Claude integration
    claude_integration: ClaudeIntegration = context.bot_data.get("claude_integration")
    if not claude_integration:
        await query.edit_message_text(
            "❌ **Claude Integration Not Available**\n\n"
            "Claude integration is not properly configured."
        )
        return

    settings: Settings = context.bot_data["settings"]
    _, scope_state = _get_scope_state_for_query(query, context)
    current_dir = scope_state.get("current_directory", settings.approved_directory)

    try:
        # Get the action from the manager
        action = quick_actions.actions.get(action_id)
        if not action:
            await query.edit_message_text(
                f"❌ **Action Not Found**\n\n"
                f"Quick action '{action_id}' is not available."
            )
            return

        # Execute the action
        await query.edit_message_text(
            f"🚀 **Executing {action.icon} {action.name}**\n\n"
            f"Running quick action in directory: `{current_dir.relative_to(settings.approved_directory)}/`\n\n"
            f"Please wait...",
            parse_mode="Markdown",
        )

        # Run the action through Claude, using scoped session to prevent
        # cross-topic leakage via facade auto-resume.
        session_id = scope_state.get("claude_session_id")
        force_new = scope_state.get("force_new_session", False)
        claude_response = await claude_integration.run_command(
            prompt=action.prompt,
            working_directory=current_dir,
            user_id=user_id,
            session_id=session_id,
            force_new_session=force_new,
            permission_handler=build_permission_handler(
                bot=context.bot, chat_id=query.message.chat_id, settings=settings
            ),
        )

        if claude_response:
            # Write back session_id and consume flag only on success
            scope_state["claude_session_id"] = claude_response.session_id
            scope_state.pop("force_new_session", None)
            # Format and send the response
            response_text = claude_response.content
            if len(response_text) > 4000:
                response_text = response_text[:4000] + "...\n\n_(Response truncated)_"

            await query.message.reply_text(
                f"✅ **{action.icon} {action.name} Complete**\n\n{response_text}",
                parse_mode="Markdown",
            )
        else:
            await query.edit_message_text(
                f"❌ **Action Failed**\n\n"
                f"Failed to execute {action.name}. Please try again."
            )

    except Exception as e:
        logger.error("Quick action execution failed", error=str(e), user_id=user_id)
        await query.edit_message_text(
            f"❌ **Action Error**\n\n"
            f"An error occurred while executing {action_id}: {str(e)}"
        )


async def handle_followup_callback(
    query, suggestion_hash: str, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle follow-up suggestion callbacks."""
    user_id = query.from_user.id

    # Get conversation enhancer from bot data if available
    conversation_enhancer = context.bot_data.get("conversation_enhancer")

    if not conversation_enhancer:
        await query.edit_message_text(
            "❌ **Follow-up Not Available**\n\n"
            "Conversation enhancement features are not available."
        )
        return

    try:
        # Get stored suggestions (this would need to be implemented in the enhancer)
        # For now, we'll provide a generic response
        await query.edit_message_text(
            "💡 **Follow-up Suggestion Selected**\n\n"
            "This follow-up suggestion will be implemented once the conversation "
            "enhancement system is fully integrated with the message handler.\n\n"
            "**Current Status:**\n"
            "• Suggestion received ✅\n"
            "• Integration pending 🔄\n\n"
            "_You can continue the conversation by sending a new message._"
        )

        logger.info(
            "Follow-up suggestion selected",
            user_id=user_id,
            suggestion_hash=suggestion_hash,
        )

    except Exception as e:
        logger.error(
            "Error handling follow-up callback",
            error=str(e),
            user_id=user_id,
            suggestion_hash=suggestion_hash,
        )

        await query.edit_message_text(
            "❌ **Error Processing Follow-up**\n\n"
            "An error occurred while processing your follow-up suggestion."
        )


async def handle_conversation_callback(
    query, action_type: str, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle conversation control callbacks."""
    user_id = query.from_user.id
    settings: Settings = context.bot_data["settings"]
    _, scope_state = _get_scope_state_for_query(query, context)

    if action_type == "continue":
        # Remove suggestion buttons and show continue message
        await query.edit_message_text(
            "✅ **Continuing Conversation**\n\n"
            "Send me your next message to continue coding!\n\n"
            "I'm ready to help with:\n"
            "• Code review and debugging\n"
            "• Feature implementation\n"
            "• Architecture decisions\n"
            "• Testing and optimization\n"
            "• Documentation\n\n"
            "_Just type your request or upload files._"
        )

    elif action_type == "end":
        # End the current session
        conversation_enhancer = context.bot_data.get("conversation_enhancer")
        if conversation_enhancer:
            conversation_enhancer.clear_context(user_id)

        session_lifecycle = context.bot_data.get("session_lifecycle_service") or (
            SessionLifecycleService(
                permission_manager=context.bot_data.get("permission_manager")
            )
        )
        session_interaction = (
            context.bot_data.get("session_interaction_service")
            or SessionInteractionService()
        )
        session_lifecycle.end_session(scope_state)

        current_dir = scope_state.get("current_directory", settings.approved_directory)
        end_message = session_interaction.build_end_success_message(
            current_dir=current_dir,
            approved_directory=settings.approved_directory,
            for_callback=True,
            title="Conversation Ended",
        )

        await query.edit_message_text(
            end_message.text,
            parse_mode="Markdown",
            reply_markup=build_reply_markup_from_spec(end_message.keyboard),
        )

        logger.info("Conversation ended via callback", user_id=user_id)

    else:
        await query.edit_message_text(
            f"❌ **Unknown Conversation Action: {action_type}**\n\n"
            "This conversation action is not recognized."
        )


async def handle_git_callback(
    query, git_action: str, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle git-related callbacks."""
    user_id = query.from_user.id
    settings: Settings = context.bot_data["settings"]
    _, scope_state = _get_scope_state_for_query(query, context)
    features = context.bot_data.get("features")

    if not features or not features.is_enabled("git"):
        await query.edit_message_text(
            "❌ **Git Integration Disabled**\n\n"
            "Git integration feature is not enabled."
        )
        return

    current_dir = scope_state.get("current_directory", settings.approved_directory)

    try:
        git_integration = features.get_git_integration()
        if not git_integration:
            await query.edit_message_text(
                "❌ **Git Integration Unavailable**\n\n"
                "Git integration service is not available."
            )
            return

        if git_action == "status":
            # Refresh git status
            git_status = await git_integration.get_status(current_dir)
            status_message = git_integration.format_status(git_status)

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

            await query.edit_message_text(
                status_message, parse_mode="Markdown", reply_markup=reply_markup
            )

        elif git_action == "diff":
            # Show git diff
            diff_output = await git_integration.get_diff(current_dir)

            if not diff_output.strip():
                diff_message = "📊 **Git Diff**\n\n_No changes to show._"
            else:
                # Clean up diff output for Telegram
                # Remove emoji symbols that interfere with markdown parsing
                clean_diff = (
                    diff_output.replace("➕", "+").replace("➖", "-").replace("📍", "@")
                )

                # Limit diff output
                max_length = 2000
                if len(clean_diff) > max_length:
                    clean_diff = (
                        clean_diff[:max_length] + "\n\n_... output truncated ..._"
                    )

                diff_message = f"📊 **Git Diff**\n\n```\n{clean_diff}\n```"

            keyboard = [
                [
                    InlineKeyboardButton("📜 Show Log", callback_data="git:log"),
                    InlineKeyboardButton("📊 Status", callback_data="git:status"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                diff_message, parse_mode="Markdown", reply_markup=reply_markup
            )

        elif git_action == "log":
            # Show git log
            commits = await git_integration.get_file_history(current_dir, ".")

            if not commits:
                log_message = "📜 **Git Log**\n\n_No commits found._"
            else:
                log_message = "📜 **Git Log**\n\n"
                for commit in commits[:10]:  # Show last 10 commits
                    short_hash = commit.hash[:7]
                    short_message = commit.message[:60]
                    if len(commit.message) > 60:
                        short_message += "..."
                    log_message += f"• `{short_hash}` {short_message}\n"

            keyboard = [
                [
                    InlineKeyboardButton("📊 Show Diff", callback_data="git:diff"),
                    InlineKeyboardButton("📊 Status", callback_data="git:status"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                log_message, parse_mode="Markdown", reply_markup=reply_markup
            )

        else:
            await query.edit_message_text(
                f"❌ **Unknown Git Action: {git_action}**\n\n"
                "This git action is not recognized."
            )

    except Exception as e:
        logger.error(
            "Error in git callback",
            error=str(e),
            git_action=git_action,
            user_id=user_id,
        )
        await query.edit_message_text(f"❌ **Git Error**\n\n{str(e)}")


async def handle_export_callback(
    query, export_format: str, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle export format selection callbacks."""
    user_id = query.from_user.id
    _, scope_state = _get_scope_state_for_query(query, context)
    features = context.bot_data.get("features")

    if export_format == "cancel":
        await query.edit_message_text(
            "📤 **Export Cancelled**\n\n" "Session export has been cancelled."
        )
        return

    parsed_format = _parse_export_format(export_format)
    if not parsed_format:
        await query.edit_message_text(
            "❌ **Invalid Export Format**\n\n"
            f"Unsupported export format: `{export_format}`",
            parse_mode="Markdown",
        )
        return

    session_exporter = features.get_session_export() if features else None
    if not session_exporter:
        await query.edit_message_text(
            "❌ **Export Unavailable**\n\n" "Session export service is not available."
        )
        return

    # Get current session
    claude_session_id = scope_state.get("claude_session_id")
    if not claude_session_id:
        await query.edit_message_text(
            "❌ **No Active Session**\n\n" "There's no active session to export."
        )
        return

    try:
        # Show processing message
        await query.edit_message_text(
            f"📤 **Exporting Session**\n\n"
            f"Generating {parsed_format.value.upper()} export...",
            parse_mode="Markdown",
        )

        # Export session
        exported_session = await session_exporter.export_session(
            user_id=user_id,
            session_id=claude_session_id,
            format=parsed_format,
        )

        # Send the exported file
        from io import BytesIO

        file_bytes = BytesIO(exported_session.content.encode("utf-8"))
        file_bytes.name = exported_session.filename

        await query.message.reply_document(
            document=file_bytes,
            filename=exported_session.filename,
            caption=(
                f"📤 **Session Export Complete**\n\n"
                f"Format: {exported_session.format.value.upper()}\n"
                f"Size: {exported_session.size_bytes:,} bytes\n"
                f"Created: {exported_session.created_at.strftime('%Y-%m-%d %H:%M:%S')}"
            ),
            parse_mode="Markdown",
        )

        # Update the original message
        await query.edit_message_text(
            f"✅ **Export Complete**\n\n"
            f"Your session has been exported as {exported_session.filename}.\n"
            f"Check the file above for your complete conversation history.",
            parse_mode="Markdown",
        )

    except Exception as e:
        logger.error(
            "Export failed", error=str(e), user_id=user_id, format=export_format
        )
        await query.edit_message_text(f"❌ **Export Failed**\n\n{str(e)}")


async def handle_permission_callback(
    query, param: str, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle tool permission button callbacks."""
    user_id = query.from_user.id
    approval_service = context.bot_data.get("approval_service") or ApprovalService()
    permission_manager = context.bot_data.get("permission_manager")
    result = approval_service.resolve_callback(
        param=param,
        user_id=user_id,
        permission_manager=permission_manager,
    )

    await query.edit_message_text(
        result.message,
        parse_mode=result.parse_mode,
    )

    if not result.ok:
        return

    logger.info(
        "Permission callback handled",
        user_id=user_id,
        request_id=result.request_id,
        decision=result.decision,
    )


async def handle_thinking_callback(
    query, param: str, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle thinking expand/collapse callbacks."""
    if not param or ":" not in param:
        await query.edit_message_text("Invalid thinking callback data.")
        return

    action, message_id = param.split(":", 1)
    cache_key = f"thinking:{message_id}"
    cached = context.user_data.get(cache_key)

    if not cached:
        await query.edit_message_text(
            "Thinking process cache has expired and cannot be expanded."
        )
        return

    if action == "expand":
        full_text = "\n".join(cached["lines"])

        # Truncate if exceeds Telegram limit
        if len(full_text) > 3800:
            full_text = _truncate_thinking(cached["lines"], max_chars=3800)

        collapse_keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Collapse",
                        callback_data=f"thinking:collapse:{message_id}",
                    )
                ]
            ]
        )
        try:
            await query.edit_message_text(
                full_text,
                parse_mode="Markdown",
                reply_markup=collapse_keyboard,
            )
        except Exception as e:
            logger.warning("Failed to expand thinking", error=str(e))
            await query.edit_message_text(
                "Failed to expand thinking process. Content may be too long."
            )

    elif action == "collapse":
        expand_keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "View thinking process",
                        callback_data=f"thinking:expand:{message_id}",
                    )
                ]
            ]
        )
        await query.edit_message_text(
            cached["summary"],
            parse_mode="Markdown",
            reply_markup=expand_keyboard,
        )

    else:
        await query.edit_message_text("Unknown thinking action.")


def _truncate_thinking(lines: list[str], max_chars: int = 3800) -> str:
    """Keep recent progress lines from the end, total length under max_chars."""
    result = []
    total = 0
    for line in reversed(lines):
        if total + len(line) + 1 > max_chars - 50:
            break
        result.insert(0, line)
        total += len(line) + 1

    skipped = len(lines) - len(result)
    if skipped > 0:
        result.insert(0, f"... ({skipped} earlier entries omitted)")

    return "\n".join(result)


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


async def handle_resume_callback(query, param, context):
    """Handle resume:* callback queries.

    Callback data format: resume:<sub>:<token>
    Sub-actions:
    - p (project), s (session), f (force-confirm)
    - show_all, show_recent, cancel
    """
    user_id = query.from_user.id
    settings: Settings = context.bot_data["settings"]

    from ...bot.resume_tokens import ResumeTokenManager
    from ...claude.desktop_scanner import DesktopSessionScanner

    token_mgr: ResumeTokenManager = context.bot_data.get("resume_token_manager")
    scanner: DesktopSessionScanner = context.bot_data.get("desktop_scanner")

    if not token_mgr or not scanner:
        await query.edit_message_text("Session expired. Please run /resume again.")
        return

    # Handle non-token sub-actions first.
    if param in {"show_all", "show_recent"}:
        await _resume_render_project_list(
            query=query,
            user_id=user_id,
            scanner=scanner,
            token_mgr=token_mgr,
            settings=settings,
            context=context,
            show_all=(param == "show_all"),
        )
        return

    # Parse tokenized sub-action: "p:<token>" / "s:<token>" / "f:<token>"
    if not param or ":" not in param:
        if param == "cancel":
            await query.edit_message_text("Resume cancelled.")
            return
        await query.edit_message_text(
            "Invalid resume action. Please run /resume again."
        )
        return

    sub, token = param.split(":", 1)

    if sub == "p":
        await _resume_select_project(
            query,
            user_id,
            token,
            token_mgr,
            scanner,
            settings,
            context,
        )
    elif sub == "s":
        await _resume_select_session(
            query,
            user_id,
            token,
            token_mgr,
            scanner,
            settings,
            context,
        )
    elif sub == "f":
        await _resume_force_confirm(
            query,
            user_id,
            token,
            token_mgr,
            settings,
            context,
        )
    elif sub == "cancel":
        await query.edit_message_text("Resume cancelled.")
    else:
        await query.edit_message_text(
            "Unknown resume action. Please run /resume again."
        )


async def _resume_render_project_list(
    *,
    query,
    user_id: int,
    scanner,
    token_mgr,
    settings: Settings,
    context: ContextTypes.DEFAULT_TYPE,
    show_all: bool,
) -> None:
    """Render resume project selection in recent/all modes."""
    projects = await scanner.list_projects()

    if not projects:
        await query.edit_message_text(
            "No desktop Claude Code sessions found.\n\n"
            "Run /resume again after using Claude Code on desktop.",
            parse_mode="Markdown",
        )
        return

    _, scope_state = _get_scope_state_for_query(query, context)
    current_dir = scope_state.get("current_directory")
    message_text, keyboard = build_resume_project_selector(
        projects=projects,
        approved_root=settings.approved_directory,
        token_mgr=token_mgr,
        user_id=user_id,
        current_directory=current_dir,
        show_all=show_all,
    )
    await query.edit_message_text(
        message_text,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def _resume_select_project(
    query,
    user_id,
    token,
    token_mgr,
    scanner,
    settings,
    context,
):
    """S1: User selected a project, show its sessions."""
    payload = token_mgr.resolve(
        kind="p",
        user_id=user_id,
        token=token,
    )
    if payload is None:
        await query.edit_message_text(
            "Token expired or invalid. Please run /resume again."
        )
        return

    from pathlib import Path

    project_cwd = Path(payload["cwd"])
    candidates = await scanner.list_sessions(project_cwd=project_cwd)

    if not candidates:
        await query.edit_message_text(
            f"No sessions found for project:\n"
            f"`{project_cwd.name}`\n\n"
            f"Run /resume to try another project.",
            parse_mode="Markdown",
        )
        return

    # Build session selection buttons
    keyboard = []
    for c in candidates[:10]:  # limit to 10 sessions
        # Format label
        preview = c.first_message[:40] if c.first_message else "..."
        active_tag = " [ACTIVE]" if c.is_probably_active else ""
        sid_short = c.session_id[:8]
        label = f"{sid_short}{active_tag} {preview}"

        tok = token_mgr.issue(
            kind="s",
            user_id=user_id,
            payload={
                "cwd": str(project_cwd),
                "session_id": c.session_id,
                "is_active": c.is_probably_active,
            },
        )
        keyboard.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"resume:s:{tok}",
                )
            ]
        )

    keyboard.append(
        [
            InlineKeyboardButton(
                "❌ Cancel",
                callback_data="resume:cancel",
            )
        ]
    )

    try:
        rel = project_cwd.relative_to(settings.approved_directory)
    except ValueError:
        rel = project_cwd.name

    await query.edit_message_text(
        f"**Sessions in** `{rel}`\n\n" f"Select a session to resume:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _resume_select_session(
    query,
    user_id,
    token,
    token_mgr,
    scanner,
    settings,
    context,
):
    """S2: User selected a session. Adopt it or ask for force-confirm."""
    payload = token_mgr.resolve(
        kind="s",
        user_id=user_id,
        token=token,
    )
    if payload is None:
        await query.edit_message_text(
            "Token expired or invalid. Please run /resume again."
        )
        return

    from pathlib import Path

    project_cwd = Path(payload["cwd"])
    session_id = payload["session_id"]
    is_active = payload.get("is_active", False)

    # If session appears active, ask for confirmation
    if is_active:
        tok = token_mgr.issue(
            kind="f",
            user_id=user_id,
            payload={
                "cwd": str(project_cwd),
                "session_id": session_id,
            },
        )
        keyboard = [
            [
                InlineKeyboardButton(
                    "Yes, resume anyway",
                    callback_data=f"resume:f:{tok}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "Cancel",
                    callback_data="resume:cancel",
                ),
            ],
        ]
        await query.edit_message_text(
            f"**Session may be active**\n\n"
            f"Session `{session_id[:8]}...` was modified very recently "
            f"and might still be running on your desktop.\n\n"
            f"Resuming it here could cause conflicts.\n"
            f"Continue anyway?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # Not active -> adopt directly
    await _do_adopt_session(
        query,
        user_id,
        project_cwd,
        session_id,
        settings,
        context,
    )


async def _resume_force_confirm(
    query,
    user_id,
    token,
    token_mgr,
    settings,
    context,
):
    """S3: User confirmed force-resume of an active session."""
    payload = token_mgr.resolve(
        kind="f",
        user_id=user_id,
        token=token,
    )
    if payload is None:
        await query.edit_message_text(
            "Token expired or invalid. Please run /resume again."
        )
        return

    from pathlib import Path

    project_cwd = Path(payload["cwd"])
    session_id = payload["session_id"]

    await _do_adopt_session(
        query,
        user_id,
        project_cwd,
        session_id,
        settings,
        context,
    )


async def _do_adopt_session(
    query,
    user_id,
    project_cwd,
    session_id,
    settings,
    context,
):
    """S4: Actually adopt the session and switch cwd."""
    # Defensive: verify project_cwd is under approved_directory
    try:
        resolved = project_cwd.resolve()
        if not resolved.is_relative_to(settings.approved_directory.resolve()):
            await query.edit_message_text(
                "Path is outside the approved directory. Cannot adopt session."
            )
            return
        project_cwd = resolved
    except (OSError, ValueError):
        await query.edit_message_text("Invalid project path. Please run /resume again.")
        return

    claude_integration: ClaudeIntegration = context.bot_data.get("claude_integration")
    if not claude_integration or not claude_integration.session_manager:
        await query.edit_message_text(
            "Claude integration not available. Cannot adopt session."
        )
        return

    try:
        await query.edit_message_text(
            f"Adopting session `{session_id[:8]}...`\n" f"Please wait...",
            parse_mode="Markdown",
        )

        adopted = await claude_integration.session_manager.adopt_external_session(
            user_id=user_id,
            project_path=project_cwd,
            external_session_id=session_id,
        )

        # Switch user's working directory and session
        _, scope_state = _get_scope_state_for_query(query, context)
        scope_state["current_directory"] = project_cwd
        scope_state["claude_session_id"] = adopted.session_id

        try:
            rel = project_cwd.relative_to(settings.approved_directory)
        except ValueError:
            rel = project_cwd.name

        keyboard = [
            [
                InlineKeyboardButton(
                    "Start Coding",
                    callback_data="action:start_coding",
                ),
                InlineKeyboardButton(
                    "Context",
                    callback_data="action:context",
                ),
            ],
        ]

        await query.edit_message_text(
            f"**Session Resumed**\n\n"
            f"Session: `{adopted.session_id[:8]}...`\n"
            f"Directory: `{rel}/`\n\n"
            f"Send a message to continue where you left off.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

        audit_logger: AuditLogger = context.bot_data.get("audit_logger")
        if audit_logger:
            await audit_logger.log_command(
                user_id=user_id,
                command="resume",
                args=[session_id[:8]],
                success=True,
            )

        logger.info(
            "Desktop session adopted",
            user_id=user_id,
            session_id=session_id,
            project=str(project_cwd),
        )

    except Exception as e:
        logger.error(
            "Failed to adopt desktop session",
            error=str(e),
            user_id=user_id,
            session_id=session_id,
        )
        await query.edit_message_text(
            f"**Failed to Resume Session**\n\n"
            f"Error: `{str(e)}`\n\n"
            f"Please run /resume to try again.",
            parse_mode="Markdown",
        )
