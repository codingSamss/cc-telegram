# 贡献指南 - Claude Code Telegram Bot

感谢你有兴趣为本项目做贡献！本文档提供了参与贡献的指引。

## 开发状态

本项目目前正在积极开发中，当前进度：

- **项目结构与配置**（完成）
- **认证与安全**（完成）
- **Bot 核心与集成**（TODO-4、TODO-5，完成）
- **存储层**（TODO-6，完成）
- **高级功能**（TODO-7，下一步）

## 快速上手

### 前置条件

- Python 3.9 或更高版本
- Poetry 依赖管理工具
- Git 版本控制

### 配置开发环境

1. **Fork 并克隆仓库**：
   ```bash
   git clone https://github.com/your-username/claude-code-telegram.git
   cd claude-code-telegram
   ```

2. **安装依赖**：
   ```bash
   make dev
   ```

3. **配置环境**：
   ```bash
   cp .env.example .env
   # 编辑 .env 填写你的开发配置
   ```

4. **验证配置**：
   ```bash
   make test
   make lint
   ```

## 开发流程

### 开始工作前

1. **查看已有 issue**，看是否有类似工作
2. 如果没有，**创建一个 issue**
3. **在 issue 下评论**表示你正在处理
4. 从 main 分支**创建功能分支**

### 进行修改

1. **遵循项目结构**：
   ```
   src/
   ├── config/     # 配置（完成）
   ├── security/   # 认证与安全（完成）
   ├── bot/        # Telegram bot（完成 - TODO-4）
   ├── claude/     # Claude 集成（完成 - TODO-5）
   └── storage/    # 数据库（完成 - TODO-6）
   ```

2. **为新功能编写测试**：
   ```bash
   # 在 tests/unit/ 或 tests/integration/ 中添加测试
   make test
   ```

3. **遵循代码规范**：
   ```bash
   make format  # 自动格式化代码
   make lint    # 检查代码质量
   ```

4. 按需**更新文档**

### 代码规范

#### 类型标注

所有代码必须包含完整的类型标注：

```python
from typing import Optional, List, Dict, Any
from pathlib import Path

async def process_data(
    items: List[Dict[str, Any]],
    config: Optional[Path] = None
) -> bool:
    """使用可选配置处理数据。"""
    # 实现
    return True
```

#### 错误处理

使用自定义异常层级：

```python
from src.exceptions import ConfigurationError, SecurityError

try:
    # 某些操作
    pass
except ValueError as e:
    raise ConfigurationError(f"无效配置: {e}") from e
```

#### 日志

使用结构化日志：

```python
import structlog

logger = structlog.get_logger()

def some_function():
    logger.info("Operation started", operation="example", user_id=123)
    # 实现
```

#### 测试

编写全面的测试：

```python
import pytest
from src.config import create_test_config

@pytest.mark.asyncio
async def test_feature():
    """测试功能。"""
    config = create_test_config(debug=True)
    # 测试实现
    assert config.debug is True
```

## 贡献类型

### 高优先级（当前 TODO）

#### TODO-7: 高级功能（当前优先）
- 带安全验证的文件上传处理
- 仓库操作的 Git 集成
- 常用工作流的快捷操作系统
- 会话导出功能（Markdown、JSON、HTML）
- 图片/截图支持与处理

**需要创建/修改的文件**：
- `src/bot/handlers/file.py`
- `src/git/integration.py`
- `src/features/quick_actions.py`
- `src/features/export.py`
- `tests/unit/test_features.py`

### 近期已完成

#### TODO-4: Telegram Bot 核心
- Bot 连接和处理器注册
- 命令路由系统
- 消息解析和格式化
- 内联键盘支持
- 错误处理中间件

#### TODO-5: Claude Code 集成
- Claude CLI 子进程管理
- 响应流式传输和解析
- 会话状态持久化
- 超时处理
- 工具使用监控

#### TODO-6: 存储层
- SQLite 数据库模式
- 仓储模式实现
- 迁移系统
- 分析与报告

### 文档改进

- API 文档
- 用户指南
- 部署指南
- 架构文档

### 测试改进

- 集成测试
- 端到端测试
- 性能测试
- 安全测试

## 提交变更

### Pull Request 流程

1. **确保测试通过**：
   ```bash
   make test
   make lint
   ```

