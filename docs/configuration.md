# 配置指南

本文档提供 Claude Code Telegram Bot 的完整配置说明。

## 概述

Bot 使用基于 Pydantic Settings v2 构建的精密配置系统，提供以下功能：

- **类型安全**：所有配置值均经过验证和类型检查
- **环境支持**：自动进行环境特定的配置覆盖
- **功能开关**：动态启用/禁用功能
- **校验机制**：跨字段验证和运行时检查
- **自文档化**：带描述信息的自文档化配置

## 配置来源

配置按以下顺序加载（后加载的来源会覆盖先前的）：

1. Settings 类中定义的**默认值**
2. **环境变量**
3. **`.env` 文件**（如果存在）
4. **环境特定覆盖**（development/testing/production）

## 环境变量

### 必需设置

以下设置必须提供，Bot 才能启动：

```bash
# Telegram Bot 配置
TELEGRAM_BOT_TOKEN=1234567890:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_BOT_USERNAME=your_bot_name

# 安全配置
APPROVED_DIRECTORY=/path/to/your/projects
```

### 可选设置

#### 用户访问控制

```bash
# 逗号分隔的允许 Telegram 用户 ID 列表
ALLOWED_USERS=123456789,987654321

# 启用基于令牌的认证（需要 AUTH_TOKEN_SECRET）
ENABLE_TOKEN_AUTH=false
AUTH_TOKEN_SECRET=your-secret-key-here
```

#### Claude 配置

```bash
# 集成方式
USE_SDK=true                          # 使用 Python SDK（默认）或 CLI 子进程
ANTHROPIC_API_KEY=sk-ant-api03-...    # 可选：SDK 集成的 API 密钥

# 需要新会话前的最大对话轮数
CLAUDE_MAX_TURNS=10

# Claude 操作超时时间（秒）
CLAUDE_TIMEOUT_SECONDS=300

# 每用户最大费用限额（美元）
CLAUDE_MAX_COST_PER_USER=10.0

# 允许的 Claude 工具（逗号分隔列表）
CLAUDE_ALLOWED_TOOLS=Read,Write,Edit,Bash,Glob,Grep,LS,Task,MultiEdit,NotebookRead,NotebookEdit,WebFetch,TodoRead,TodoWrite,WebSearch
```

#### 限流

```bash
# 每时间窗口允许的请求数
RATE_LIMIT_REQUESTS=10

# 限流时间窗口（秒）
RATE_LIMIT_WINDOW=60

# 限流突发容量
RATE_LIMIT_BURST=20
```

#### 存储与数据库

```bash
# 数据库 URL（默认使用 SQLite）
DATABASE_URL=sqlite:///data/bot.db

# 会话管理
SESSION_TIMEOUT_HOURS=24           # 会话超时时间（小时）
MAX_SESSIONS_PER_USER=5            # 每用户最大并发会话数

# 数据库连接
DATABASE_CONNECTION_POOL_SIZE=5    # 连接池大小
DATABASE_TIMEOUT_SECONDS=30       # 数据库操作超时时间

# 数据保留
DATA_RETENTION_DAYS=90            # 旧数据保留天数
AUDIT_LOG_RETENTION_DAYS=365     # 审计日志保留天数
```

#### 功能开关

```bash
# 启用 Model Context Protocol
ENABLE_MCP=false
MCP_CONFIG_PATH=/path/to/mcp/config.json

# 启用 Git 集成
ENABLE_GIT_INTEGRATION=true

# 启用文件上传处理
ENABLE_FILE_UPLOADS=true

# 启用快捷操作按钮
ENABLE_QUICK_ACTIONS=true
```

#### 监控与日志

```bash
# 日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL）
LOG_LEVEL=INFO

# 启用匿名遥测
ENABLE_TELEMETRY=false

# Sentry DSN 错误追踪
SENTRY_DSN=https://your-sentry-dsn@sentry.io/project
```

