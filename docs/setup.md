# 安装与配置指南

本指南提供 Claude Code Telegram Bot 的完整安装说明，涵盖 CLI 和 SDK 两种集成模式。

## 快速开始

### 1. 前置条件

- **Python 3.9+** - [点此下载](https://www.python.org/downloads/)
- **Poetry** - 现代 Python 依赖管理工具
- **Telegram Bot Token** - 从 [@BotFather](https://t.me/botfather) 获取
- **Claude 认证** - 从下方选择一种方式

### 2. Claude 认证配置

Bot 支持两种 Claude 集成模式，请根据需求选择：

#### 方式 A：SDK + CLI 认证（推荐）

此方式使用 Python SDK 获得更好的性能，同时复用已有的 Claude CLI 认证。

```bash
# 1. 安装 Claude CLI
# 访问 https://claude.ai/code 并按照说明安装

# 2. 完成 Claude 认证
claude auth login

# 3. 验证认证状态
claude auth status
# 应显示："✓ You are authenticated"

# 4. 配置 bot（见下方第 4 步）
USE_SDK=true
# 不填 ANTHROPIC_API_KEY - SDK 会使用 CLI 凭据
```

**优点：**
- 性能最佳，原生异步支持
- 使用已有的 Claude CLI 认证
- 更好的流式传输和错误处理
- 无需单独管理 API Key

**缺点：**
- 需要安装 Claude CLI

#### 方式 B：SDK + 直接 API Key

此方式使用 Python SDK 配合直接 API Key，无需安装 Claude CLI。

```bash
# 1. 从 https://console.anthropic.com/ 获取 API Key
# 2. 配置 bot（见下方第 4 步）
USE_SDK=true
ANTHROPIC_API_KEY=sk-ant-api03-your-key-here
```

**优点：**
- 无需安装 Claude CLI
- 直接 API 集成
- 良好的异步支持性能

**缺点：**
- 需要手动管理 API Key
- 需处理 API Key 的管理与轮换

#### 方式 C：CLI 子进程模式（传统方式）

此方式将 Claude CLI 作为子进程调用。仅在需要兼容旧有配置时使用。

```bash
# 1. 安装 Claude CLI
# 访问 https://claude.ai/code 并按照说明安装

# 2. 完成 Claude 认证
claude auth login

# 3. 配置 bot（见下方第 4 步）
USE_SDK=false
# CLI 模式不需要 ANTHROPIC_API_KEY
```

**优点：**
- 使用官方 Claude CLI
- 兼容所有 CLI 功能

**缺点：**
- 比 SDK 集成慢
- 子进程开销
- 错误处理不够可靠

### 3. 安装 Bot

```bash
# 克隆仓库
git clone https://github.com/yourusername/claude-code-telegram.git
cd claude-code-telegram

# 安装 Poetry（如需要）
curl -sSL https://install.python-poetry.org | python3 -

# 安装依赖
make dev
```

### 4. 配置环境变量

```bash
# 复制示例配置文件
cp .env.example .env

# 编辑配置
nano .env
```

**必需的配置项：**

```bash
# Telegram Bot 设置
TELEGRAM_BOT_TOKEN=1234567890:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_BOT_USERNAME=your_bot_username

# 安全设置
APPROVED_DIRECTORY=/path/to/your/projects
ALLOWED_USERS=123456789  # 你的 Telegram 用户 ID

# Claude 集成（根据上方选择的认证方式配置）
USE_SDK=true                          # true 使用 SDK，false 使用 CLI
ANTHROPIC_API_KEY=                    # 仅在使用方式 B 时需要
```

### 5. 获取你的 Telegram 用户 ID

配置 `ALLOWED_USERS` 的方法：

1. 在 Telegram 上向 [@userinfobot](https://t.me/userinfobot) 发送消息
2. 它会回复你的用户 ID 数字
3. 将此数字添加到 `ALLOWED_USERS` 配置中

### 6. 运行 Bot

```bash
# 以调试模式启动（首次运行推荐）
make run-debug

# 或以生产模式启动
make run
```

### 7. 测试 Bot

1. 在 Telegram 中搜索你的 bot 用户名
2. 发送 `/start` 开始使用
3. 尝试简单命令如 `/pwd` 或 `/ls`
4. 用一个简单问题测试 Claude 集成

## 高级配置

### 认证方式对比

| 特性 | SDK + CLI 认证 | SDK + API Key | CLI 子进程 |
|------|----------------|---------------|------------|
| 性能 | 最佳 | 最佳 | 较慢 |
| 配置复杂度 | 中等 | 简单 | 中等 |
| 是否需要 CLI | 是 | 否 | 是 |
| API Key 管理 | 否 | 是 | 否 |
| 流式传输支持 | 是 | 是 | 有限 |
| 错误处理 | 最佳 | 最佳 | 基础 |

### 安全注意事项

#### 目录隔离
```bash
# 设置为具体的项目目录，而非你的 home 目录
APPROVED_DIRECTORY=/Users/yourname/projects

# Bot 只能访问此目录下的文件
# 这可以防止访问敏感的系统文件
```

#### 用户访问控制
```bash
# 方式 1：白名单指定用户（推荐）
ALLOWED_USERS=123456789,987654321

# 方式 2：令牌认证
ENABLE_TOKEN_AUTH=true
AUTH_TOKEN_SECRET=your-secret-key-here  # 生成方式：openssl rand -hex 32
```

### 限流配置

```bash
# 通过限流防止滥用
RATE_LIMIT_REQUESTS=10          # 每个时间窗口的请求数
RATE_LIMIT_WINDOW=60            # 时间窗口（秒）
RATE_LIMIT_BURST=20             # 突发容量

# 基于费用的限制
CLAUDE_MAX_COST_PER_USER=10.0   # 每用户最大费用（美元）
```

### 开发环境配置

用于开发工作：

```bash
# 开发专用设置
DEBUG=true
DEVELOPMENT_MODE=true
LOG_LEVEL=DEBUG
ENVIRONMENT=development

# 更宽松的限流，方便测试
RATE_LIMIT_REQUESTS=100
CLAUDE_TIMEOUT_SECONDS=600
```

## 常见问题排查

### 常见配置问题

#### Bot 没有响应
```bash
# 检查 bot token
echo $TELEGRAM_BOT_TOKEN

# 验证用户 ID 是否正确
# 向 @userinfobot 发消息获取你的 ID

# 查看 bot 日志
make run-debug
```

#### Claude 认证问题

**SDK + CLI 认证模式：**
```bash
# 检查 CLI 认证状态
claude auth status

# 应显示："✓ You are authenticated"
# 如果不是，运行：claude auth login
```

**SDK + API Key 模式：**
```bash
# 验证 API Key 已设置
echo $ANTHROPIC_API_KEY

# 应以 sk-ant-api03- 开头
# 从 https://console.anthropic.com/ 获取新 Key
```

**CLI 模式：**
```bash
# 检查 CLI 安装
claude --version

# 检查认证状态
claude auth status

# 测试 CLI 是否正常工作
claude "Hello, can you help me?"
```

#### 权限错误
```bash
# 检查受批准目录是否存在且可访问
ls -la /path/to/your/projects

# 验证 bot 进程具有读写权限
# 该目录应由运行 bot 的用户拥有
```

### 性能优化

#### SDK 模式
```bash
# SDK 集成的最佳设置
USE_SDK=true
CLAUDE_TIMEOUT_SECONDS=300
CLAUDE_MAX_TURNS=20
```

#### CLI 模式
```bash
# 如果必须使用 CLI 模式，优化以下设置
USE_SDK=false
CLAUDE_TIMEOUT_SECONDS=450      # 子进程开销需要更长超时
CLAUDE_MAX_TURNS=10             # 减少轮数以降低子进程调用
```

### 监控与日志

#### 启用详细日志
```bash
LOG_LEVEL=DEBUG
DEBUG=true

# 以调试模式运行
make run-debug
```

#### 监控使用量与费用
```bash
# 在 Telegram 中查看使用情况
/status

# 监控日志中的费用追踪
tail -f logs/bot.log | grep -i cost
```

## 生产部署

### 环境特定设置

```bash
# 生产配置
ENVIRONMENT=production
DEBUG=false
LOG_LEVEL=INFO
DEVELOPMENT_MODE=false

# 更严格的限流
RATE_LIMIT_REQUESTS=5
CLAUDE_MAX_COST_PER_USER=5.0
SESSION_TIMEOUT_HOURS=12

# 启用监控
ENABLE_TELEMETRY=true
SENTRY_DSN=https://your-sentry-dsn@sentry.io/project
```

### 数据库配置

```bash
# 生产环境使用持久化的数据库路径
DATABASE_URL=sqlite:///var/lib/claude-telegram/bot.db

# 或使用 PostgreSQL 用于大规模部署
# DATABASE_URL=postgresql://user:pass@localhost/claude_telegram
```

### 安全加固

```bash
# 启用令牌认证以增强安全性
ENABLE_TOKEN_AUTH=true
AUTH_TOKEN_SECRET=your-very-secure-secret-key

# 仅允许特定用户
ALLOWED_USERS=123456789,987654321

# 使用受限的项目目录
APPROVED_DIRECTORY=/opt/projects
```

## 获取帮助

- **文档**：查看主 [README.md](../README.md)
- **配置**：查看 [configuration.md](configuration.md) 了解所有选项
- **开发**：查看 [development.md](development.md) 了解开发配置
- **问题反馈**：[提交 Issue](https://github.com/yourusername/claude-code-telegram/issues)
- **安全**：查看 [SECURITY.md](../SECURITY.md) 了解安全相关事项
