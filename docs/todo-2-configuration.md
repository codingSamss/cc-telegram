# TODO-2: Configuration Management

## Objective
Create a robust, environment-aware configuration system that supports development, testing, and production deployments with proper validation and security.

## Configuration Structure

### Environment Variables Schema
```
# Bot Configuration
TELEGRAM_BOT_TOKEN=             # Required: Bot token from BotFather
TELEGRAM_BOT_USERNAME=          # Required: Bot username

# Security
APPROVED_DIRECTORY=             # Required: Base directory for projects
ALLOWED_USERS=                  # Optional: Comma-separated user IDs
ENABLE_TOKEN_AUTH=false         # Optional: Enable token-based auth
AUTH_TOKEN_SECRET=              # Required if ENABLE_TOKEN_AUTH=true

# Claude Configuration
CLAUDE_MAX_TURNS=10             # Max conversation turns
CLAUDE_TIMEOUT_SECONDS=300      # Timeout for Claude operations
CLAUDE_MAX_COST_PER_USER=10.0   # Max cost per user in USD

# Rate Limiting
RATE_LIMIT_REQUESTS=10          # Requests per window
RATE_LIMIT_WINDOW=60            # Window in seconds
RATE_LIMIT_BURST=20             # Burst capacity

# Storage
DATABASE_URL=sqlite:///data/bot.db  # Database connection
SESSION_TIMEOUT_HOURS=24            # Session expiry
MAX_SESSIONS_PER_USER=5             # Concurrent sessions

# Features
ENABLE_MCP=false                # Model Context Protocol
MCP_CONFIG_PATH=                # MCP configuration file
ENABLE_GIT_INTEGRATION=true     # Git commands
ENABLE_FILE_UPLOADS=true        # File upload handling
ENABLE_QUICK_ACTIONS=true       # Quick action buttons

# Monitoring
LOG_LEVEL=INFO                  # Logging level
ENABLE_TELEMETRY=false          # Anonymous usage stats
SENTRY_DSN=                     # Error tracking

# Development
DEBUG=false                     # Debug mode
DEVELOPMENT_MODE=false          # Development features
```

## Configuration Implementation

### Main Config Class
```python
# src/config.py
"""
Configuration management using Pydantic Settings

Features:
- Environment variable loading
- Type validation
- Default values
- Computed properties
- Environment-specific settings
"""

from pydantic import BaseSettings, validator, SecretStr, DirectoryPath
from typing import List, Optional, Dict
from pathlib import Path

class Settings(BaseSettings):
    # Bot settings
    telegram_bot_token: SecretStr
    telegram_bot_username: str
    
    # Security
    approved_directory: DirectoryPath
    allowed_users: Optional[List[int]] = None
    enable_token_auth: bool = False
    auth_token_secret: Optional[SecretStr] = None
    
    # Claude settings
    claude_max_turns: int = 10
    claude_timeout_seconds: int = 300
    claude_max_cost_per_user: float = 10.0
    
    # Rate limiting
    rate_limit_requests: int = 10
    rate_limit_window: int = 60
    rate_limit_burst: int = 20
    
    # Storage
    database_url: str = "sqlite:///data/bot.db"
    session_timeout_hours: int = 24
    max_sessions_per_user: int = 5
    
    # Features
    enable_mcp: bool = False
    mcp_config_path: Optional[Path] = None
    enable_git_integration: bool = True
    enable_file_uploads: bool = True
    enable_quick_actions: bool = True
    
    # Monitoring
    log_level: str = "INFO"
    enable_telemetry: bool = False
    sentry_dsn: Optional[str] = None
    
    # Development
    debug: bool = False
    development_mode: bool = False
    
    class Config:
        env_file = '.env'
        env_file_encoding = 'utf-8'
        case_sensitive = False
```

### Validators and Computed Properties
```python
# Validators
@validator('allowed_users', pre=True)
def parse_allowed_users(cls, v):
    """Parse comma-separated user IDs"""
    if isinstance(v, str):
        return [int(uid.strip()) for uid in v.split(',') if uid.strip()]
    return v

@validator('auth_token_secret')
def validate_auth_token(cls, v, values):
    """Ensure token secret exists if token auth enabled"""
    if values.get('enable_token_auth') and not v:
        raise ValueError('auth_token_secret required when enable_token_auth is True')
    return v

@validator('approved_directory')
def validate_approved_directory(cls, v):
    """Ensure approved directory exists and is absolute"""
    path = Path(v).resolve()
    if not path.exists():
        raise ValueError(f'Approved directory does not exist: {path}')
    return path

# Computed properties
@property
def is_production(self) -> bool:
    return not (self.debug or self.development_mode)

@property
def database_path(self) -> Path:
    """Extract path from database URL"""
    if self.database_url.startswith('sqlite:///'):
        return Path(self.database_url.replace('sqlite:///', ''))
    raise ValueError('Only SQLite supported in current version')
```

### Environment-Specific Configurations
```python
# src/config/environments.py
"""
Environment-specific configuration overrides
"""

class DevelopmentConfig:
    """Development environment overrides"""
    debug = True
    development_mode = True
    log_level = "DEBUG"
    rate_limit_requests = 100  # More lenient for testing
    
class TestingConfig:
    """Testing environment configuration"""
    database_url = "sqlite:///:memory:"
    approved_directory = "/tmp/test_projects"
    enable_telemetry = False
    
class ProductionConfig:
    """Production environment configuration"""
    debug = False
    development_mode = False
    enable_telemetry = True
```

