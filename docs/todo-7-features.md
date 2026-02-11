# TODO-7: Advanced Features

## Objective
Implement advanced features that enhance the user experience, including file upload handling, Git integration, quick actions, session export, and image/screenshot support.

## Feature Breakdown

### 1. Enhanced File Upload Handling

#### Multi-file Support
```python
# src/bot/features/file_handler.py
"""
Advanced file handling

Features:
- Multiple file processing
- Zip archive extraction
- Code analysis
- Diff generation
"""

class FileHandler:
    """Handle various file operations"""
    
    def __init__(self, config: Settings, security: SecurityValidator):
        self.config = config
        self.security = security
        self.temp_dir = Path("/tmp/claude_bot_files")
        self.temp_dir.mkdir(exist_ok=True)
        
    async def handle_document_upload(
        self, 
        document: Document,
        user_id: int,
        context: str = ""
    ) -> ProcessedFile:
        """Process uploaded document"""
        
        # Download file
        file_path = await self._download_file(document)
        
        try:
            # Detect file type
            file_type = self._detect_file_type(file_path)
            
            # Process based on type
            if file_type == 'archive':
                return await self._process_archive(file_path, context)
            elif file_type == 'code':
                return await self._process_code_file(file_path, context)
            elif file_type == 'text':
                return await self._process_text_file(file_path, context)
            else:
                raise ValueError(f"Unsupported file type: {file_type}")
                
        finally:
            # Cleanup
            file_path.unlink(missing_ok=True)
    
    async def _process_archive(self, archive_path: Path, context: str) -> ProcessedFile:
        """Extract and analyze archive contents"""
        import zipfile
        import tarfile
        
        # Create extraction directory
        extract_dir = self.temp_dir / f"extract_{uuid.uuid4()}"
        extract_dir.mkdir()
        
        try:
            # Extract based on type
            if archive_path.suffix == '.zip':
                with zipfile.ZipFile(archive_path) as zf:
                    # Security check - prevent zip bombs
                    total_size = sum(f.file_size for f in zf.filelist)
                    if total_size > 100 * 1024 * 1024:  # 100MB limit
                        raise ValueError("Archive too large")
                    
                    zf.extractall(extract_dir)
            
            # Analyze contents
            file_tree = self._build_file_tree(extract_dir)
            code_files = self._find_code_files(extract_dir)
            
            # Create analysis prompt
            prompt = f"{context}\n\nProject structure:\n{file_tree}\n\n"
            
            # Add key files
            for file_path in code_files[:5]:  # Limit to 5 files
                content = file_path.read_text(encoding='utf-8', errors='ignore')
                prompt += f"\nFile: {file_path.relative_to(extract_dir)}\n```\n{content[:1000]}...\n```\n"
            
            return ProcessedFile(
                type='archive',
                prompt=prompt,
                metadata={
                    'file_count': len(list(extract_dir.rglob('*'))),
                    'code_files': len(code_files)
                }
            )
            
        finally:
            # Cleanup
            shutil.rmtree(extract_dir, ignore_errors=True)
    
    def _build_file_tree(self, directory: Path, prefix: str = "") -> str:
        """Build visual file tree"""
        items = sorted(directory.iterdir(), key=lambda x: (x.is_file(), x.name))
        tree_lines = []
        
        for i, item in enumerate(items):
            is_last = i == len(items) - 1
            current_prefix = "└── " if is_last else "├── "
            
            if item.is_dir():
                tree_lines.append(f"{prefix}{current_prefix}{item.name}/")
                # Recursive call with updated prefix
                sub_prefix = prefix + ("    " if is_last else "│   ")
                tree_lines.append(self._build_file_tree(item, sub_prefix))
            else:
                size = item.stat().st_size
                tree_lines.append(f"{prefix}{current_prefix}{item.name} ({self._format_size(size)})")
        
        return "\n".join(filter(None, tree_lines))
```