2. 按需**更新文档**

3. **创建 Pull Request** 并包含：
   - 清晰的标题和描述
   - 关联的 issue
   - 变更列表
   - 如涉及 UI 则附截图

4. **及时回应审查反馈**

### 提交信息格式

使用约定式提交：

```
feat: add rate limiting functionality
fix: resolve configuration validation issue
docs: update development guide
test: add tests for authentication system
refactor: reorganize bot handlers
```

### Pull Request 模板

```markdown
## 描述
简要描述所做的变更。

## 关联 Issue
Fixes #123

## 变更类型
- [ ] Bug 修复
- [ ] 新功能
- [ ] 破坏性变更
- [ ] 文档更新

## 测试
- [ ] 已添加/更新测试
- [ ] 所有测试通过
- [ ] 已完成手动测试

## 检查清单
- [ ] 代码遵循项目风格指南
- [ ] 已完成自查
- [ ] 文档已更新
- [ ] 无破坏性变更（或已明确记录）
```

## 代码审查指南

### 对贡献者

- 提交前**自查**代码
- **编写清晰的提交信息**和 PR 描述
- **及时回应**审查反馈
- **保持 PR 聚焦**于单一变更
- 为新功能**添加测试**

### 对审查者

- 提供**建设性**和有帮助的反馈
- 尽可能**测试功能**
- **检查安全影响**
- **验证文档更新**
- **确保测试全面**

## Issue 指南

### Bug 报告

```markdown
**描述 Bug**
清晰描述这个 Bug 是什么。

**复现步骤**
复现该行为的步骤。

**期望行为**
你期望发生什么。

**环境**
- 操作系统：[如 macOS、Linux]
- Python 版本：[如 3.9]
- Poetry 版本：[如 1.7.1]

**补充说明**
关于该问题的其他上下文。
```

### 功能请求

```markdown
**你的功能请求是否与某个问题相关？**
清晰描述该问题是什么。

**描述你期望的解决方案**
清晰描述你希望实现什么。

**描述你考虑过的替代方案**
你考虑过的替代解决方案或功能。

**补充说明**
关于该功能请求的其他上下文。
```

## 安全

### 报告安全问题

**不要**为安全漏洞创建公开的 issue。

请：
1. 将安全问题发送至 [维护者邮箱]
2. 包含漏洞的详细描述
3. 在公开披露前等待确认

### 安全指南

- **永远不要提交**密钥或凭据
- **彻底验证所有输入**
- 数据库操作**使用参数化查询**
- **遵循最小权限原则**
- **记录安全相关事件**

## 开发环境

### 必需工具

- **Poetry**：依赖管理
- **Black**：代码格式化
- **isort**：导入排序
- **flake8**：代码检查
- **mypy**：类型检查
- **pytest**：测试

### 推荐的 IDE 配置

#### VS Code
```json
{
    "python.defaultInterpreterPath": ".venv/bin/python",
    "python.formatting.provider": "black",
    "python.linting.enabled": true,
    "python.linting.flake8Enabled": true,
    "python.linting.mypyEnabled": true
}
```

#### PyCharm
- 配置 Poetry 解释器
- 启用 Black 格式化
- 启用 flake8 和 mypy 检查

## 社区指南

### 行为准则

- **尊重**他人并包容
- **欢迎新人**并帮助他们入门
- 提供**建设性反馈**
- **聚焦于代码**，而非个人
- **假设善意**

### 沟通

- 使用**清晰、简洁的语言**
- 在 issue 和 PR 中**提供上下文**
- 不确定时**提出问题**
- **分享知识**并帮助他人

## 获取帮助

### 文档
- 查看 `docs/` 目录中的指南
- 查看现有代码了解模式
- 阅读配置指南

### 提问
- 先搜索已有 issue
- 提供上下文和示例
- 包含相关环境信息
- 具体说明你尝试过什么

### 调试
- 使用 `make run-debug` 获取详细日志
- 用 `make test` 检查测试输出
- 运行 `poetry run mypy src` 进行类型检查

## 致谢

贡献者将在以下位置获得致谢：
- `CHANGELOG.md` 中记录其贡献
- 项目文档
- 发布说明

感谢你为 Claude Code Telegram Bot 做出贡献！
