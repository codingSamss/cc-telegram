# TODO-1: Project Structure & Core Setup

## Objective
Establish a well-organized, maintainable project structure that supports both development and open-source contribution.

## Directory Structure

```
claude-code-telegram/
├── src/
│   ├── __init__.py
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── handlers/
│   │   │   ├── __init__.py
│   │   │   ├── command.py      # Command handlers
│   │   │   ├── message.py      # Message handlers
│   │   │   └── callback.py     # Inline keyboard handlers
│   │   ├── middleware/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py         # Authentication middleware
│   │   │   ├── logging.py      # Logging middleware
│   │   │   └── error.py        # Error handling middleware
│   │   └── core.py             # Main bot class
│   ├── claude/
│   │   ├── __init__.py
│   │   ├── integration.py      # Claude Code subprocess manager
│   │   ├── parser.py           # Output parsing
│   │   └── session.py          # Session management
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── database.py         # Database connection
│   │   ├── models.py           # Data models
│   │   └── repositories.py     # Data access layer
│   ├── security/
│   │   ├── __init__.py
│   │   ├── auth.py            # Authentication logic
│   │   ├── validators.py      # Input validation
│   │   └── rate_limiter.py    # Rate limiting
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── formatting.py      # Message formatting
│   │   ├── file_handler.py    # File operations
│   │   └── constants.py       # App constants
│   ├── config.py              # Configuration management
│   ├── exceptions.py          # Custom exceptions
│   └── main.py               # Entry point
├── tests/
│   ├── __init__.py
│   ├── unit/                  # Unit tests mirror src structure
│   ├── integration/           # Integration tests
│   ├── fixtures/              # Test data
│   └── conftest.py           # Pytest configuration
├── docs/
│   ├── setup.md
│   ├── configuration.md
│   ├── api/                   # API documentation
│   └── development.md
├── scripts/
│   ├── setup.sh              # Development setup
│   ├── migrate.py            # Database migrations
│   └── check_health.py       # Health check script
├── docker/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── .dockerignore
├── .github/
│   ├── workflows/
│   │   ├── test.yml          # CI testing
│   │   ├── lint.yml          # Code quality
│   │   └── release.yml       # Release automation
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md
│   │   └── feature_request.md
│   └── pull_request_template.md
├── requirements/
│   ├── base.txt              # Core dependencies
│   ├── dev.txt               # Development dependencies
│   └── test.txt              # Testing dependencies
├── .env.example              # Environment template
├── .gitignore
├── README.md
├── CONTRIBUTING.md
├── SECURITY.md
├── LICENSE
├── pyproject.toml           # Project metadata
├── setup.py                 # Package setup
└── Makefile                 # Common commands
```

## Core Package Setup

### pyproject.toml
```toml
[tool.poetry]
name = "claude-code-telegram"
version = "0.1.0"
description = "Telegram bot for remote Claude Code access"
authors = ["Your Name <email@example.com>"]
license = "MIT"
readme = "README.md"
repository = "https://github.com/yourusername/claude-code-telegram"
keywords = ["telegram", "bot", "claude", "ai", "development"]

[tool.black]
line-length = 88
target-version = ['py39']

[tool.isort]
profile = "black"
line_length = 88

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = "test_*.py"
addopts = "-v --cov=src --cov-report=html --cov-report=term-missing"

[tool.mypy]
python_version = "3.9"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
```

## Logging Infrastructure

### Structured Logging Setup
```python
# src/utils/logging.py
"""
Configure structured logging using structlog
- JSON output for production
- Pretty printing for development
- Correlation IDs for request tracking
- Performance metrics
"""

# Configuration based on environment
# Development: Colorful, human-readable output
# Production: JSON with full context
# Include: timestamp, level, logger, correlation_id, user_id, event
```

## Exception Hierarchy

### Base Exceptions
```python
# src/exceptions.py
"""
ClaudeCodeTelegramError (base)
├── ConfigurationError
│   ├── MissingConfigError
│   └── InvalidConfigError
├── SecurityError
│   ├── AuthenticationError
│   ├── AuthorizationError
│   └── DirectoryTraversalError
├── ClaudeError
│   ├── ClaudeTimeoutError
│   ├── ClaudeProcessError
│   └── ClaudeParsingError
├── StorageError
│   ├── DatabaseConnectionError
│   └── DataIntegrityError
└── TelegramError
    ├── MessageTooLongError
    └── RateLimitError
"""
```

## Development Environment

### Makefile Commands
```makefile
.PHONY: install dev test lint format clean

install:
	pip install -r requirements/base.txt

dev:
	pip install -r requirements/dev.txt
	pre-commit install

test:
	pytest

lint:
	black --check src tests
	isort --check-only src tests
	flake8 src tests
	mypy src

format:
	black src tests
	isort src tests

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
```

## Initial Files to Create

1. **src/__init__.py**: Version and package info
2. **src/main.py**: Entry point with basic argument parsing
3. **src/config.py**: Empty configuration class
4. **src/exceptions.py**: Complete exception hierarchy
5. **src/utils/constants.py**: App-wide constants
6. **.env.example**: Template with all required variables
7. **requirements/base.txt**: Core dependencies only
8. **README.md**: Basic project description
9. **.gitignore**: Python-specific ignores
10. **Makefile**: Development commands

## Dependencies to Include

### requirements/base.txt
```
python-telegram-bot>=20.0
structlog>=23.0
pydantic>=2.0
pydantic-settings>=2.0
asyncio>=3.4
aiofiles>=23.0
```

### requirements/dev.txt
```
-r base.txt
-r test.txt
black>=23.0
isort>=5.0
flake8>=6.0
mypy>=1.0
pre-commit>=3.0
ipython>=8.0
```

### requirements/test.txt
```
-r base.txt
pytest>=7.0
pytest-asyncio>=0.21
pytest-cov>=4.0
pytest-mock>=3.0
factory-boy>=3.0
```

## Success Criteria

- [ ] All directories created with __init__.py files
- [ ] Dependencies installed successfully
- [ ] Basic logging works with structured output
- [ ] Exception hierarchy implemented
- [ ] Makefile commands functioning
- [ ] Pre-commit hooks configured
- [ ] Can run `make test` successfully (even with no tests)
- [ ] Project installable with `pip install -e .`