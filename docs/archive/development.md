# 开发指南

本文档为参与 Claude Code Telegram Bot 开发的开发者提供详细信息。

## 快速上手

### 前置条件

- Python 3.9 或更高版本
- Poetry 依赖管理工具
- Git 版本控制
- Claude 认证（以下任选其一）：
  - 已安装并完成认证的 Claude Code CLI
  - 用于直接调用 SDK 的 Anthropic API Key

### 初始配置

1. **克隆仓库**：
   ```bash
   git clone <repository-url>
   cd claude-code-telegram
   ```

2. **安装 Poetry**（如尚未安装）：
   ```bash
   pip install poetry
   ```

3. **安装依赖**：
   ```bash
   make dev
   ```

4. **配置 pre-commit 钩子**（可选但推荐）：
   ```bash
   poetry run pre-commit install
   ```

5. **创建配置文件**：
   ```bash
   cp .env.example .env
   # 编辑 .env，填入你的开发环境配置
   ```

## 开发工作流

### 日常开发

1. **激活 Poetry 环境**：
   ```bash
   poetry shell
   ```

2. **在开发过程中持续运行测试**：
   ```bash
   make test
   ```

3. **提交前格式化代码**：
   ```bash
   make format
   ```

4. **检查代码质量**：
   ```bash
   make lint
   ```

### 可用的 Make 命令

```bash
make help          # 显示所有可用命令
make install       # 仅安装生产依赖
make dev           # 安装所有依赖（含开发工具）
make test          # 运行完整测试套件并统计覆盖率
make lint          # 运行所有代码质量检查
make format        # 自动格式化所有代码
make clean         # 清理生成的文件
make run           # 以正常模式运行 bot
make run-debug     # 以调试日志模式运行 bot
```

## 项目架构

### 包结构

```
src/
├── config/           # 配置管理（已完成）
│   ├── __init__.py
│   ├── settings.py   # Pydantic Settings 类
│   ├── loader.py     # 环境检测与加载
│   ├── environments.py # 环境特定覆盖配置
│   └── features.py   # 功能开关管理
├── bot/              # Telegram bot 实现（已完成）
│   ├── __init__.py
│   ├── core.py       # Bot 主类
│   ├── handlers/     # 命令与消息处理器
│   ├── middleware/   # 认证与限流
│   └── utils/        # 响应格式化工具
├── claude/           # Claude Code 集成（已完成）
│   ├── __init__.py
│   ├── integration.py # 子进程管理
│   ├── parser.py     # 输出解析与格式化
│   ├── session.py    # 会话管理
│   ├── monitor.py    # 工具使用监控
│   ├── facade.py     # 高层集成 API
│   └── exceptions.py # Claude 专用异常
├── storage/          # 数据库与持久化（已完成）
│   ├── __init__.py
│   ├── database.py   # 数据库连接与迁移
│   ├── models.py     # 类型安全的数据模型
│   ├── repositories.py # 仓储模式的数据访问
│   ├── facade.py     # 存储门面接口
│   └── session_storage.py # 持久化会话存储
├── security/         # 认证与安全（已完成）
│   ├── __init__.py
│   ├── auth.py       # 认证逻辑
│   ├── validators.py # 输入校验
│   └── rate_limiter.py # 限流
├── utils/            # 工具与常量（已完成）
│   ├── __init__.py
│   └── constants.py  # 应用常量
├── exceptions.py     # 自定义异常层级（已完成）
└── main.py          # 应用入口（已完成）
```

### 测试结构

```
tests/
├── unit/             # 单元测试（目录结构镜像 src）
│   ├── test_config.py
│   ├── test_environments.py
│   ├── test_exceptions.py
│   ├── test_bot/     # Bot 组件测试
│   ├── test_claude/  # Claude 集成测试
│   ├── test_security/ # 安全框架测试
│   └── test_storage/ # 存储层测试
├── integration/      # 集成测试（待完成）
├── fixtures/         # 测试数据与夹具（待完成）
└── conftest.py      # Pytest 配置
```

## 代码规范

### 代码风格

我们使用严格的代码格式化与质量工具：

- **Black**：代码格式化，行宽 88 字符
- **isort**：导入排序，兼容 Black 配置
- **flake8**：代码检查，行宽 88 字符
- **mypy**：严格模式的静态类型检查

