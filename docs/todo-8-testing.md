# TODO-8: Testing & Quality

## Objective
Implement comprehensive testing strategy with unit tests, integration tests, end-to-end tests, and performance tests while ensuring code quality through linting, type checking, and continuous integration.

## Testing Architecture

### Test Structure
```
tests/
├── unit/                    # Unit tests (mirror src structure)
│   ├── bot/
│   │   ├── test_handlers.py
│   │   ├── test_middleware.py
│   │   └── test_core.py
│   ├── claude/
│   │   ├── test_integration.py
│   │   ├── test_parser.py
│   │   └── test_session.py
│   ├── security/
│   │   ├── test_auth.py
│   │   ├── test_validators.py
│   │   └── test_rate_limiter.py
│   └── storage/
│       ├── test_repositories.py
│       └── test_models.py
├── integration/            # Integration tests
│   ├── test_bot_claude.py
│   ├── test_storage_integration.py
│   └── test_security_integration.py
├── e2e/                   # End-to-end tests
│   ├── test_user_flows.py
│   └── test_scenarios.py
├── performance/           # Performance tests
│   ├── test_load.py
│   └── test_memory.py
├── fixtures/              # Test data
│   ├── __init__.py
│   ├── factories.py      # Test data factories
│   ├── mocks.py         # Mock objects
│   └── sample_data/     # Sample files
└── conftest.py          # Pytest configuration
```

## Test Implementation

### Pytest Configuration
```python
# tests/conftest.py
"""
Pytest configuration and shared fixtures
"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock
import tempfile
import aiosqlite

# Configure async tests
pytest_plugins = ['pytest_asyncio']

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def test_config():
    """Test configuration"""
    from src.config import Settings
    
    return Settings(
        telegram_bot_token="test_token",
        telegram_bot_username="test_bot",
        approved_directory=Path("/tmp/test_projects"),
        allowed_users=[123456789],
        database_url="sqlite:///:memory:",
        claude_timeout_seconds=10,
        rate_limit_requests=100,
        session_timeout_hours=1,
        enable_telemetry=False
    )

@pytest.fixture
async def test_db():
    """In-memory test database"""
    from src.storage.database import DatabaseManager
    
    db = DatabaseManager("sqlite:///:memory:")
    await db.initialize()
    yield db
    await db.close()

@pytest.fixture
def mock_telegram_update():
    """Mock Telegram update"""
    update = Mock()
    update.effective_user.id = 123456789
    update.effective_user.username = "testuser"
    update.message.text = "Test message"
    update.message.chat.id = 123456789
    update.message.reply_text = AsyncMock()
    return update

@pytest.fixture
def mock_claude_response():
    """Mock Claude response"""
    from src.claude.integration import ClaudeResponse
    
    return ClaudeResponse(
        content="Test response",
        session_id="test-session-123",
        cost=0.001,
        duration_ms=1000,
        num_turns=1,
        tools_used=[]
    )

@pytest.fixture
async def test_storage(test_db):
    """Test storage with database"""
    from src.storage.facade import Storage
    
    storage = Storage("sqlite:///:memory:")
    await storage.initialize()
    yield storage
    await storage.close()

@pytest.fixture
def temp_project_dir():
    """Temporary project directory"""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir) / "test_project"
        project_dir.mkdir()
        
        # Create sample files
        (project_dir / "main.py").write_text("print('Hello World')")
        (project_dir / "README.md").write_text("# Test Project")
        
        yield project_dir
```

### Unit Tests

#### Bot Handler Tests
```python
# tests/unit/bot/test_handlers.py
"""
Unit tests for bot command handlers
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from pathlib import Path

from src.bot.handlers import command

class TestCommandHandlers:
    """Test command handlers"""
    
    @pytest.mark.asyncio
    async def test_list_files_success(self, mock_telegram_update, temp_project_dir):
        """Test ls command lists files correctly"""
        # Setup
        context = Mock()
        context.user_data = {
            'deps': {
                'session_manager': Mock(get_session=Mock(return_value=Mock(
                    current_directory=temp_project_dir
                ))),
                'audit_logger': AsyncMock(),
                'config': Mock(approved_directory=temp_project_dir.parent)
            }
        }
        
        # Execute
        await command.list_files(mock_telegram_update, context)
        
        # Assert
        mock_telegram_update.message.reply_text.assert_called_once()
        call_args = mock_telegram_update.message.reply_text.call_args[0][0]
        assert "main.py" in call_args
        assert "README.md" in call_args
    
    @pytest.mark.asyncio
    async def test_change_directory_security(self, mock_telegram_update):
        """Test cd command prevents directory traversal"""
        # Setup
        context = Mock()
        context.args = ["../../../etc"]
        context.user_data = {
            'deps': {
                'session_manager': Mock(),
                'security_validator': Mock(
                    validate_path=Mock(return_value=(False, None, "Access denied"))
                ),
                'audit_logger': AsyncMock()
            }
        }
        
        # Execute
        await command.change_directory(mock_telegram_update, context)
        
        # Assert
        mock_telegram_update.message.reply_text.assert_called_with("❌ Access denied")
    
    @pytest.mark.asyncio
    async def test_new_session_clears_state(self, mock_telegram_update):
        """Test new session clears Claude session"""
        # Setup
        session = Mock()
        session.claude_session_id = "old-session"
        session.current_directory = Path("/test")
        
        context = Mock()
        context.user_data = {
            'deps': {
                'session_manager': Mock(get_session=Mock(return_value=session)),
                'config': Mock(approved_directory=Path("/"))
            }
        }
        
        # Execute
        await command.new_session(mock_telegram_update, context)
        
        # Assert
        assert session.claude_session_id is None
        mock_telegram_update.message.reply_text.assert_called_once()
```