#### 开发配置

```bash
# 启用调试模式
DEBUG=false

# 启用开发功能
DEVELOPMENT_MODE=false

# 环境覆盖（development, testing, production）
ENVIRONMENT=development
```

#### Webhook（可选）

```bash
# Bot 的 Webhook URL（留空则使用轮询模式）
WEBHOOK_URL=https://your-domain.com/webhook

# Webhook 端口
WEBHOOK_PORT=8443

# Webhook 路径
WEBHOOK_PATH=/webhook
```

## 环境特定配置

Bot 会根据环境自动应用不同的设置：

### 开发环境

当 `ENVIRONMENT=development` 或 `DEBUG=true` 时激活：

- `debug = true`
- `development_mode = true`
- `log_level = "DEBUG"`
- `rate_limit_requests = 100`（更宽松）
- `claude_timeout_seconds = 600`（更长超时）
- `enable_telemetry = false`

### 测试环境

当 `ENVIRONMENT=testing` 时激活：

- `debug = true`
- `development_mode = true`
- `database_url = "sqlite:///:memory:"`（内存数据库）
- `approved_directory = "/tmp/test_projects"`
- `enable_telemetry = false`
- `claude_timeout_seconds = 30`（更快超时）
- `rate_limit_requests = 1000`（实质上无限流限制）
- `session_timeout_hours = 1`（短超时）

### 生产环境

当 `ENVIRONMENT=production` 时激活：

- `debug = false`
- `development_mode = false`
- `log_level = "INFO"`
- `enable_telemetry = true`
- `claude_max_cost_per_user = 5.0`（更严格的费用限制）
- `rate_limit_requests = 5`（更严格的限流）
- `session_timeout_hours = 12`（更短的会话超时）

## 功能开关

功能开关允许动态启用或禁用功能：

```python
from src.config import load_config, FeatureFlags

config = load_config()
features = FeatureFlags(config)

if features.git_enabled:
    # 启用 git 命令
    pass

if features.mcp_enabled:
    # 启用 Model Context Protocol
    pass
```

可用的功能开关：

- `mcp_enabled`：Model Context Protocol 支持
- `git_enabled`：Git 集成命令
- `file_uploads_enabled`：文件上传处理
- `quick_actions_enabled`：快捷操作按钮
- `telemetry_enabled`：匿名使用遥测
- `token_auth_enabled`：基于令牌的认证
- `webhook_enabled`：Webhook 模式（对比轮询模式）
- `development_features_enabled`：仅开发环境可用的功能

## 校验

配置系统会执行全面的校验：

### 路径校验

- `APPROVED_DIRECTORY` 必须存在且可访问
- `MCP_CONFIG_PATH` 在启用 MCP 时必须存在

### 跨字段校验

- `ENABLE_TOKEN_AUTH=true` 时需要 `AUTH_TOKEN_SECRET`
- `ENABLE_MCP=true` 时需要 `MCP_CONFIG_PATH`

### 值校验

- `LOG_LEVEL` 必须是以下之一：DEBUG, INFO, WARNING, ERROR, CRITICAL
- 数值型值在适用时必须为正数
- `ALLOWED_USERS` 中的用户 ID 必须是有效整数

## 代码中的配置加载

### 基本用法

```python
from src.config import load_config

# 自动环境检测加载
config = load_config()

# 访问配置
bot_token = config.telegram_token_str
max_cost = config.claude_max_cost_per_user
```

### 环境特定加载

```python
from src.config import load_config

# 显式加载生产环境配置
config = load_config(env="production")

# 检查是否运行在生产环境
if config.is_production:
    # 生产环境特定行为
    pass
```

### 测试配置

```python
from src.config import create_test_config

# 创建带覆盖值的测试配置
config = create_test_config(
    claude_max_turns=5,
    debug=True
)
```

## 故障排除

### 常见问题

