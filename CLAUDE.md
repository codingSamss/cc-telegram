# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在本仓库中工作时提供指引。

## 项目概述

Telegram bot，提供对 Claude Code 的远程访问。Python 3.10+，使用 Poetry 构建，`python-telegram-bot` 处理 Telegram 交互，`claude-agent-sdk` 处理 Claude Code 集成。

## 命令

```bash
make dev              # 安装所有依赖（含开发依赖）
make install          # 仅安装生产依赖
make run              # 运行 bot
make run-debug        # 以调试日志模式运行
make test             # 运行测试并生成覆盖率
make lint             # Black + isort + flake8 + mypy
make format           # 使用 black + isort 自动格式化

# 运行单个测试
poetry run pytest tests/unit/test_config.py -k test_name -v

# 仅类型检查
poetry run mypy src
```

## 架构

### 双 Claude 集成（SDK 优先，CLI 回退）

`ClaudeIntegration`（门面层，位于 `src/claude/facade.py`）封装两个后端：
- **`ClaudeSDKManager`**（`src/claude/sdk_integration.py`）— 主要方式。使用 `claude-agent-sdk` 异步 `query()` 和流式传输。会话 ID 来自 Claude 的 `ResultMessage`，而非本地生成。
- **`ClaudeProcessManager`**（`src/claude/integration.py`）— 传统 CLI 子进程回退方式。在 SDK 出现 JSON 解码或 TaskGroup 错误时使用。

会话自动恢复：按用户+目录维度，持久化到 SQLite，临时 ID（`temp_*`）不会发送给 Claude 用于恢复。

### 请求流程

```
Telegram 消息 → 安全中间件 (group -3) → 认证中间件 (group -2)
→ 限流 (group -1) → 命令/消息处理器 (group 10)
→ ClaudeIntegration.run_command() → SDK（带 CLI 回退）
→ 响应解析 → 存入 SQLite → 返回 Telegram
```

### 依赖注入

Bot 处理器通过 `context.bot_data` 访问依赖：
```python
context.bot_data["auth_manager"]
context.bot_data["claude_integration"]
context.bot_data["storage"]
context.bot_data["security_validator"]
```

### 关键目录

- `src/config/` — Pydantic Settings v2 配置，带环境检测、功能开关（`features.py`）
- `src/bot/handlers/` — Telegram 命令、消息和回调处理器
- `src/bot/middleware/` — 认证、限流、安全输入验证
- `src/bot/features/` — Git 集成、文件处理、快捷操作、会话导出
- `src/claude/` — Claude 集成门面层、SDK/CLI 管理器、会话管理、工具监控
- `src/storage/` — 基于 aiosqlite 的 SQLite，仓储模式（users、sessions、messages、tool_usage、audit_log、cost_tracking）
- `src/security/` — 多提供者认证（白名单 + 令牌）、输入验证器、限流器、审计日志

### 安全模型

5 层纵深防御：认证（白名单/令牌）→ 目录隔离（APPROVED_DIRECTORY + 路径遍历防护）→ 输入验证（阻止 `..`、`;`、`&&`、`$()`等）→ 限流（令牌桶）→ 审计日志。

`SecurityValidator` 阻止访问敏感文件（`.env`、`.ssh`、`id_rsa`、`.pem`）和危险 shell 模式。

### 配置

配置通过 Pydantic Settings 从环境变量加载。必需项：`TELEGRAM_BOT_TOKEN`、`TELEGRAM_BOT_USERNAME`、`APPROVED_DIRECTORY`。重要可选项：`ALLOWED_USERS`（逗号分隔的 Telegram ID）、`USE_SDK`（默认 true）、`ANTHROPIC_API_KEY`、`ENABLE_MCP`、`MCP_CONFIG_PATH`。

功能开关位于 `src/config/features.py`，控制：MCP、Git 集成、文件上传、快捷操作、会话导出、图片上传、对话模式。

## 代码风格

- Black（88 字符行宽）、isort（black 配置）、flake8、mypy 严格模式
- pytest-asyncio，`asyncio_mode = "auto"`
- structlog 用于所有日志（生产 JSON，开发控制台）
- 所有函数必须添加类型标注（`disallow_untyped_defs = true`）

## 添加新 Bot 命令

1. 在 `src/bot/handlers/command.py` 中添加处理函数
2. 在 `src/bot/core.py` 的 `_register_handlers()` 中注册
3. 添加到 `_set_bot_commands()` 以显示在 Telegram 命令菜单中
4. 为该命令添加审计日志