#### Security Tests
```python
# tests/unit/security/test_validators.py
"""
Unit tests for security validators
"""

import pytest
from pathlib import Path

from src.security.validators import SecurityValidator

class TestSecurityValidator:
    """Test security validation"""
    
    @pytest.fixture
    def validator(self, temp_project_dir):
        return SecurityValidator(temp_project_dir)
    
    @pytest.mark.parametrize("path,should_fail", [
        ("../../../etc/passwd", True),
        ("./valid_dir", False),
        ("subdir/file.txt", False),
        ("~/.ssh/keys", True),
        ("/etc/shadow", True),
        ("project/../../../", True),
        ("project/./valid", False),
        ("project%2F..%2F..", True),
        ("$(whoami)", True),
        ("file;rm -rf /", True),
        ("file|mail attacker", True),
    ])
    def test_path_validation(self, validator, path, should_fail):
        """Test path validation catches dangerous paths"""
        valid, resolved, error = validator.validate_path(
            path, 
            validator.approved_directory
        )
        
        if should_fail:
            assert not valid
            assert error is not None
        else:
            assert valid or not (validator.approved_directory / path).exists()
    
    @pytest.mark.parametrize("filename,should_fail", [
        ("../../etc/passwd", True),
        ("normal_file.py", False),
        (".hidden_file", True),
        ("file.exe", True),
        ("script.sh", False),
        ("../malicious.py", True),
        ("file\x00.txt", True),
    ])
    def test_filename_validation(self, validator, filename, should_fail):
        """Test filename validation"""
        valid, error = validator.validate_filename(filename)
        
        if should_fail:
            assert not valid
            assert error is not None
        else:
            assert valid
```

#### Claude Integration Tests
```python
# tests/unit/claude/test_integration.py
"""
Unit tests for Claude integration
"""

import pytest
import asyncio
import json
from unittest.mock import Mock, AsyncMock, patch

from src.claude.integration import ClaudeProcessManager, ClaudeResponse

class TestClaudeProcessManager:
    """Test Claude process management"""
    
    @pytest.fixture
    def process_manager(self, test_config):
        return ClaudeProcessManager(test_config)
    
    @pytest.mark.asyncio
    async def test_execute_command_success(self, process_manager):
        """Test successful command execution"""
        # Mock subprocess
        mock_process = Mock()
        mock_process.stdout = self._create_mock_stream([
            json.dumps({"type": "system", "subtype": "init", "tools": ["bash"]}),
            json.dumps({
                "type": "assistant", 
                "message": {"content": [{"type": "text", "text": "Hello"}]}
            }),
            json.dumps({
                "type": "result",
                "subtype": "success",
                "result": "Hello",
                "session_id": "test-123",
                "cost_usd": 0.001,
                "duration_ms": 100,
                "num_turns": 1
            })
        ])
        mock_process.wait = AsyncMock(return_value=0)
        
        with patch('asyncio.create_subprocess_exec', return_value=mock_process):
            result = await process_manager.execute_command(
                "test prompt",
                Path("/test"),
                None,
                False,
                None
            )
        
        assert isinstance(result, ClaudeResponse)
        assert result.content == "Hello"
        assert result.session_id == "test-123"
        assert result.cost == 0.001
    
    @pytest.mark.asyncio
    async def test_timeout_handling(self, process_manager, test_config):
        """Test timeout kills process"""
        # Mock slow subprocess
        mock_process = Mock()
        mock_process.stdout = self._create_slow_stream()
        mock_process.kill = Mock()
        mock_process.wait = AsyncMock()
        
        test_config.claude_timeout_seconds = 0.1  # Very short timeout
        
        with patch('asyncio.create_subprocess_exec', return_value=mock_process):
            with pytest.raises(ClaudeTimeoutError):
                await process_manager.execute_command(
                    "test", Path("/test"), None, False, None
                )
        
        mock_process.kill.assert_called_once()
    
    def _create_mock_stream(self, lines):
        """Create mock stream that yields lines"""
        async def mock_readline():
            for line in lines:
                yield (line + '\n').encode()
            yield b''
        
        mock_stream = Mock()
        mock_stream.readline = mock_readline().__anext__
        return mock_stream
```

