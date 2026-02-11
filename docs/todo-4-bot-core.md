# TODO-4: Telegram Bot Core

## Objective
Build the core Telegram bot infrastructure with proper command handling, message routing, inline keyboards, and error management while maintaining clean architecture and extensibility.

## Bot Architecture

### Component Structure
```
Bot Core
├── Main Bot Class (Orchestrator)
├── Command Handlers
│   ├── Navigation Commands (/cd, /ls, /pwd)
│   ├── Session Commands (/new, /continue, /status)
│   ├── Utility Commands (/help, /start, /projects)
│   └── Admin Commands (/stats, /users)
├── Message Handlers
│   ├── Text Message Handler
│   ├── Document Handler
│   └── Photo Handler
├── Callback Handlers
│   ├── Project Selection
│   ├── Quick Actions
│   └── Confirmation Dialogs
└── Response Formatters
    ├── Code Formatter
    ├── Error Formatter
    └── Progress Indicators
```

## Main Bot Implementation

### Core Bot Class
```python
# src/bot/core.py
"""
Main Telegram bot class

Features:
- Command registration
- Handler management
- Context injection
- Graceful shutdown
"""

from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram import Update, BotCommand
from typing import Dict, List, Callable
import asyncio

class ClaudeCodeBot:
    """Main bot orchestrator"""
    
    def __init__(self, config: Settings, dependencies: Dict[str, Any]):
        self.config = config
        self.deps = dependencies
        self.app: Optional[Application] = None
        self.handlers: Dict[str, Callable] = {}
        
    async def initialize(self):
        """Initialize bot application"""
        # Create application
        self.app = Application.builder().token(
            self.config.telegram_bot_token.get_secret_value()
        ).build()
        
        # Set bot commands for menu
        await self._set_bot_commands()
        
        # Register handlers
        self._register_handlers()
        
        # Add middleware
        self._add_middleware()
        
        # Initialize webhook or polling
        if self.config.webhook_url:
            await self._setup_webhook()
        
    async def _set_bot_commands(self):
        """Set bot command menu"""
        commands = [
            BotCommand("start", "Start bot and show help"),
            BotCommand("help", "Show available commands"),
            BotCommand("new", "Start new Claude session"),
            BotCommand("continue", "Continue last session"),
            BotCommand("ls", "List files in current directory"),
            BotCommand("cd", "Change directory"),
            BotCommand("pwd", "Show current directory"),
            BotCommand("projects", "Show all projects"),
            BotCommand("status", "Show session status"),
            BotCommand("export", "Export current session"),
        ]
        
        await self.app.bot.set_my_commands(commands)
    
    def _register_handlers(self):
        """Register all command and message handlers"""
        # Import handlers
        from .handlers import command, message, callback
        
        # Command handlers
        self.app.add_handler(CommandHandler("start", self._inject_deps(command.start_command)))
        self.app.add_handler(CommandHandler("help", self._inject_deps(command.help_command)))
        self.app.add_handler(CommandHandler("new", self._inject_deps(command.new_session)))
        self.app.add_handler(CommandHandler("continue", self._inject_deps(command.continue_session)))
        self.app.add_handler(CommandHandler("ls", self._inject_deps(command.list_files)))
        self.app.add_handler(CommandHandler("cd", self._inject_deps(command.change_directory)))
        self.app.add_handler(CommandHandler("pwd", self._inject_deps(command.print_working_directory)))
        self.app.add_handler(CommandHandler("projects", self._inject_deps(command.show_projects)))
        self.app.add_handler(CommandHandler("status", self._inject_deps(command.session_status)))
        
        # Message handlers
        self.app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self._inject_deps(message.handle_text_message)
        ))
        self.app.add_handler(MessageHandler(
            filters.Document.ALL,
            self._inject_deps(message.handle_document)
        ))
        self.app.add_handler(MessageHandler(
            filters.PHOTO,
            self._inject_deps(message.handle_photo)
        ))
        
        # Callback query handler
        self.app.add_handler(CallbackQueryHandler(
            self._inject_deps(callback.handle_callback_query)
        ))
        
        # Error handler
        self.app.add_error_handler(self._error_handler)
    
    def _inject_deps(self, handler: Callable) -> Callable:
        """Inject dependencies into handlers"""
        async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE):
            # Add dependencies to context
            context.user_data['deps'] = self.deps
            return await handler(update, context)
        return wrapped
    
    def _add_middleware(self):
        """Add middleware to application"""
        # Middleware runs in order
        self.app.add_handler(
            MessageHandler(filters.ALL, self._inject_deps(auth_middleware)),
            group=-2  # Auth first
        )
        self.app.add_handler(
            MessageHandler(filters.ALL, self._inject_deps(rate_limit_middleware)),
            group=-1  # Rate limit second
        )
    
    async def start(self):
        """Start the bot"""
        await self.initialize()
        
        if self.config.webhook_url:
            # Webhook mode
            await self.app.run_webhook(
                listen="0.0.0.0",
                port=self.config.webhook_port,
                url_path=self.config.webhook_path,
                webhook_url=self.config.webhook_url
            )
        else:
            # Polling mode
            await self.app.run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True
            )
    
    async def stop(self):
        """Gracefully stop the bot"""
        if self.app:
            await self.app.stop()
```