### 类型标注

所有代码必须包含完整的类型标注：

```python
from typing import Optional, List, Dict, Any
from pathlib import Path

def process_config(
    settings: Settings,
    overrides: Optional[Dict[str, Any]] = None
) -> Path:
    """处理配置，支持可选覆盖参数。"""
    # 实现
    return Path("/example")
```

### 错误处理

使用 `src/exceptions.py` 中定义的自定义异常层级：

```python
from src.exceptions import ConfigurationError, SecurityError

try:
    # 某些操作
    pass
except ValueError as e:
    raise ConfigurationError(f"Invalid configuration: {e}") from e
```

### 日志

全局使用结构化日志：

```python
import structlog

logger = structlog.get_logger()

def some_function():
    logger.info("Operation started", operation="example", user_id=123)
    try:
        # 某些操作
        logger.debug("Step completed", step="validation")
    except Exception as e:
        logger.error("Operation failed", error=str(e), operation="example")
        raise
```

## 测试指南

### 测试组织

- **单元测试**：隔离测试单个函数和类
- **集成测试**：测试组件间交互
- **端到端测试**：测试完整工作流（规划中）

### 编写测试

```python
import pytest
from src.config import create_test_config

def test_feature_with_config():
    """测试特定配置下的功能。"""
    config = create_test_config(
        debug=True,
        claude_max_turns=5
    )

    # 测试实现
    assert config.debug is True
    assert config.claude_max_turns == 5

@pytest.mark.asyncio
async def test_async_feature():
    """测试异步功能。"""
    # 测试异步代码
    result = await some_async_function()
    assert result is not None
```

### 测试覆盖率

我们的目标是测试覆盖率大于 80%。当前覆盖率：

- 配置系统：约 95%
- 安全框架：约 95%
- Claude 集成：约 75%
- 存储层：约 90%
- Bot 组件：约 85%
- 异常处理：100%
- 工具模块：100%
- 总体：约 85%

## 实现进度

### 已完成的组件

#### TODO-1：项目结构
- 完整的包布局与规范的 Python 打包
- Poetry 依赖管理，区分开发/测试/生产依赖
- Makefile 开发命令
- 异常层级，正确使用继承
- 结构化日志，生产环境支持 JSON 输出
- 测试框架，支持 pytest、覆盖率统计和 asyncio

#### TODO-2：配置系统
- **Pydantic Settings v2**，支持环境变量加载
- **环境特定覆盖**（开发/测试/生产）
- **功能开关系统**，支持动态功能控制
- **跨字段校验**，提供清晰的错误信息
- **类型安全配置**，完全通过 mypy 检查
- **计算属性**，用于派生值
- **配置加载器**，支持环境检测
- **测试工具**，方便测试时使用配置

#### TODO-3：认证与安全框架
- 多提供者认证系统（白名单和令牌认证）
- 基于令牌桶算法的限流
- 全面的输入校验和路径遍历防护
- 安全审计日志，附带风险评估
- Bot 中间件框架，集成安全功能

#### TODO-4：Telegram Bot 核心
- 完整的 bot 实现，支持处理器注册
- 命令路由系统，覆盖全面的命令集
- 消息解析与智能响应格式化
- 内联键盘支持用户交互
- 错误处理中间件，提供用户友好的错误信息

#### TODO-5：Claude Code 集成
- 异步子进程管理 Claude CLI，支持超时处理
- 响应流式传输与解析，支持实时更新
- 会话状态持久化与上下文维护
- 工具使用监控与安全校验
- 费用追踪与使用量分析

#### TODO-6：存储层
- SQLite 数据库，完整的表结构与外键关系
- 仓储模式实现，提供清晰的数据访问
- 迁移系统，支持表结构版本管理
- 分析与报表，支持用户/管理员仪表盘
- 持久化会话存储，替代内存存储

### 下一步实现计划

#### TODO-7：高级功能（当前优先）
- 文件上传处理与安全校验
- Git 集成，支持仓库操作
- 快捷操作系统，覆盖常见工作流
- 会话导出功能（Markdown、JSON、HTML）
- 图片/截图支持与处理