### Integration Tests

#### Bot-Claude Integration
```python
# tests/integration/test_bot_claude.py
"""
Integration tests for bot and Claude
"""

import pytest
from pathlib import Path

class TestBotClaudeIntegration:
    """Test bot integration with Claude"""
    
    @pytest.mark.asyncio
    async def test_message_to_claude_flow(
        self, 
        test_storage,
        mock_telegram_update,
        mock_claude_response
    ):
        """Test complete flow from message to Claude response"""
        # Setup dependencies
        deps = {
            'session_manager': Mock(get_session=Mock(return_value=Mock(
                current_directory=Path("/test"),
                claude_session_id=None
            ))),
            'claude_integration': AsyncMock(
                run_command=AsyncMock(return_value=mock_claude_response)
            ),
            'rate_limiter': Mock(
                check_rate_limit=AsyncMock(return_value=(True, None)),
                track_cost=AsyncMock()
            ),
            'config': Mock(enable_quick_actions=False)
        }
        
        context = Mock()
        context.user_data = {'deps': deps}
        
        # Execute
        from src.bot.handlers.message import handle_text_message
        await handle_text_message(mock_telegram_update, context)
        
        # Verify Claude was called
        deps['claude_integration'].run_command.assert_called_once()
        
        # Verify response was sent
        assert mock_telegram_update.message.reply_text.called
        
        # Verify cost was tracked
        deps['rate_limiter'].track_cost.assert_called_with(
            123456789, 
            mock_claude_response.cost
        )
```

### End-to-End Tests

#### User Flow Tests
```python
# tests/e2e/test_user_flows.py
"""
End-to-end tests for complete user flows
"""

import pytest
from telegram import Update
from telegram.ext import Application

class TestUserFlows:
    """Test complete user workflows"""
    
    @pytest.mark.asyncio
    async def test_new_user_onboarding(self, test_bot_app):
        """Test new user onboarding flow"""
        # Simulate /start command
        update = self._create_update("/start", user_id=999999)
        await test_bot_app.process_update(update)
        
        # Verify welcome message
        assert "Welcome to Claude Code Bot" in self.sent_messages[-1]
        
        # Simulate /projects command
        update = self._create_update("/projects", user_id=999999)
        await test_bot_app.process_update(update)
        
        # Verify project list
        assert "Select a project" in self.sent_messages[-1]
    
    @pytest.mark.asyncio
    async def test_coding_session_flow(self, test_bot_app):
        """Test complete coding session"""
        user_id = 123456789
        
        # Start in project
        update = self._create_update("/cd myproject", user_id=user_id)
        await test_bot_app.process_update(update)
        
        # Send coding request
        update = self._create_update(
            "Create a Python function to calculate fibonacci", 
            user_id=user_id
        )
        await test_bot_app.process_update(update)
        
        # Verify Claude response
        assert "def fibonacci" in self.sent_messages[-1]
        
        # Continue conversation
        update = self._create_update(
            "Now add memoization", 
            user_id=user_id
        )
        await test_bot_app.process_update(update)
        
        # Verify session continuity
        assert "memoization" in self.sent_messages[-1]
```

### Performance Tests

#### Load Testing
```python
# tests/performance/test_load.py
"""
Performance and load tests
"""

import pytest
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

class TestPerformance:
    """Test performance characteristics"""
    
    @pytest.mark.asyncio
    async def test_concurrent_users(self, test_bot_app):
        """Test handling multiple concurrent users"""
        num_users = 50
        messages_per_user = 5
        
        async def simulate_user(user_id):
            """Simulate user sending messages"""
            for i in range(messages_per_user):
                update = self._create_update(
                    f"Test message {i}", 
                    user_id=user_id
                )
                await test_bot_app.process_update(update)
                await asyncio.sleep(0.1)  # Simulate typing
        
        start_time = time.time()
        
        # Run concurrent users
        tasks = [
            simulate_user(user_id) 
            for user_id in range(num_users)
        ]
        await asyncio.gather(*tasks)
        
        duration = time.time() - start_time
        total_messages = num_users * messages_per_user
        throughput = total_messages / duration
        
        # Assert performance targets
        assert throughput > 10  # At least 10 messages/second
        assert duration < 30    # Complete within 30 seconds
    
    @pytest.mark.asyncio
    async def test_memory_usage(self, test_bot_app):
        """Test memory usage under load"""
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Send many messages
        for i in range(1000):
            update = self._create_update(f"Message {i}", user_id=123)
            await test_bot_app.process_update(update)
        
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory
        
        # Assert memory usage is reasonable
        assert memory_increase < 100  # Less than 100MB increase
```

