# CLITG

Telegram Bot for Claude Code - 通过 Telegram 远程操控 Claude Code，支持 Claude/Codex 双引擎切换、多会话、图片分析、MCP 集成、流式输出。

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

# 可选：开启 Codex 引擎适配
ENABLE_CODEX_CLI=true
CODEX_CLI_PATH=

# 建议默认 false，避免 MCP 启动卡顿；需要 MCP 工具时再临时打开
CODEX_ENABLE_MCP=false
```

完整配置项参考 `.env.example`。

### Step 5: 配置 claude-wrapper.sh

如果使用 CLI 子进程模式 (`USE_SDK=false`)，建议从模板复制：

```bash
cp claude-wrapper.example.sh claude-wrapper.sh
chmod +x claude-wrapper.sh
```

然后按你的本机环境修改 `claude-wrapper.sh`（例如代理地址、CLI 路径）。  
本地 `claude-wrapper.sh` 保持在 `.gitignore` 中，避免把机器相关配置提交到仓库。

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

### Bot 命令（与当前版本同步）

| 命令 | 说明 | 适用引擎 |
|------|------|------|
| `/start` | 显示欢迎页与快捷入口 | 全部 |
| `/help` | 查看完整命令说明 | 全部 |
| `/engine [claude|codex]` | 切换 CLI 引擎（也可不带参数走按钮） | 全部 |
| `/resume` | 恢复桌面端最近会话 | 全部 |
| `/new` | 清除当前绑定并新建会话 | 全部 |
| `/continue [message]` | 显式续接当前会话 | 全部 |
| `/end` | 结束当前会话 | 全部 |
| `/context [full]` | 查看会话上下文与用量 | 全部（Claude 主展示） |
| `/status [full]` | `/context` 的兼容别名 | 全部（Codex 主展示） |
| `/model` | Claude：按钮切换 Sonnet/Opus/Haiku | Claude |
| `/model [name|default]` | Codex：设置/清除 `--model` | Codex |
| `/codexdiag [root|<session_id>]` | 诊断 Codex MCP 调用情况 | Codex |
| `/cd <path>` | 切换目录（带安全校验） | 全部 |
| `/ls` | 列出当前目录内容 | 全部 |
| `/pwd` | 查看当前目录 | 全部 |
| `/projects` | 显示可用项目 | 全部 |
| `/git` | Git 仓库信息与操作入口 | 全部 |
| `/actions` | 快捷动作菜单 | 全部 |
| `/export` | 导出当前会话 | 全部 |
| `/cancel` | 取消当前运行中的任务 | 全部 |

### 使用方式

- 直接发送文本消息 = 向当前引擎（Claude/Codex）下达指令
- 发送文件 = 由当前引擎分析文件内容（支持代码、配置、文档）
- 发送图片 = 引擎分析截图/图表（能力取决于当前引擎与模式）
- 会话按“用户 + 会话作用域（私聊/群聊话题）+ 目录”维护
- 引擎切换后会清理旧会话绑定，并引导你重新选择目录与可恢复会话

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
| `Claude process error: exit code 1` | 常见于引擎/模型不匹配 | 先 `/engine claude`，再 `/model` 选 Claude 模型或执行 `/model default` |
| `invalid claude code request` | SDK 显式 setting sources 与网关不兼容 | 保持 `CLAUDE_SETTING_SOURCES` 为空；若需要强制来源再设为 `user,project,local` |

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