## Command Handlers

### Navigation Commands
```python
# src/bot/handlers/command.py
"""
Command handlers for bot operations
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from pathlib import Path

async def list_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /ls command"""
    deps = context.user_data['deps']
    session_manager = deps['session_manager']
    security_validator = deps['security_validator']
    
    # Get user session
    user_id = update.effective_user.id
    session = session_manager.get_session(user_id)
    
    try:
        # List directory contents
        items = []
        for item in sorted(session.current_directory.iterdir()):
            if item.name.startswith('.'):
                continue  # Skip hidden files
                
            if item.is_dir():
                items.append(f"📁 {item.name}/")
            else:
                # Get file size
                size = item.stat().st_size
                size_str = _format_file_size(size)
                items.append(f"📄 {item.name} ({size_str})")
        
        # Format response
        if not items:
            message = f"📂 `{session.current_directory.name}/`\n\n_(empty directory)_"
        else:
            current_path = session.current_directory.relative_to(deps['config'].approved_directory)
            message = f"📂 `{current_path}/`\n\n"
            
            # Limit items shown
            max_items = 50
            if len(items) > max_items:
                shown_items = items[:max_items]
                message += "\n".join(shown_items)
                message += f"\n\n_... and {len(items) - max_items} more items_"
            else:
                message += "\n".join(items)
        
        await update.message.reply_text(message, parse_mode='Markdown')
        
        # Log command
        await deps['audit_logger'].log_command(user_id, 'ls', [], True)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error listing directory: {str(e)}")
        await deps['audit_logger'].log_command(user_id, 'ls', [], False)

async def change_directory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cd command"""
    deps = context.user_data['deps']
    session_manager = deps['session_manager']
    security_validator = deps['security_validator']
    
    user_id = update.effective_user.id
    session = session_manager.get_session(user_id)
    
    # Parse arguments
    if not context.args:
        await update.message.reply_text(
            "Usage: `/cd <directory>`\n"
            "Examples:\n"
            "• `/cd myproject` - Enter subdirectory\n"
            "• `/cd ..` - Go up one level\n"
            "• `/cd /` - Go to root of approved directory",
            parse_mode='Markdown'
        )
        return
    
    target_path = ' '.join(context.args)
    
    # Validate path
    valid, resolved_path, error = security_validator.validate_path(
        target_path, 
        session.current_directory
    )
    
    if not valid:
        await update.message.reply_text(f"❌ {error}")
        await deps['audit_logger'].log_security_violation(
            user_id, 'path_traversal', f"Attempted: {target_path}"
        )
        return
    
    # Check if directory exists
    if not resolved_path.exists():
        await update.message.reply_text(f"❌ Directory not found: `{target_path}`", parse_mode='Markdown')
        return
        
    if not resolved_path.is_dir():
        await update.message.reply_text(f"❌ Not a directory: `{target_path}`", parse_mode='Markdown')
        return
    
    # Update session
    session.current_directory = resolved_path
    session.claude_session_id = None  # Clear Claude session on directory change
    
    # Send confirmation
    relative_path = resolved_path.relative_to(deps['config'].approved_directory)
    await update.message.reply_text(
        f"✅ Changed directory to: `{relative_path}/`\n"
        f"Claude session cleared. Send a message to start new session.",
        parse_mode='Markdown'
    )
    
    await deps['audit_logger'].log_command(user_id, 'cd', [target_path], True)
```

