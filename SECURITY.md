# Security Policy

## Supported Versions

This project is currently in development. Security updates will be provided for:

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | ✅ Current development |

## Security Model

The Claude Code Telegram Bot implements a defense-in-depth security model with multiple layers:

### 1. Authentication & Authorization (TODO-3)
- **User Whitelist**: Only pre-approved Telegram user IDs can access the bot
- **Token-Based Auth**: Optional token-based authentication for additional security
- **Session Management**: Secure session handling with timeout and cleanup

### 2. Directory Boundaries (TODO-3)
- **Approved Directory**: All operations confined to a pre-configured directory tree
- **Path Validation**: Prevents directory traversal attacks (../../../etc/passwd)
- **Permission Checks**: Validates file system permissions before operations

### 3. Input Validation (TODO-3)
- **Command Sanitization**: All user inputs sanitized to prevent injection attacks
- **File Type Validation**: Only allowed file types can be uploaded
- **Path Sanitization**: Removes dangerous characters and patterns

### 4. Rate Limiting (TODO-3)
- **Request Rate Limiting**: Prevents abuse with configurable request limits
- **Cost-Based Limiting**: Tracks and limits Claude usage costs per user
- **Burst Protection**: Token bucket algorithm prevents burst attacks

### 5. Audit Logging (TODO-3)
- **Authentication Events**: All login attempts and auth failures logged
- **Command Execution**: All commands and file operations logged
- **Security Violations**: Path traversal attempts and other violations logged

## Current Security Status

### ✅ Implemented Security Features

#### Configuration Security
- **Environment Variable Protection**: Sensitive values (tokens, secrets) handled as SecretStr
- **Validation**: All configuration values validated with proper error messages
- **Path Security**: Approved directory must exist and be accessible

#### Input Validation Foundation
- **Type Safety**: Full mypy compliance ensures type safety
- **Validation Framework**: Pydantic validators for all configuration inputs
- **Error Handling**: Comprehensive exception hierarchy for security errors

#### Development Security
- **No Secrets in Code**: All sensitive data via environment variables
- **Secure Defaults**: Production defaults favor security over convenience
- **Audit Trail**: Structured logging captures all configuration and validation events

### 🚧 Planned Security Features (TODO-3)

#### Authentication System
```python
# Planned implementation
class AuthenticationManager:
    async def authenticate_user(self, user_id: int) -> bool
    async def check_permissions(self, user_id: int, action: str) -> bool
    async def create_session(self, user_id: int) -> Session
```

#### Path Validation
```python
# Planned implementation  
class SecurityValidator:
    def validate_path(self, path: str) -> Tuple[bool, Path, Optional[str]]
    def sanitize_command_input(self, text: str) -> str
    def validate_filename(self, filename: str) -> Tuple[bool, Optional[str]]
```

#### Rate Limiting
```python
# Planned implementation
class RateLimiter:
    async def check_rate_limit(self, user_id: int, cost: float) -> Tuple[bool, Optional[str]]
    async def track_usage(self, user_id: int, cost: float) -> None
```

## Security Configuration

### Required Security Settings

```bash
# Base directory for all operations (CRITICAL)
APPROVED_DIRECTORY=/path/to/approved/projects

# User access control
ALLOWED_USERS=123456789,987654321  # Telegram user IDs

# Optional: Token-based authentication
ENABLE_TOKEN_AUTH=true
AUTH_TOKEN_SECRET=your-secret-here  # Generate with: openssl rand -hex 32
```

### Recommended Security Settings

```bash
# Strict rate limiting for production
RATE_LIMIT_REQUESTS=5
RATE_LIMIT_WINDOW=60
RATE_LIMIT_BURST=10

# Cost controls
CLAUDE_MAX_COST_PER_USER=5.0

# Security features
ENABLE_TELEMETRY=true  # For security monitoring
LOG_LEVEL=INFO         # Capture security events

# Environment
ENVIRONMENT=production  # Enables strict security defaults
```

## Security Best Practices

### For Administrators

1. **Directory Configuration**
   ```bash
   # Use minimal necessary permissions
   chmod 755 /path/to/approved/projects
   
   # Avoid sensitive directories
   # ❌ Don't use: /, /home, /etc, /var
   # ✅ Use: /home/user/projects, /opt/bot-projects
   ```