#### Code Analysis Features
```python
async def analyze_codebase(self, directory: Path) -> CodebaseAnalysis:
    """Analyze entire codebase"""
    
    analysis = CodebaseAnalysis()
    
    # Language detection
    language_stats = defaultdict(int)
    file_extensions = defaultdict(int)
    
    for file_path in directory.rglob('*'):
        if file_path.is_file():
            ext = file_path.suffix.lower()
            file_extensions[ext] += 1
            
            language = self._detect_language(ext)
            if language:
                language_stats[language] += 1
    
    # Find entry points
    entry_points = self._find_entry_points(directory)
    
    # Detect frameworks
    frameworks = self._detect_frameworks(directory)
    
    # Find TODOs and FIXMEs
    todos = await self._find_todos(directory)
    
    # Check for tests
    test_files = self._find_test_files(directory)
    
    return CodebaseAnalysis(
        languages=dict(language_stats),
        frameworks=frameworks,
        entry_points=entry_points,
        todo_count=len(todos),
        test_coverage=len(test_files) > 0,
        file_stats=dict(file_extensions)
    )
```

### 2. Git Integration

#### Git Commands
```python
# src/bot/features/git_integration.py
"""
Git integration for version control operations

Features:
- Status checking
- Diff viewing
- Branch management
- Commit history
"""

class GitIntegration:
    """Handle Git operations"""
    
    def __init__(self, security: SecurityValidator):
        self.security = security
        
    async def get_status(self, repo_path: Path) -> GitStatus:
        """Get repository status"""
        if not (repo_path / '.git').exists():
            raise ValueError("Not a git repository")
        
        # Run git status
        result = await self._run_git_command(['status', '--porcelain'], repo_path)
        
        # Parse status
        changes = self._parse_status(result)
        
        # Get current branch
        branch = await self._get_current_branch(repo_path)
        
        # Get recent commits
        commits = await self._get_recent_commits(repo_path, limit=5)
        
        return GitStatus(
            branch=branch,
            changes=changes,
            recent_commits=commits,
            has_changes=len(changes) > 0
        )
    
    async def get_diff(self, repo_path: Path, staged: bool = False) -> str:
        """Get diff of changes"""
        cmd = ['diff']
        if staged:
            cmd.append('--staged')
        
        diff = await self._run_git_command(cmd, repo_path)
        
        # Format for display
        return self._format_diff(diff)
    
    async def get_file_history(self, repo_path: Path, file_path: str) -> List[CommitInfo]:
        """Get commit history for a file"""
        cmd = ['log', '--follow', '--pretty=format:%H|%an|%ae|%ai|%s', '--', file_path]
        
        result = await self._run_git_command(cmd, repo_path)
        
        commits = []
        for line in result.strip().split('\n'):
            if line:
                parts = line.split('|')
                if len(parts) >= 5:
                    commits.append(CommitInfo(
                        hash=parts[0],
                        author=parts[1],
                        email=parts[2],
                        date=parts[3],
                        message=parts[4]
                    ))
        
        return commits
    
    async def _run_git_command(self, args: List[str], cwd: Path) -> str:
        """Run git command safely"""
        # Security check - only allow safe git commands
        safe_commands = ['status', 'diff', 'log', 'branch', 'remote', 'show']
        if args[0] not in safe_commands:
            raise SecurityError(f"Git command not allowed: {args[0]}")
        
        cmd = ['git'] + args
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd)
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise GitError(f"Git command failed: {stderr.decode()}")
        
        return stdout.decode()
    
    def _format_diff(self, diff: str) -> str:
        """Format diff for Telegram display"""
        lines = diff.split('\n')
        formatted = []
        
        for line in lines[:100]:  # Limit output
            if line.startswith('+'):
                formatted.append(f"➕ {line[1:]}")
            elif line.startswith('-'):
                formatted.append(f"➖ {line[1:]}")
            elif line.startswith('@@'):
                formatted.append(f"📍 {line}")
            else:
                formatted.append(line)
        
        if len(lines) > 100:
            formatted.append(f"\n... and {len(lines) - 100} more lines")
        
        return '\n'.join(formatted)
```

### 3. Quick Actions System