1. **"Approved directory does not exist"**
   - 确保 `APPROVED_DIRECTORY` 中的路径存在
   - 使用绝对路径，不要用相对路径
   - 检查文件权限

2. **"auth_token_secret required"**
   - 使用 `ENABLE_TOKEN_AUTH=true` 时需设置 `AUTH_TOKEN_SECRET`
   - 生成安全密钥：`openssl rand -hex 32`

3. **"MCP config file does not exist"**
   - 确保 `MCP_CONFIG_PATH` 指向已存在的文件
   - 或使用 `ENABLE_MCP=false` 禁用 MCP

### 调试配置

查看加载了哪些配置：

```bash
export TELEGRAM_BOT_TOKEN=test
export TELEGRAM_BOT_USERNAME=test
export APPROVED_DIRECTORY=/tmp
make run-debug
```

这将显示配置加载和校验的详细日志。

## 安全注意事项

- **切勿将密钥提交**到版本控制
- **使用环境变量**存储敏感数据
- 如果使用令牌认证，**定期轮换令牌**
- 将 `APPROVED_DIRECTORY` **限制**在必要路径范围内
- **监控日志**以发现配置错误和安全事件

## Claude 集成选项

### SDK 模式与 CLI 模式

Bot 支持两种 Claude 集成方式：

1. **SDK 模式（默认）**：使用 Claude Code Python SDK 进行直接 API 集成
   - 更好的性能和流式传输支持
   - 可使用现有的 Claude CLI 认证或 API 密钥
   - 更可靠的错误处理

2. **CLI 模式**：使用 Claude Code CLI 子进程
   - 需要安装 Claude Code CLI
   - 仅使用 CLI 认证
   - 兼容性保留的传统模式

### 认证选项

#### 选项 1：使用现有 Claude CLI 认证（推荐）
```bash
# 安装并认证 Claude CLI
claude auth login

# 配置 bot 使用 SDK + CLI 认证
USE_SDK=true
# 不需要 ANTHROPIC_API_KEY — SDK 将使用 CLI 凭据
```

#### 选项 2：直接 API 密钥
```bash
# 使用 API 密钥配置 bot
USE_SDK=true
ANTHROPIC_API_KEY=sk-ant-api03-your-key-here
```

#### 选项 3：CLI 模式（传统）
```bash
# 使用 CLI 子进程替代 SDK
USE_SDK=false
# 需要安装并认证 Claude CLI
```

## .env 文件示例

```bash
# Telegram 配置
TELEGRAM_BOT_TOKEN=1234567890:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_BOT_USERNAME=my_claude_bot

# 安全配置
APPROVED_DIRECTORY=/home/user/projects
ALLOWED_USERS=123456789,987654321

# 可选：令牌认证
ENABLE_TOKEN_AUTH=false
AUTH_TOKEN_SECRET=

# Claude 集成
USE_SDK=true                          # 使用 Python SDK（推荐）
ANTHROPIC_API_KEY=                    # 可选：仅在不使用 CLI 认证时需要

# 限流
RATE_LIMIT_REQUESTS=10
RATE_LIMIT_WINDOW=60

# Claude 设置
CLAUDE_MAX_COST_PER_USER=10.0
CLAUDE_TIMEOUT_SECONDS=300
CLAUDE_ALLOWED_TOOLS=Read,Write,Edit,Bash,Glob,Grep,LS,Task,MultiEdit,NotebookRead,NotebookEdit,WebFetch,TodoRead,TodoWrite,WebSearch

# 存储与数据库
DATABASE_URL=sqlite:///data/bot.db
SESSION_TIMEOUT_HOURS=24
MAX_SESSIONS_PER_USER=5
DATA_RETENTION_DAYS=90

# 功能开关
ENABLE_GIT_INTEGRATION=true
ENABLE_FILE_UPLOADS=true
ENABLE_QUICK_ACTIONS=true

# 开发配置
DEBUG=false
LOG_LEVEL=INFO
```