### Session Commands
```python
async def new_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /new command"""
    deps = context.user_data['deps']
    session_manager = deps['session_manager']
    
    user_id = update.effective_user.id
    session = session_manager.get_session(user_id)
    
    # Clear Claude session
    session.claude_session_id = None
    
    # Show confirmation with current directory
    relative_path = session.current_directory.relative_to(deps['config'].approved_directory)
    
    keyboard = [[
        InlineKeyboardButton("📝 Start coding", callback_data="action:start_coding"),
        InlineKeyboardButton("📁 Change project", callback_data="action:show_projects")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"🆕 New Claude Code session\n\n"
        f"📂 Working directory: `{relative_path}/`\n\n"
        f"Send me a message to start coding, or:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def session_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command"""
    deps = context.user_data['deps']
    session_manager = deps['session_manager']
    rate_limiter = deps['rate_limiter']
    
    user_id = update.effective_user.id
    session = session_manager.get_session(user_id)
    
    # Get session info
    has_claude_session = session.claude_session_id is not None
    relative_path = session.current_directory.relative_to(deps['config'].approved_directory)
    
    # Get usage info
    user_cost = rate_limiter.cost_tracker.get(user_id, 0.0)
    cost_limit = deps['config'].claude_max_cost_per_user
    cost_percentage = (user_cost / cost_limit) * 100
    
    # Format status message
    status_lines = [
        "📊 **Session Status**",
        "",
        f"📂 Directory: `{relative_path}/`",
        f"🤖 Claude Session: {'✅ Active' if has_claude_session else '❌ None'}",
        f"💰 Usage: ${user_cost:.2f} / ${cost_limit:.2f} ({cost_percentage:.0f}%)",
        f"⏰ Last Activity: {session.last_activity.strftime('%H:%M:%S')}",
    ]
    
    if has_claude_session:
        status_lines.append(f"🆔 Session ID: `{session.claude_session_id[:8]}...`")
    
    # Add action buttons
    keyboard = []
    if has_claude_session:
        keyboard.append([
            InlineKeyboardButton("🔄 Continue session", callback_data="action:continue"),
            InlineKeyboardButton("🆕 New session", callback_data="action:new")
        ])
    keyboard.append([
        InlineKeyboardButton("📤 Export session", callback_data="action:export"),
        InlineKeyboardButton("🔄 Refresh", callback_data="action:refresh_status")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "\n".join(status_lines),
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
```

## Message Handlers

### Text Message Handler
```python
# src/bot/handlers/message.py
"""
Message handlers for non-command inputs
"""

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular text messages as Claude prompts"""
    deps = context.user_data['deps']
    session_manager = deps['session_manager']
    claude_integration = deps['claude_integration']
    rate_limiter = deps['rate_limiter']
    
    user_id = update.effective_user.id
    session = session_manager.get_session(user_id)
    message_text = update.message.text
    
    # Check rate limit with estimated cost
    estimated_cost = 0.001  # Base cost estimate
    allowed, limit_message = await rate_limiter.check_rate_limit(user_id, estimated_cost)
    
    if not allowed:
        await update.message.reply_text(f"⏱️ {limit_message}")
        return
    
    # Send typing indicator
    await update.message.chat.send_action('typing')
    
    # Create progress message
    progress_msg = await update.message.reply_text(
        "🤔 Thinking...",
        reply_to_message_id=update.message.message_id
    )
    
    try:
        # Run Claude Code
        result = await claude_integration.run_command(
            prompt=message_text,
            working_directory=session.current_directory,
            session_id=session.claude_session_id,
            on_stream=lambda msg: _update_progress(progress_msg, msg)
        )
        
        # Delete progress message
        await progress_msg.delete()
        
        # Update session
        session.claude_session_id = result.session_id
        
        # Format and send response
        formatter = ResponseFormatter(deps['config'])
        messages = formatter.format_claude_response(result.content)
        
        for msg in messages:
            await update.message.reply_text(
                msg.text,
                parse_mode=msg.parse_mode,
                reply_markup=msg.reply_markup
            )
        
        # Send metadata
        await _send_metadata(update, result)
        
        # Update cost tracking
        await rate_limiter.track_cost(user_id, result.cost)
        
    except asyncio.TimeoutError:
        await progress_msg.edit_text("❌ Operation timed out. Try a simpler request.")
    except Exception as e:
        await progress_msg.edit_text(f"❌ Error: {str(e)}")
        logger.exception("Error handling text message")
```