#### Action Definitions
```python
# src/bot/features/quick_actions.py
"""
Quick action system for common tasks

Features:
- Predefined actions
- Custom actions
- Context-aware suggestions
"""

@dataclass
class QuickAction:
    """Quick action definition"""
    id: str
    name: str
    icon: str
    prompt: str
    requires_confirmation: bool = False
    context_requirements: List[str] = None

class QuickActionManager:
    """Manage quick actions"""
    
    def __init__(self):
        self.actions = self._load_default_actions()
        
    def _load_default_actions(self) -> Dict[str, QuickAction]:
        """Load default quick actions"""
        return {
            'test': QuickAction(
                id='test',
                name='Run Tests',
                icon='🧪',
                prompt='Run all tests in the current directory and show results',
                context_requirements=['test_framework']
            ),
            'install': QuickAction(
                id='install',
                name='Install Dependencies',
                icon='📦',
                prompt='Install project dependencies based on package files',
                context_requirements=['package_file']
            ),
            'format': QuickAction(
                id='format',
                name='Format Code',
                icon='🎨',
                prompt='Format all code files using appropriate formatters'
            ),
            'lint': QuickAction(
                id='lint',
                name='Run Linter',
                icon='🔍',
                prompt='Run linting tools and show issues'
            ),
            'security': QuickAction(
                id='security',
                name='Security Check',
                icon='🔒',
                prompt='Check for security vulnerabilities in dependencies'
            ),
            'optimize': QuickAction(
                id='optimize',
                name='Optimize Code',
                icon='⚡',
                prompt='Analyze and suggest optimizations for the current code'
            ),
            'document': QuickAction(
                id='document',
                name='Add Documentation',
                icon='📝',
                prompt='Add or improve documentation for the current code'
            ),
            'refactor': QuickAction(
                id='refactor',
                name='Refactor Code',
                icon='🔧',
                prompt='Suggest refactoring improvements for better code quality'
            )
        }
    
    async def get_context_actions(self, directory: Path) -> List[QuickAction]:
        """Get actions available for current context"""
        available = []
        
        # Check context
        context = await self._analyze_context(directory)
        
        for action in self.actions.values():
            if self._is_action_available(action, context):
                available.append(action)
        
        return available
    
    async def _analyze_context(self, directory: Path) -> Dict[str, bool]:
        """Analyze directory context"""
        context = {
            'test_framework': False,
            'package_file': False,
            'git_repo': False,
            'has_code': False
        }
        
        # Check for test framework
        test_indicators = ['pytest.ini', 'jest.config.js', 'test/', 'tests/', '__tests__']
        for indicator in test_indicators:
            if (directory / indicator).exists():
                context['test_framework'] = True
                break
        
        # Check for package files
        package_files = ['package.json', 'requirements.txt', 'Pipfile', 'Cargo.toml', 'go.mod']
        for pf in package_files:
            if (directory / pf).exists():
                context['package_file'] = True
                break
        
        # Check for git
        context['git_repo'] = (directory / '.git').exists()
        
        # Check for code files
        code_extensions = {'.py', '.js', '.ts', '.java', '.cpp', '.go', '.rs'}
        for file in directory.iterdir():
            if file.suffix in code_extensions:
                context['has_code'] = True
                break
        
        return context
    
    def create_action_keyboard(self, actions: List[QuickAction]) -> InlineKeyboardMarkup:
        """Create inline keyboard for actions"""
        keyboard = []
        
        # Group actions in rows of 2
        for i in range(0, len(actions), 2):
            row = []
            for j in range(2):
                if i + j < len(actions):
                    action = actions[i + j]
                    row.append(InlineKeyboardButton(
                        f"{action.icon} {action.name}",
                        callback_data=f"quick:{action.id}"
                    ))
            keyboard.append(row)
        
        return InlineKeyboardMarkup(keyboard)
```

### 4. Session Export Feature