2. **Token Management**
   ```bash
   # Generate secure secrets
   openssl rand -hex 32
   
   # Store in environment, never in code
   export AUTH_TOKEN_SECRET="generated-secret"
   ```

3. **User Management**
   ```bash
   # Get Telegram User ID: message @userinfobot
   # Add to whitelist
   export ALLOWED_USERS="123456789,987654321"
   ```

4. **Monitoring**
   ```bash
   # Enable logging and monitoring
   export LOG_LEVEL=INFO
   export ENABLE_TELEMETRY=true
   
   # Monitor logs for security events
   tail -f bot.log | grep -i "security\|auth\|violation"
   ```

### For Developers

1. **Never Commit Secrets**
   ```bash
   # Add to .gitignore
   .env
   *.key
   *.pem
   config/secrets.yml
   ```

2. **Use Type Safety**
   ```python
   # Always use type hints
   def validate_path(path: str) -> Tuple[bool, Optional[str]]:
       pass
   ```

3. **Validate All Inputs**
   ```python
   # Use the security validator
   from src.security.validators import SecurityValidator
   
   validator = SecurityValidator(approved_dir)
   valid, resolved_path, error = validator.validate_path(user_input)
   ```

4. **Log Security Events**
   ```python
   # Use structured logging
   logger.warning("Security violation", 
                 user_id=user_id, 
                 violation_type="path_traversal",
                 attempted_path=user_input)
   ```

## Threat Model

### Threats We Protect Against

1. **Directory Traversal** (High Priority)
   - Attempts to access files outside approved directory
   - Path traversal attacks (../, ~/, etc.)
   - Symbolic link attacks

2. **Command Injection** (High Priority)
   - Shell command injection through user inputs
   - Environment variable injection
   - Process substitution attacks

3. **Unauthorized Access** (Medium Priority)
   - Access by non-whitelisted users
   - Token theft and replay attacks
   - Session hijacking

4. **Resource Abuse** (Medium Priority)
   - Rate limiting bypass attempts
   - Cost limit violations
   - Denial of service attacks

5. **Information Disclosure** (Low Priority)
   - Sensitive file exposure
   - Configuration information leakage
   - Error message information leakage

### Threats Outside Scope

- Network-level attacks (handled by hosting infrastructure)
- Telegram API vulnerabilities (handled by Telegram)
- Host OS security (handled by system administration)
- Physical access to servers (handled by hosting infrastructure)

## Reporting a Vulnerability

### Security Contact

**Do not create public GitHub issues for security vulnerabilities.**

For security issues, please email: [Insert security contact email]

### Report Format

Please include:

1. **Description** of the vulnerability
2. **Steps to reproduce** the issue
3. **Potential impact** assessment
4. **Suggested mitigation** if known
5. **Disclosure timeline** preferences

### Response Process

1. **Acknowledgment** within 48 hours
2. **Initial assessment** within 1 week
3. **Fix development** as soon as possible
4. **Security advisory** published after fix
5. **Credit** to reporter (if desired)

## Security Checklist

### For Each Release

- [ ] All dependencies updated to latest secure versions
- [ ] Security tests passing
- [ ] No secrets committed to repository
- [ ] Security documentation updated
- [ ] Threat model reviewed
- [ ] Security configuration validated

### For Production Deployment

- [ ] APPROVED_DIRECTORY properly configured and restricted
- [ ] ALLOWED_USERS whitelist configured
- [ ] Rate limiting enabled and configured
- [ ] Logging enabled and monitored
- [ ] Authentication tokens properly secured
- [ ] Environment variables properly configured
- [ ] File permissions properly set
- [ ] Network access properly restricted

## Security Resources

### Tools and Libraries

- **Pydantic**: Input validation and type safety
- **structlog**: Secure, structured logging
- **SecretStr**: Safe handling of sensitive strings
- **pathlib**: Safe path manipulation

### References

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [OWASP API Security Top 10](https://owasp.org/www-project-api-security/)
- [Telegram Bot Security Best Practices](https://core.telegram.org/bots/faq#how-do-i-make-sure-that-webhook-requests-are-coming-from-telegram)
- [Python Security Guide](https://python-security.readthedocs.io/)

---

**Last Updated**: 2025-06-05  
**Security Review**: TODO-3 Implementation Phase