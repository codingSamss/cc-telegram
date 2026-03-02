# 配置指南（当前实现）

本文档只描述当前代码实际支持的配置项。权威来源：
- `src/config/settings.py`
- `.env.example`

## 1. 最小必需配置

```bash
TELEGRAM_BOT_TOKEN=<BotFather token>
TELEGRAM_BOT_USERNAME=<bot username without @>
APPROVED_DIRECTORY=<absolute path>
ALLOWED_USERS=<telegram user id, comma-separated>
```

说明：
- `ALLOWED_USERS` 为空时，应用会 fail-closed，启动失败。
- 当前认证仅支持白名单，不支持 token 认证模式。

## 2. 引擎相关配置

### Claude（默认）

```bash
USE_SDK=true
SDK_ENABLE_TOOL_PERMISSION_GATE=false
ANTHROPIC_API_KEY=
CLAUDE_CLI_PATH=
CLAUDE_BINARY_PATH=
CLAUDE_SETTING_SOURCES=user,project,local
CLAUDE_MODEL=claude-3-5-sonnet-20241022
CLAUDE_MAX_TURNS=10
CLAUDE_TIMEOUT_SECONDS=300
CLAUDE_ALLOWED_TOOLS=
CLAUDE_DISALLOWED_TOOLS=git commit,git push
```

### Codex（可选）

```bash
ENABLE_CODEX_CLI=false
CODEX_CLI_PATH=
CODEX_ENABLE_MCP=true
```

说明：
- 启用 Codex 后，可通过 `/engine codex` 切换。
- `CODEX_ENABLE_MCP=true` 为默认值，更接近本机 Codex CLI 行为；如需严格禁用 MCP，再显式设为 `false`。
- `CLAUDE_BINARY_PATH` 为兼容字段，通常与 `CLAUDE_CLI_PATH` 保持一致或留空。
- `CLAUDE_ALLOWED_TOOLS` 为空时，不向 CLI 传 `--allowedTools`，可继承本机 Claude 配置。
- `CLAUDE_SETTING_SOURCES` 默认推荐 `user,project,local`；若你的网关拒绝显式 sources，再临时留空排障。

## 3. 会话与运行时配置

```bash
DATABASE_URL=sqlite:///data/bot.db
SESSION_TIMEOUT_HOURS=24
SESSION_TIMEOUT_MINUTES=120
MAX_SESSIONS_PER_USER=5
RESUME_SCAN_CACHE_TTL_SECONDS=30
RESUME_HISTORY_PREVIEW_COUNT=6
STREAM_RENDER_DEBOUNCE_MS=1000
STREAM_RENDER_MIN_EDIT_INTERVAL_MS=1000
STATUS_REACTIONS_ENABLED=true
STATUS_REACTION_DEBOUNCE_MS=700
STATUS_REACTION_STALL_SOFT_MS=10000
STATUS_REACTION_STALL_HARD_MS=30000
STATUS_CONTEXT_PROBE_TTL_SECONDS=0
STATUS_CONTEXT_PROBE_TIMEOUT_SECONDS=45
IMAGE_CLEANUP_MAX_AGE_HOURS=24
```

## 4. 功能开关

```bash
ENABLE_MCP=false
MCP_CONFIG_PATH=
ENABLE_GIT_INTEGRATION=true
ENABLE_FILE_UPLOADS=true
ENABLE_QUICK_ACTIONS=false
```

说明：
- `ENABLE_MCP` 仅控制“应用侧通过 `MCP_CONFIG_PATH` 显式注入 MCP”。
- 即使 `ENABLE_MCP=false`，Claude 仍可从 `user/project/local` 配置源加载其自身 MCP 设置。

## 5. 监控与环境

```bash
LOG_LEVEL=INFO
ENABLE_TELEMETRY=false
SENTRY_DSN=
ENVIRONMENT=development
DEBUG=false
DEVELOPMENT_MODE=true
```

## 6. Webhook（可选）

```bash
WEBHOOK_URL=
WEBHOOK_PORT=8443
WEBHOOK_PATH=/webhook
```

为空时默认使用 long polling。

## 7. 环境覆盖规则

基于 `src/config/environments.py`：
- `development`：`debug=true`、`development_mode=true`、`log_level=DEBUG`、`claude_timeout_seconds=600`
- `testing`：`debug=true`、`development_mode=true`、`database_url=sqlite:///:memory:`、`claude_timeout_seconds=30`
- `production`：`debug=false`、`development_mode=false`、`log_level=INFO`、`session_timeout_hours=12`

## 8. 已移除配置（不要再使用）

以下配置项在当前实现中已移除：
- `ENABLE_TOKEN_AUTH`
- `AUTH_TOKEN_SECRET`
- `RATE_LIMIT_REQUESTS`
- `RATE_LIMIT_WINDOW`
- `RATE_LIMIT_BURST`
- `CLAUDE_MAX_COST_PER_USER`
- `MAX_FILE_UPLOAD_SIZE_MB`
- `MAX_ARCHIVE_PREVIEW_FILES`
- `ENABLE_SESSION_EXPORT`
- `ENABLE_IMAGE_UPLOADS`
- `ENABLE_CONVERSATION_MODE`
- `QUICK_ACTIONS_TIMEOUT`
- `GIT_OPERATIONS_TIMEOUT`

## 9. 常见问题

1. `No authentication providers configured`
- 原因：`ALLOWED_USERS` 未配置或解析为空
- 处理：设置有效的用户 ID 列表

2. `ENABLE_CODEX_CLI is true but codex binary not found`
- 原因：Codex CLI 不在 PATH 且未设置 `CODEX_CLI_PATH`
- 处理：安装 Codex CLI 或指定绝对路径

3. `invalid claude code request`
- 原因：部分网关与显式 setting sources 不兼容
- 处理：先将 `CLAUDE_SETTING_SOURCES` 留空（默认推荐值仍为 `user,project,local`）