### Feature Flags System
```python
# src/config/features.py
"""
Feature flag management
"""

class FeatureFlags:
    def __init__(self, settings: Settings):
        self.settings = settings
        
    @property
    def mcp_enabled(self) -> bool:
        return self.settings.enable_mcp and self.settings.mcp_config_path
        
    @property
    def git_enabled(self) -> bool:
        return self.settings.enable_git_integration
        
    @property
    def file_uploads_enabled(self) -> bool:
        return self.settings.enable_file_uploads
        
    @property
    def quick_actions_enabled(self) -> bool:
        return self.settings.enable_quick_actions
        
    def is_feature_enabled(self, feature_name: str) -> bool:
        """Generic feature check"""
        return getattr(self, f"{feature_name}_enabled", False)
```

### Configuration Loader
```python
# src/config/loader.py
"""
Configuration loading with environment detection
"""

import os
from typing import Optional

def load_config(env: Optional[str] = None) -> Settings:
    """Load configuration based on environment"""
    env = env or os.getenv('ENVIRONMENT', 'development')
    
    # Load base settings
    settings = Settings()
    
    # Apply environment overrides
    if env == 'development':
        settings = apply_overrides(settings, DevelopmentConfig)
    elif env == 'testing':
        settings = apply_overrides(settings, TestingConfig)
    elif env == 'production':
        settings = apply_overrides(settings, ProductionConfig)
        
    # Validate configuration
    validate_config(settings)
    
    return settings

def validate_config(settings: Settings):
    """Additional runtime validation"""
    # Check file permissions
    if not os.access(settings.approved_directory, os.R_OK | os.X_OK):
        raise ConfigurationError(f"Cannot access approved directory: {settings.approved_directory}")
    
    # Validate feature dependencies
    if settings.enable_mcp and not settings.mcp_config_path:
        raise ConfigurationError("MCP enabled but no config path provided")
```

## .env.example Template
```bash
# Claude Code Telegram Bot Configuration

# === REQUIRED SETTINGS ===
# Telegram Bot Token from @BotFather
TELEGRAM_BOT_TOKEN=your_bot_token_here

# Bot username (without @)
TELEGRAM_BOT_USERNAME=your_bot_username

# Base directory for project access (absolute path)
APPROVED_DIRECTORY=/home/user/projects

# === SECURITY SETTINGS ===
# Comma-separated list of allowed Telegram user IDs (optional)
# Leave empty to allow all users (not recommended for production)
ALLOWED_USERS=123456789,987654321

# Enable token-based authentication
ENABLE_TOKEN_AUTH=false

# Secret for generating auth tokens (required if ENABLE_TOKEN_AUTH=true)
# Generate with: openssl rand -hex 32
AUTH_TOKEN_SECRET=

# === CLAUDE SETTINGS ===
# Maximum conversation turns before requiring new session
CLAUDE_MAX_TURNS=10

# Timeout for Claude operations (seconds)
CLAUDE_TIMEOUT_SECONDS=300

# Maximum cost per user in USD
CLAUDE_MAX_COST_PER_USER=10.0

# === RATE LIMITING ===
# Number of requests allowed per window
RATE_LIMIT_REQUESTS=10

# Rate limit window in seconds
RATE_LIMIT_WINDOW=60

# Burst capacity for rate limiting
RATE_LIMIT_BURST=20

# === STORAGE SETTINGS ===
# Database URL (SQLite by default)
DATABASE_URL=sqlite:///data/bot.db

# Session timeout in hours
SESSION_TIMEOUT_HOURS=24

# Maximum concurrent sessions per user
MAX_SESSIONS_PER_USER=5

# === FEATURE FLAGS ===
# Enable Model Context Protocol
ENABLE_MCP=false

# Path to MCP configuration file
MCP_CONFIG_PATH=

# Enable Git integration
ENABLE_GIT_INTEGRATION=true

# Enable file upload handling
ENABLE_FILE_UPLOADS=true

# Enable quick action buttons
ENABLE_QUICK_ACTIONS=true

# === MONITORING ===
# Log level (DEBUG, INFO, WARNING, ERROR)
LOG_LEVEL=INFO

# Enable anonymous telemetry
ENABLE_TELEMETRY=false

# Sentry DSN for error tracking (optional)
SENTRY_DSN=

# === DEVELOPMENT ===
# Enable debug mode
DEBUG=false

# Enable development features
DEVELOPMENT_MODE=false
```

## Usage Examples
```python
# Simple usage
from src.config import load_config

config = load_config()
bot_token = config.telegram_bot_token.get_secret_value()

# With feature flags
from src.config import load_config, FeatureFlags

config = load_config()
features = FeatureFlags(config)

if features.git_enabled:
    # Enable git commands
    pass

# Environment-specific
config = load_config(env='production')

# Access computed properties
if config.is_production:
    # Production-specific behavior
    pass
```

## Testing Configuration
```python
# tests/test_config.py
"""
Test configuration loading and validation
"""

def test_required_fields():
    """Test that missing required fields raise errors"""
    
def test_validator_allowed_users():
    """Test parsing of comma-separated user IDs"""
    
def test_environment_overrides():
    """Test environment-specific configurations"""
    
def test_feature_flags():
    """Test feature flag system"""
```

## Success Criteria

- [ ] Configuration loads from environment variables
- [ ] Validation catches missing required fields
- [ ] Environment-specific overrides work correctly
- [ ] Feature flags properly control functionality
- [ ] Sensitive values (tokens) are properly masked
- [ ] Configuration can be loaded for different environments
- [ ] All validators pass with valid input
- [ ] Invalid configuration raises clear errors
- [ ] .env.example includes all configuration options
- [ ] Tests cover all configuration scenarios