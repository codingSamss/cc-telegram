"""Security framework for Claude Code Telegram Bot.

This module provides comprehensive security features including:
- Whitelist authentication
- Path traversal and injection prevention
- Input validation and sanitization
- Security audit logging

Key Components:
- AuthenticationManager: Main authentication system
- SecurityValidator: Input validation and path security
- AuditLogger: Security event logging
"""

from .audit import AuditEvent, AuditLogger, SQLiteAuditStorage
from .auth import (
    AuthenticationManager,
    AuthProvider,
    UserSession,
    WhitelistAuthProvider,
)
from .validators import SecurityValidator

__all__ = [
    "AuthProvider",
    "WhitelistAuthProvider",
    "AuthenticationManager",
    "UserSession",
    "SecurityValidator",
    "AuditLogger",
    "AuditEvent",
    "SQLiteAuditStorage",
]