### Document Handler
```python
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle file uploads"""
    deps = context.user_data['deps']
    security_validator = deps['security_validator']
    
    document = update.message.document
    
    # Validate filename
    valid, error = security_validator.validate_filename(document.file_name)
    if not valid:
        await update.message.reply_text(f"❌ {error}")
        return
    
    # Check file size
    max_size = 10 * 1024 * 1024  # 10MB
    if document.file_size > max_size:
        await update.message.reply_text(
            f"❌ File too large. Maximum size: {max_size // 1024 // 1024}MB"
        )
        return
    
    # Download file
    try:
        file = await document.get_file()
        file_bytes = await file.download_as_bytearray()
        
        # Try to decode as text
        try:
            content = file_bytes.decode('utf-8')
        except UnicodeDecodeError:
            await update.message.reply_text("❌ File must be text-based (UTF-8)")
            return
        
        # Create prompt with file content
        caption = update.message.caption or "Review this file:"
        prompt = f"{caption}\n\nFile: {document.file_name}\n```\n{content}\n```"
        
        # Process as regular message
        update.message.text = prompt
        await handle_text_message(update, context)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error processing file: {str(e)}")
```

## Callback Query Handler

### Inline Keyboard Actions
```python
# src/bot/handlers/callback.py
"""
Handle inline keyboard callbacks
"""

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route callback queries to appropriate handlers"""
    query = update.callback_query
    await query.answer()  # Acknowledge the callback
    
    data = query.data
    deps = context.user_data['deps']
    
    # Parse callback data
    if ':' in data:
        action, param = data.split(':', 1)
    else:
        action, param = data, None
    
    # Route to appropriate handler
    handlers = {
        'cd': handle_cd_callback,
        'action': handle_action_callback,
        'confirm': handle_confirm_callback,
        'quick': handle_quick_action_callback,
    }
    
    handler = handlers.get(action)
    if handler:
        await handler(query, param, deps)
    else:
        await query.edit_message_text("❌ Unknown action")

async def handle_cd_callback(query, project_name, deps):
    """Handle project selection from inline keyboard"""
    session_manager = deps['session_manager']
    security_validator = deps['security_validator']
    
    user_id = query.from_user.id
    session = session_manager.get_session(user_id)
    
    # Validate and change directory
    new_path = deps['config'].approved_directory / project_name
    
    if new_path.exists() and new_path.is_dir():
        session.current_directory = new_path
        session.claude_session_id = None
        
        await query.edit_message_text(
            f"✅ Changed to project: `{project_name}/`\n\n"
            f"Claude session cleared. Send a message to start coding.",
            parse_mode='Markdown'
        )
    else:
        await query.edit_message_text("❌ Project not found")

async def handle_quick_action_callback(query, action_type, deps):
    """Handle quick action buttons"""
    quick_actions = {
        'test': "Run all tests in the current directory",
        'install': "Install dependencies (npm install or pip install)",
        'format': "Format all code files",
        'lint': "Run linter on all files",
        'git_status': "Show git status",
        'find_todos': "Find all TODO comments in the codebase",
    }
    
    prompt = quick_actions.get(action_type)
    if prompt:
        # Simulate sending the prompt
        query.message.text = prompt
        await handle_text_message(query, {'user_data': {'deps': deps}})
```

## Response Formatting

