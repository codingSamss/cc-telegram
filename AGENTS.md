# Repository Guidelines

## 项目结构与模块组织
核心代码位于 `src/`，按职责分层：`config/`（配置加载与环境覆盖）、`security/`（鉴权与限流）、`bot/`（Telegram 交互与处理器）、`claude/`（Claude 集成）、`storage/`（SQLite 与仓储模式）、`utils/`（常量与通用工具）。入口为 `src/main.py`。  
测试代码位于 `tests/`，当前以 `tests/unit/` 为主，目录结构尽量镜像 `src/`。文档在 `docs/`，运维与部署相关说明见 `README.md`、`SECURITY.md`、`SYSTEMD_SETUP.md`。

## 构建、测试与开发命令
 - `make dev`：安装开发依赖（Poetry）并尝试安装提交钩子。
 - `make install`：仅安装生产依赖。
 - `make run`：启动机器人。
 - `make run-debug`：调试模式启动，输出更详细日志。
 - `make test`：运行 `pytest` 与覆盖率统计。
 - `make lint`：执行 `black --check`、`isort --check-only`、`flake8`、`mypy`。
 - `make format`：自动格式化 `src` 与 `tests`。

## 重启服务
本仓库在 macOS 上通常没有 systemd，推荐使用项目内脚本重启：
1. `./scripts/restart-bot.sh`（在项目根目录下执行），这个脚本会 `pkill -f cli-tg` 并接着 `poetry run claude-telegram-bot` 启动最新版本（对 Claude CLI 与 Codex CLI 都生效）。
2. 如需后台运行，请在 `tmux`/`screen` 里执行脚本，或在脚本命令前加 `nohup`/`setsid`。
3. 每次我在 TG 上修改代码后只需重复一次脚本调用即完成“重启服务”。

## 代码风格与命名约定
使用 Python 3.10+，统一 4 空格缩进，行宽 88（Black 规则）。导入顺序由 isort（与 Black 兼容配置）管理。  
命名规范：模块/函数使用 `snake_case`，类使用 `PascalCase`，常量使用 `UPPER_SNAKE_CASE`。  
类型标注为强制要求（mypy 开启 `disallow_untyped_defs`），新增或修改接口时必须补齐类型。优先复用 `src/exceptions.py` 中的异常层级与结构化日志模式。

## 测试指南
测试框架为 `pytest` + `pytest-asyncio` + `pytest-cov`。测试文件命名使用 `test_*.py`，测试函数使用 `test_*`。异步用例显式添加 `@pytest.mark.asyncio`。  
执行 `make test` 后查看终端缺失覆盖率报告与 `htmlcov/`。项目当前总体覆盖率约 85%，新增变更应避免拉低覆盖率（建议保持在 80% 以上）。

## 提交与合并请求规范
提交信息遵循约定式提交（Conventional Commits），历史中常见前缀：`feat:`、`fix:`、`refactor:`、`docs:`、`test:`、`chore:`。示例：`feat: add session export command`。  
发起合并请求（Pull Request）时请包含：变更目的、关联 Issue、测试结果（至少 `make test` 与 `make lint`）、必要文档更新。若变更影响 Telegram 交互流程，附上关键聊天截图或日志片段。

## 安全与配置提示
从 `.env.example` 复制生成 `.env`，严禁提交令牌、密钥或真实凭据。重点检查 `ALLOWED_USERS` 与 `APPROVED_DIRECTORY`，避免越权访问。涉及 Claude 命令执行路径时，优先使用本地 `claude-wrapper.sh` 并在提交前确认未泄露敏感配置。