### Test Utilities

#### Test Factories
```python
# tests/fixtures/factories.py
"""
Test data factories
"""

import factory
from datetime import datetime

from src.storage.models import UserModel, SessionModel, MessageModel

class UserFactory(factory.Factory):
    """Create test users"""
    class Meta:
        model = UserModel
    
    user_id = factory.Sequence(lambda n: 1000 + n)
    telegram_username = factory.Faker('user_name')
    first_seen = factory.LazyFunction(datetime.utcnow)
    last_active = factory.LazyFunction(datetime.utcnow)
    is_allowed = True
    total_cost = 0.0
    message_count = 0
    session_count = 0

class SessionFactory(factory.Factory):
    """Create test sessions"""
    class Meta:
        model = SessionModel
    
    session_id = factory.Faker('uuid4')
    user_id = factory.SubFactory(UserFactory)
    project_path = "/test/project"
    created_at = factory.LazyFunction(datetime.utcnow)
    last_used = factory.LazyFunction(datetime.utcnow)
    total_cost = 0.0
    total_turns = 0
    message_count = 0
    is_active = True
```

#### Mock Builders
```python
# tests/fixtures/mocks.py
"""
Mock object builders
"""

def create_mock_update(text, user_id=123456789, **kwargs):
    """Create mock Telegram update"""
    update = Mock()
    update.effective_user.id = user_id
    update.effective_user.username = kwargs.get('username', 'testuser')
    update.message.text = text
    update.message.chat.id = kwargs.get('chat_id', user_id)
    update.message.message_id = kwargs.get('message_id', 1)
    update.message.reply_text = AsyncMock()
    update.message.chat.send_action = AsyncMock()
    
    # Add callback query if specified
    if 'callback_data' in kwargs:
        update.callback_query = Mock()
        update.callback_query.data = kwargs['callback_data']
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
    
    return update
```

## Quality Assurance

### Code Coverage Configuration
```ini
# .coveragerc
[run]
source = src
omit = 
    */tests/*
    */migrations/*
    */__init__.py

[report]
precision = 2
show_missing = True
skip_covered = False

[html]
directory = htmlcov

[xml]
output = coverage.xml
```

### Linting Configuration
```toml
# pyproject.toml additions
[tool.black]
line-length = 88
target-version = ['py39']
include = '\.pyi?$'

[tool.isort]
profile = "black"
line_length = 88

[tool.flake8]
max-line-length = 88
extend-ignore = E203, W503
exclude = .git,__pycache__,docs,old,build,dist

[tool.mypy]
python_version = "3.9"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
ignore_missing_imports = true

[tool.pylint]
max-line-length = 88
disable = C0103,C0114,C0115,C0116,R0903
```

### CI/CD Pipeline
```yaml
# .github/workflows/test.yml
name: Tests

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: [3.9, "3.10", 3.11]
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python ${{ matrix.python-version }}
      uses: actions/setup-python@v4
      with:
        python-version: ${{ matrix.python-version }}
    
    - name: Cache dependencies
      uses: actions/cache@v3
      with:
        path: ~/.cache/pip
        key: ${{ runner.os }}-pip-${{ hashFiles('requirements/*.txt') }}
    
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements/test.txt
    
    - name: Lint with flake8
      run: |
        flake8 src tests
    
    - name: Check formatting with black
      run: |
        black --check src tests
    
    - name: Type check with mypy
      run: |
        mypy src
    
    - name: Test with pytest
      run: |
        pytest -v --cov=src --cov-report=xml --cov-report=html
    
    - name: Upload coverage
      uses: codecov/codecov-action@v3
      with:
        file: ./coverage.xml
        fail_ci_if_error: true
```

## Testing Commands

### Makefile Additions
```makefile
# Testing commands
test:
	pytest -v

test-unit:
	pytest tests/unit -v

test-integration:
	pytest tests/integration -v

test-e2e:
	pytest tests/e2e -v

test-coverage:
	pytest --cov=src --cov-report=html --cov-report=term

test-watch:
	ptw -- -v

test-parallel:
	pytest -n auto

test-profile:
	pytest --profile

test-all: lint type-check test-coverage
```

## Success Criteria

- [ ] Unit test coverage > 80%
- [ ] All integration tests pass
- [ ] E2E tests cover main user flows
- [ ] Performance tests meet targets
- [ ] No linting errors
- [ ] Type checking passes
- [ ] CI/CD pipeline green
- [ ] Load tests handle 50+ concurrent users
- [ ] Memory usage stays under limits
- [ ] Security tests pass OWASP checks
- [ ] Mock objects properly simulate real behavior
- [ ] Test execution time < 5 minutes