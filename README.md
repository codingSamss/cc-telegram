# CLI TG

通过 Telegram Bot 远程控制本地机器上运行的 CLI 编码智能体（支持 Claude、Codex 及未来的 CLI 引擎），实现手机端下达指令、查看结果的工作流。

基于 Python，使用 `python-telegram-bot` (Polling 模式) + `claude-agent-sdk`，无需 Cloudflare Tunnel、tmux 等外部依赖。启动即用。

## 架构概览

```
手机 Telegram App
    |  HTTPS (TLS 加密)
    v
Telegram Bot API 服务器
    |  Long Polling (Bot 主动拉取)
    v
本地 Python Bot 进程
    |  claude-agent-sdk async query()
    v
Claude Code (SDK 集成 / CLI 子进程 fallback)
    |  结果解析 + SQLite 存储
    v
Telegram 回复用户
```

Bot 使用 Long Polling 模式主动拉取消息，不需要公网 IP 或反向代理。Claude 集成采用双后端架构：SDK 为主、CLI 子进程兜底，SDK 失败时自动切换。

## 前置要求

- Python 3.10+ (推荐 3.11)
- [Poetry](https://python-poetry.org/) 包管理器
- Claude Code CLI (已登录认证)
- Telegram 账号

## 部署步骤

### Step 1: 安装系统依赖

```bash
# macOS
brew install python@3.11

# Poetry
curl -sSL https://install.python-poetry.org | python3 -

# Node.js (CLI fallback 模式需要)
brew install node
```

### Step 2: 创建 Telegram Bot

1. 在 Telegram 搜索 `@BotFather`，发送 `/newbot`
2. 按提示设置 Bot 名称，获得 **Bot Token** (格式: `1234567890:ABC-DEF...`)
3. 记下 Bot 用户名 (不带 `@`)
4. 获取你的 User ID: 向 `@userinfobot` 发消息，记下返回的数字

### Step 3: 克隆项目并安装依赖

```bash
git clone <repo-url> ~/cli-tg
cd ~/cli-tg
poetry install
```

### Step 4: 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填写以下必填项:

```bash
# === 必填 ===
TELEGRAM_BOT_TOKEN=<从 BotFather 获取>
TELEGRAM_BOT_USERNAME=<Bot 用户名，不带 @>
APPROVED_DIRECTORY=/path/to/your/projects

# === 安全 ===
ALLOWED_USERS=<你的 Telegram User ID>

# === CLI 引擎集成 ===
USE_SDK=false
CLAUDE_CLI_PATH=./claude-wrapper.sh
CLAUDE_MAX_TURNS=50
CLAUDE_TIMEOUT_SECONDS=600
```

完整配置项参考 `.env.example`。

### Step 5: 配置 claude-wrapper.sh

如果使用 CLI 子进程模式 (`USE_SDK=false`)，需要创建包装脚本:

```bash
cat > claude-wrapper.sh << 'EOF'
#!/bin/bash
# 根据需要配置代理 (不需要代理则删除以下三行)
export http_proxy="http://127.0.0.1:7897"
export https_proxy="http://127.0.0.1:7897"
export no_proxy="localhost,127.0.0.1"
exec /opt/homebrew/bin/npx -y @anthropic-ai/claude-code@latest "$@"
EOF
chmod +x claude-wrapper.sh
```

> 此脚本已在 `.gitignore` 中屏蔽，不会提交到仓库。根据你的环境修改代理地址和 `npx` 路径。

### Step 6: 确保 Claude CLI 已认证

```bash
# 安装 Claude Code CLI
npm install -g @anthropic-ai/claude-code

# 登录认证
claude auth login

# 验证状态
claude auth status
```

### Step 7: 启动

```bash
# 普通启动
make run

# 或 Debug 日志启动
make run-debug

# 或直接运行
poetry run python -m src.main
```

启动后在 Telegram 中给 Bot 发消息即可使用。

## 日常使用

### Bot 命令

| 命令 | 说明 |
|------|------|
| `/start` | 启动 Bot |
| `/help` | 查看帮助 |
| `/cd <path>` | 切换工作目录 |
| `/ls` | 列出当前目录文件 |
| `/pwd` | 显示当前目录 |
| `/projects` | 显示可用项目 |
| `/new` | 清除上下文，开始新会话 |
| `/status` | 查看 Bot 状态和用量 |
| `/git` | 查看 Git 仓库信息 |
| `/actions` | 显示快捷操作按钮 |
| `/export` | 导出会话记录 |

### 使用方式

- 直接发送文本消息 = 向 Claude Code 下达指令
- 发送文件 = Claude 分析文件内容 (支持代码、配置、文档)
- 发送图片 = Claude 分析截图/图表
- 会话按 用户+目录 维度自动保持，切换目录自动恢复对应会话

## 安全模型

5 层防御体系:

| 层级 | 机制 | 说明 |
|------|------|------|
| 身份认证 | Telegram User ID 白名单 | `ALLOWED_USERS` 配置 |
| 目录隔离 | `APPROVED_DIRECTORY` + 路径穿越防护 | 只允许访问指定目录及子目录 |
| 输入验证 | 屏蔽 `..`、`;`、`&&`、`$()` 等 | 阻止命令注入 |
| 限流 | Token Bucket 算法 | 可配置请求数/窗口/突发容量 |
| 审计日志 | 全操作记录 | 安全事件自动告警 |

> Telegram Bot 消息非端到端加密，经过 Telegram 服务器中转。不要通过 Bot 传递密码、API Key 等敏感信息。

## 故障排查

| 问题 | 原因 | 解决 |
|------|------|------|
| `ModuleNotFoundError` | 依赖未安装 | `poetry install` |
| `No such file: claude` | CLI 路径错误 | 检查 `.env` 中 `CLAUDE_CLI_PATH` |
| `Can't parse entities` | 消息格式解析失败 | 检查响应中的特殊字符转义 |
| `Authentication failed` | User ID 不在白名单 | 检查 `ALLOWED_USERS` |
| `Rate limit exceeded` | 请求过于频繁 | 调整 `RATE_LIMIT_*` 配置 |
| Bot 无响应 | Token 错误或进程未启动 | 检查 `TELEGRAM_BOT_TOKEN` 和进程状态 |

## 开发命令

```bash
make dev          # 安装所有依赖 (含开发依赖)
make install      # 仅安装生产依赖
make run          # 启动 Bot
make run-debug    # Debug 日志启动
make test         # 运行测试 + 覆盖率
make lint         # Black + isort + flake8 + mypy
make format       # 自动格式化代码
```

## 参考链接

- [python-telegram-bot 文档](https://docs.python-telegram-bot.org/)
- [claude-agent-sdk](https://pypi.org/project/claude-agent-sdk/)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [Poetry 文档](https://python-poetry.org/docs/)
