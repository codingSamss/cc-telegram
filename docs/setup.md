# 安装与启动（当前实现）

本指南按当前代码实现整理，适用于 CLITG（Claude/Codex 双引擎 Telegram Bot）。

## 1. 前置条件

- Python 3.10+（推荐 3.11）
- Poetry
- Telegram Bot Token（BotFather）
- 你的 Telegram 用户 ID（`@userinfobot`）
- Claude CLI（推荐）或 Anthropic API Key（二选一）
- 可选：Codex CLI（如需 Codex 引擎）

## 2. 安装项目

```bash
git clone <repo-url> ~/cli-tg
cd ~/cli-tg
poetry install
```

## 3. 配置 `.env`

```bash
cp .env.example .env
```

最小可运行配置：

```bash
TELEGRAM_BOT_TOKEN=<BotFather token>
TELEGRAM_BOT_USERNAME=<bot username without @>
APPROVED_DIRECTORY=<absolute path>
ALLOWED_USERS=<your telegram user id>
USE_SDK=true
```

### Claude 认证方式

1. Claude CLI 凭据（推荐）
```bash
claude auth login
USE_SDK=true
ANTHROPIC_API_KEY=
```

2. API Key
```bash
USE_SDK=true
ANTHROPIC_API_KEY=sk-ant-api03-...
```

3. Claude CLI 子进程模式（兼容）
```bash
USE_SDK=false
```

## 4. 可选启用 Codex

```bash
ENABLE_CODEX_CLI=true
CODEX_CLI_PATH=  # 可留空，默认走 PATH
CODEX_ENABLE_MCP=false
```

启动后在 Telegram 中执行：
```text
/engine codex
```

## 5. 启动命令

```bash
make run
# 或
make run-debug
# 或
poetry run cli-tg-bot --debug
```

兼容旧别名（不推荐）：
```bash
poetry run claude-telegram-bot --debug
```

## 6. 运行后验证

1. Telegram 中发送 `/help`，确认有响应
2. 执行 `/projects`、`/status` 验证基础命令
3. 如启用 Codex，执行 `/engine codex` 后再发一条普通消息验证链路
4. 执行 `/engine claude` 切回默认引擎

## 7. macOS 推荐重启方式（tmux）

```bash
tmux kill-session -t cli_tg_bot
tmux new-session -d -s cli_tg_bot -c /Users/suqi3/PycharmProjects/cli-tg './scripts/restart-bot.sh'
ps -Ao pid,ppid,command | rg -i 'cli-tg-bot|claude-telegram-bot|src.main' | rg -v 'rg -i'
tmux capture-pane -t cli_tg_bot -p | tail -n 80
```

## 8. 常见问题

1. 启动报 `No authentication providers configured`
- 检查 `ALLOWED_USERS` 是否为空

2. `ENABLE_CODEX_CLI is true but codex binary not found`
- 安装 Codex CLI 或配置 `CODEX_CLI_PATH`

3. Telegram 在线但无响应
- 先确认单实例运行，再检查代理环境与重启脚本日志

## 9. 重要说明

- 当前认证仅支持白名单（`ALLOWED_USERS`）。
- 文档中的配置细节以 `.env.example` 与 `src/config/settings.py` 为最终准则。