#### Export Formats
```python
# src/bot/features/session_export.py
"""
Export Claude sessions in various formats

Features:
- Markdown export
- JSON export
- HTML export
- PDF generation
"""

class SessionExporter:
    """Export sessions in various formats"""
    
    def __init__(self, storage: Storage):
        self.storage = storage
        
    async def export_session(
        self, 
        session_id: str,
        format: str = 'markdown'
    ) -> ExportedSession:
        """Export session in specified format"""
        
        # Load session data
        session = await self.storage.sessions.get_session(session_id)
        if not session:
            raise ValueError("Session not found")
        
        # Load messages
        messages = await self.storage.messages.get_session_messages(session_id)
        
        # Export based on format
        if format == 'markdown':
            content = self._export_markdown(session, messages)
            filename = f"claude_session_{session_id[:8]}.md"
        elif format == 'json':
            content = self._export_json(session, messages)
            filename = f"claude_session_{session_id[:8]}.json"
        elif format == 'html':
            content = self._export_html(session, messages)
            filename = f"claude_session_{session_id[:8]}.html"
        else:
            raise ValueError(f"Unsupported format: {format}")
        
        return ExportedSession(
            content=content,
            filename=filename,
            format=format,
            size=len(content.encode('utf-8'))
        )
    
    def _export_markdown(self, session: SessionModel, messages: List[MessageModel]) -> str:
        """Export as Markdown"""
        lines = []
        
        # Header
        lines.append(f"# Claude Code Session Export")
        lines.append(f"\n**Session ID:** `{session.session_id}`")
        lines.append(f"**Project:** `{session.project_path}`")
        lines.append(f"**Created:** {session.created_at.isoformat()}")
        lines.append(f"**Messages:** {len(messages)}")
        lines.append(f"**Total Cost:** ${session.total_cost:.4f}")
        lines.append("\n---\n")
        
        # Messages
        for msg in reversed(messages):  # Chronological order
            lines.append(f"## 🧑 User ({msg.timestamp.strftime('%H:%M:%S')})")
            lines.append(f"\n{msg.prompt}\n")
            
            if msg.response:
                lines.append(f"## 🤖 Claude")
                lines.append(f"\n{msg.response}\n")
                
                if msg.cost > 0:
                    lines.append(f"*Cost: ${msg.cost:.4f} | Duration: {msg.duration_ms}ms*")
            
            lines.append("\n---\n")
        
        return '\n'.join(lines)
    
    def _export_html(self, session: SessionModel, messages: List[MessageModel]) -> str:
        """Export as HTML with styling"""
        template = """
<!DOCTYPE html>
<html>
<head>
    <title>Claude Code Session - {session_id}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                max-width: 800px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #f0f0f0; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
        .message {{ margin: 20px 0; padding: 15px; border-radius: 8px; }}
        .user {{ background: #e3f2fd; }}
        .assistant {{ background: #f5f5f5; }}
        .timestamp {{ color: #666; font-size: 0.9em; }}
        .cost {{ color: #666; font-size: 0.9em; font-style: italic; }}
        pre {{ background: #272822; color: #f8f8f2; padding: 10px; border-radius: 4px; overflow-x: auto; }}
        code {{ background: #f0f0f0; padding: 2px 4px; border-radius: 3px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Claude Code Session Export</h1>
        <p><strong>Session ID:</strong> <code>{session_id}</code></p>
        <p><strong>Project:</strong> <code>{project_path}</code></p>
        <p><strong>Created:</strong> {created}</p>
        <p><strong>Total Cost:</strong> ${total_cost:.4f}</p>
    </div>
    
    {messages_html}
</body>
</html>
        """
        
        messages_html = []
        for msg in reversed(messages):
            msg_html = f"""
            <div class="message user">
                <div class="timestamp">👤 User - {msg.timestamp.strftime('%H:%M:%S')}</div>
                <div>{self._markdown_to_html(msg.prompt)}</div>
            </div>
            """
            
            if msg.response:
                msg_html += f"""
                <div class="message assistant">
                    <div class="timestamp">🤖 Claude</div>
                    <div>{self._markdown_to_html(msg.response)}</div>
                    <div class="cost">Cost: ${msg.cost:.4f} | Duration: {msg.duration_ms}ms</div>
                </div>
                """
            
            messages_html.append(msg_html)
        
        return template.format(
            session_id=session.session_id,
            project_path=session.project_path,
            created=session.created_at.isoformat(),
            total_cost=session.total_cost,
            messages_html='\n'.join(messages_html)
        )
```

### 5. Image/Screenshot Support

#### Image Processing
```python
# src/bot/features/image_handler.py
"""
Handle image uploads for UI/screenshot analysis

Features:
- OCR for text extraction
- UI element detection
- Image description
- Diagram analysis
"""

class ImageHandler:
    """Process image uploads"""
    
    def __init__(self, config: Settings):
        self.config = config
        self.supported_formats = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}
        
    async def process_image(
        self,
        photo: PhotoSize,
        caption: Optional[str] = None
    ) -> ProcessedImage:
        """Process uploaded image"""
        
        # Download image
        file = await photo.get_file()
        image_bytes = await file.download_as_bytearray()
        
        # Detect image type
        image_type = self._detect_image_type(image_bytes)
        
        # Create appropriate prompt
        if image_type == 'screenshot':
            prompt = self._create_screenshot_prompt(caption)
        elif image_type == 'diagram':
            prompt = self._create_diagram_prompt(caption)
        elif image_type == 'ui_mockup':
            prompt = self._create_ui_prompt(caption)
        else:
            prompt = self._create_generic_prompt(caption)
        
        # Convert to base64 for Claude (if supported in future)
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        
        return ProcessedImage(
            prompt=prompt,
            image_type=image_type,
            base64_data=base64_image,
            size=len(image_bytes)
        )
    
    def _detect_image_type(self, image_bytes: bytes) -> str:
        """Detect type of image"""
        # Simple heuristic based on image characteristics
        # In practice, could use ML model for better detection
        
        # For now, return generic type
        return 'screenshot'
    
    def _create_screenshot_prompt(self, caption: Optional[str]) -> str:
        """Create prompt for screenshot analysis"""
        base_prompt = """I'm sharing a screenshot with you. Please analyze it and help me with:
        
1. Identifying what application or website this is from
2. Understanding the UI elements and their purpose
3. Any issues or improvements you notice
4. Answering any specific questions I have

"""
        if caption:
            base_prompt += f"Specific request: {caption}"
        
        return base_prompt
```

