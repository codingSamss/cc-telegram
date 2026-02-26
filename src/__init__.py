"""CLITG.

A Telegram bot that provides remote access to CLI coding agents, allowing
developers to interact with their projects from anywhere through a secure,
terminal-like interface within Telegram.

Features:
- Environment-based configuration with Pydantic validation
- Feature flags for dynamic functionality control
- Authentication and security validation
- Session persistence and state management
- Claude/Codex engine integration

Current Implementation Status:
- Core bot workflow and middleware are implemented
- Claude SDK/CLI and Codex CLI adapters are available
- Storage, audit logging, and session management are enabled
- Unit tests and lint pipeline are integrated
"""

__version__ = "0.1.0"
__author__ = "Richard Atkinson"
__email__ = "richardatk01@gmail.com"
__license__ = "MIT"
__homepage__ = "https://github.com/codingSamss/cli-tg"

# Development status indicator
__status__ = "Active Development"