### Message Formatter
```python
# src/bot/utils/formatting.py
"""
Format bot responses for optimal display
"""

from dataclasses import dataclass
from typing import List, Optional
import re

@dataclass
class FormattedMessage:
    text: str
    parse_mode: str = 'Markdown'
    reply_markup: Optional[Any] = None

class ResponseFormatter:
    """Format Claude responses for Telegram"""
    
    def __init__(self, config: Settings):
        self.config = config
        self.max_message_length = 4000
    
    def format_claude_response(self, text: str) -> List[FormattedMessage]:
        """Format Claude response into Telegram messages"""
        # Handle code blocks
        text = self._format_code_blocks(text)
        
        # Split long messages
        messages = self._split_message(text)
        
        # Add quick actions to last message if enabled
        if self.config.enable_quick_actions and messages:
            messages[-1].reply_markup = self._get_quick_actions_keyboard()
        
        return messages
    
    def _format_code_blocks(self, text: str) -> str:
        """Ensure code blocks are properly formatted"""
        # Convert triple backticks to Telegram format
        # Handle language specifications
        pattern = r'```(\w+)?\n(.*?)```'
        
        def replace_code_block(match):
            lang = match.group(1) or ''
            code = match.group(2)
            
            # Telegram doesn't support language hints in code blocks
            # But we can add it as a comment
            if lang:
                return f"```\n# {lang}\n{code}```"
            return f"```\n{code}```"
        
        return re.sub(pattern, replace_code_block, text, flags=re.DOTALL)
    
    def _split_message(self, text: str) -> List[FormattedMessage]:
        """Split long messages while preserving formatting"""
        if len(text) <= self.max_message_length:
            return [FormattedMessage(text)]
        
        messages = []
        current = []
        current_length = 0
        in_code_block = False
        
        for line in text.split('\n'):
            line_length = len(line) + 1
            
            # Check for code block markers
            if line.strip() == '```':
                in_code_block = not in_code_block
            
            # Check if adding line would exceed limit
            if current_length + line_length > self.max_message_length:
                # Close code block if needed
                if in_code_block:
                    current.append('```')
                
                # Save current message
                messages.append(FormattedMessage('\n'.join(current)))
                
                # Start new message
                current = []
                current_length = 0
                
                # Reopen code block if needed
                if in_code_block:
                    current.append('```')
                    current_length = 4
            
            current.append(line)
            current_length += line_length
        
        # Add remaining content
        if current:
            messages.append(FormattedMessage('\n'.join(current)))
        
        return messages
    
    def _get_quick_actions_keyboard(self):
        """Get quick actions inline keyboard"""
        keyboard = [
            [
                InlineKeyboardButton("🧪 Run tests", callback_data="quick:test"),
                InlineKeyboardButton("📦 Install deps", callback_data="quick:install")
            ],
            [
                InlineKeyboardButton("🎨 Format code", callback_data="quick:format"),
                InlineKeyboardButton("🔍 Find TODOs", callback_data="quick:find_todos")
            ]
        ]
        
        return InlineKeyboardMarkup(keyboard)
```

## Error Handling

### Global Error Handler
```python
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors globally"""
    logger.error(f"Exception while handling update {update}: {context.error}")
    
    # Notify user
    if update and update.effective_message:
        error_messages = {
            RateLimitError: "⏱️ Rate limit exceeded. Please wait a moment.",
            SecurityError: "🔒 Security violation detected.",
            ClaudeError: "🤖 Error communicating with Claude.",
            asyncio.TimeoutError: "⏰ Operation timed out.",
        }
        
        error_type = type(context.error)
        message = error_messages.get(error_type, "❌ An unexpected error occurred.")
        
        try:
            await update.effective_message.reply_text(message)
        except Exception:
            # Error sending error message - just log it
            logger.exception("Error sending error message to user")
    
    # Report to monitoring
    if context.user_data.get('deps', {}).get('monitoring'):
        await context.user_data['deps']['monitoring'].report_error(
            error=context.error,
            update=update,
            context=context
        )
```

## Success Criteria

- [ ] Bot successfully connects to Telegram
- [ ] All commands properly registered and visible in menu
- [ ] Navigation commands work with proper validation
- [ ] Session commands manage Claude state correctly
- [ ] Text messages trigger Claude integration
- [ ] File uploads are validated and processed
- [ ] Inline keyboards function properly
- [ ] Response formatting handles long messages
- [ ] Code blocks display correctly
- [ ] Error handling provides useful feedback
- [ ] All handlers properly inject dependencies
- [ ] Middleware executes in correct order
- [ ] Bot can handle concurrent users