### 6. Interactive Features

#### Conversation Mode
```python
# src/bot/features/conversation_mode.py
"""
Enhanced conversation features

Features:
- Context preservation
- Follow-up suggestions
- Code execution tracking
"""

class ConversationEnhancer:
    """Enhance conversation experience"""
    
    def __init__(self):
        self.conversation_contexts = {}
        
    def generate_follow_up_suggestions(
        self,
        response: ClaudeResponse,
        context: ConversationContext
    ) -> List[str]:
        """Generate relevant follow-up suggestions"""
        suggestions = []
        
        # Based on tools used
        if 'create_file' in [t['name'] for t in response.tools_used]:
            suggestions.append("Add tests for the new code")
            suggestions.append("Create documentation")
        
        if 'edit_file' in [t['name'] for t in response.tools_used]:
            suggestions.append("Review the changes")
            suggestions.append("Run tests to verify")
        
        # Based on content
        if 'error' in response.content.lower():
            suggestions.append("Help me debug this error")
            suggestions.append("Suggest alternative approaches")
        
        if 'todo' in response.content.lower():
            suggestions.append("Complete the TODO items")
            suggestions.append("Prioritize the tasks")
        
        return suggestions[:3]  # Limit to 3 suggestions
    
    def create_follow_up_keyboard(self, suggestions: List[str]) -> InlineKeyboardMarkup:
        """Create keyboard with follow-up suggestions"""
        keyboard = []
        
        for suggestion in suggestions:
            keyboard.append([InlineKeyboardButton(
                f"💡 {suggestion}",
                callback_data=f"followup:{hash(suggestion) % 1000000}"
            )])
        
        keyboard.append([InlineKeyboardButton(
            "✅ Done",
            callback_data="conversation:end"
        )])
        
        return InlineKeyboardMarkup(keyboard)
```

## Integration Points

### Feature Registry
```python
# src/bot/features/registry.py
"""
Central feature registry and management
"""

class FeatureRegistry:
    """Manage all bot features"""
    
    def __init__(self, config: Settings, deps: Dict[str, Any]):
        self.config = config
        self.deps = deps
        self.features = {}
        
        # Initialize features based on config
        self._initialize_features()
    
    def _initialize_features(self):
        """Initialize enabled features"""
        if self.config.enable_file_uploads:
            self.features['file_handler'] = FileHandler(
                self.config,
                self.deps['security']
            )
        
        if self.config.enable_git_integration:
            self.features['git'] = GitIntegration(
                self.deps['security']
            )
        
        if self.config.enable_quick_actions:
            self.features['quick_actions'] = QuickActionManager()
        
        self.features['session_export'] = SessionExporter(
            self.deps['storage']
        )
        
        self.features['image_handler'] = ImageHandler(self.config)
        
        self.features['conversation'] = ConversationEnhancer()
    
    def get_feature(self, name: str) -> Optional[Any]:
        """Get feature by name"""
        return self.features.get(name)
    
    def is_enabled(self, feature_name: str) -> bool:
        """Check if feature is enabled"""
        return feature_name in self.features
```

## Success Criteria

- [ ] File uploads process correctly with security validation
- [ ] Archive extraction handles zip/tar files safely
- [ ] Git integration shows status, diffs, and history
- [ ] Quick actions appear contextually
- [ ] Session export works in all formats
- [ ] Image uploads create appropriate prompts
- [ ] Follow-up suggestions are relevant
- [ ] All features respect security boundaries
- [ ] Features can be toggled via configuration
- [ ] Memory usage stays reasonable with large files
- [ ] Error handling provides clear feedback
- [ ] Integration tests cover all features