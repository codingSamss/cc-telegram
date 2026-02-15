# Systemd 用户服务配置指南

本指南介绍如何将 Claude Code Telegram Bot 作为持久化的 systemd 用户服务运行。

**安全提示：** 配置服务前，请确保 `.env` 文件中已设置 `DEVELOPMENT_MODE=false` 和 `ENVIRONMENT=production` 以保证安全运行。

## 快速配置

### 1. 创建服务文件

```bash
mkdir -p ~/.config/systemd/user
nano ~/.config/systemd/user/cli-tg.service
```

添加以下内容：

```ini
[Unit]
Description=Claude Code Telegram Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/ubuntu/Code/oss/claude-code-telegram
ExecStart=/home/ubuntu/.local/bin/poetry run cli-tg
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Environment
Environment="PATH=/home/ubuntu/.local/bin:/usr/local/bin:/usr/bin:/bin"

[Install]
WantedBy=default.target
```

**注意：** 请将 `WorkingDirectory` 更新为你的项目路径。

### 2. 启用并启动服务

```bash
# 重新加载 systemd 以识别新服务
systemctl --user daemon-reload

# 启用开机自启
systemctl --user enable cli-tg.service

# 立即启动服务
systemctl --user start cli-tg.service
```

### 3. 验证运行状态

```bash
systemctl --user status cli-tg
```

### 4. 验证安全配置

检查服务是否以生产模式运行：

```bash
# 检查日志中的环境模式
journalctl --user -u cli-tg -n 50 | grep -i "environment\|development"

# 应该显示：
# "environment": "production"
# "development_mode": false（如果为 false 则不显示）

# 验证认证是否受限
journalctl --user -u cli-tg -n 50 | grep -i "auth"

# 应该显示：
# "allowed_users": 1（如果配置了多个用户则更多）
# "allow_all_dev": false
```

如果看到 `allow_all_dev: true` 或 `environment: development`，请**立即停止服务**并修复 `.env` 文件。

## 常用命令

```bash
# 启动服务
systemctl --user start cli-tg

# 停止服务
systemctl --user stop cli-tg

# 重启服务
systemctl --user restart cli-tg

# 查看状态
systemctl --user status cli-tg

# 查看实时日志
journalctl --user -u cli-tg -f

# 查看最近日志（最后 50 行）
journalctl --user -u cli-tg -n 50

# 禁用自启动
systemctl --user disable cli-tg

# 启用自启动
systemctl --user enable cli-tg
```

## 更新服务

编辑服务文件后：

```bash
systemctl --user daemon-reload
systemctl --user restart cli-tg
```

## 故障排除

**服务无法启动：**
```bash
# 检查日志中的错误
journalctl --user -u cli-tg -n 100

# 验证服务文件中的路径是否正确
systemctl --user cat cli-tg

# 检查 Poetry 是否已安装
poetry --version

# 先手动测试 bot
cd /home/ubuntu/Code/oss/claude-code-telegram
poetry run cli-tg
```

**注销后服务停止：**

启用 lingering 以在注销后保持用户服务运行：
```bash
loginctl enable-linger $USER
```

## 相关文件

- 服务文件：`~/.config/systemd/user/cli-tg.service`
- 日志：使用 `journalctl --user -u cli-tg` 查看
- 项目目录：`/home/ubuntu/Code/oss/claude-code-telegram`