#### TODO-8：完整测试套件
- 端到端工作流的集成测试
- 性能测试与基准测试
- 安全测试与渗透测试
- 并发用户负载测试

#### TODO-9：部署与文档
- Docker 配置与容器化
- Kubernetes 清单，用于生产部署
- 完整的用户和管理员文档
- API 文档与开发者指南

## 开发环境配置

### 必需的环境变量

在开发环境中，请在 `.env` 文件中设置以下变量：

```bash
# 基本功能所需
TELEGRAM_BOT_TOKEN=test_token_for_development
TELEGRAM_BOT_USERNAME=test_bot
APPROVED_DIRECTORY=/path/to/your/test/projects

# Claude 集成（选择一种认证方式）
USE_SDK=true                      # 使用 SDK（推荐用于开发）
# 方式一：使用已有的 Claude CLI 认证（无需 API Key）
# 方式二：直接使用 API Key
# ANTHROPIC_API_KEY=sk-ant-api03-your-development-key

# 开发设置
DEBUG=true
DEVELOPMENT_MODE=true
LOG_LEVEL=DEBUG
ENVIRONMENT=development

# 可选，用于测试特定功能
ENABLE_GIT_INTEGRATION=true
ENABLE_FILE_UPLOADS=true
ENABLE_QUICK_ACTIONS=true
```

### 以开发模式运行

```bash
# 通过环境变量启动
export TELEGRAM_BOT_TOKEN=test_token
export TELEGRAM_BOT_USERNAME=test_bot
export APPROVED_DIRECTORY=/tmp/test_projects
make run-debug

# 或使用 .env 文件
make run-debug
```

调试输出将显示：
- 配置加载步骤
- 已应用的环境覆盖配置
- 已启用的功能开关
- 校验结果

## 参与贡献

### 提交 PR 前的检查清单

1. **运行完整测试套件**：
   ```bash
   make test
   ```

2. **检查代码质量**：
   ```bash
   make lint
   ```

3. **格式化代码**：
   ```bash
   make format
   ```

4. **如有需要，更新文档**

5. **为新功能添加测试**

### 提交信息格式

使用约定式提交（Conventional Commits）：

```
feat: add rate limiting functionality
fix: resolve configuration validation issue
docs: update development guide
test: add tests for authentication system
```

### 代码评审准则

- 所有代码必须通过代码检查和类型检查
- 测试覆盖率不应降低
- 新功能需要同步更新文档
- 安全相关变更需要额外评审

## 常见开发任务

### 添加新配置项

1. **在 Settings 类中添加**，位于 `src/config/settings.py`：
   ```python
   new_setting: bool = Field(False, description="Description of new setting")
   ```

2. **添加到 `.env.example`** 并附带说明

3. **如有需要，添加校验逻辑**

4. **编写测试**，位于 `tests/unit/test_config.py`

5. **更新文档**，位于 `docs/configuration.md`

### 添加新功能开关

1. **在 `FeatureFlags` 类中添加属性**，位于 `src/config/features.py`：
   ```python
   @property
   def new_feature_enabled(self) -> bool:
       return self.settings.enable_new_feature
   ```

2. **添加到已启用功能列表**

3. **编写测试**

### 调试配置问题

1. **使用调试日志**：
   ```bash
   make run-debug
   ```

2. **在日志中检查校验错误**

3. **验证环境变量**：
   ```bash
   env | grep TELEGRAM
   env | grep CLAUDE
   ```

4. **测试配置加载**：
   ```python
   from src.config import load_config
   config = load_config()
   print(config.model_dump())
   ```

## 常见问题排查

### 常见问题

1. **导入错误**：确保你处于 Poetry 环境中（`poetry shell`）

2. **配置校验错误**：检查必需的环境变量是否已设置

3. **测试失败**：确保测试依赖已安装（`make dev`）

4. **类型检查错误**：运行 `poetry run mypy src` 查看详细错误

5. **Poetry 相关问题**：尝试 `poetry lock --no-update` 修复 lock 文件问题

### 获取帮助

- 使用 `make run-debug` 查看日志
- 使用 `make test` 查看测试输出
- 查阅 `docs/` 中的实现文档
- 参考已完成模块中的代码模式
