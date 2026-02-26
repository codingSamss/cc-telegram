# 安全策略

## 支持的版本

本项目目前处于开发阶段。安全更新将为以下版本提供：

| 版本 | 支持状态 |
| ------- | ------------------ |
| 0.1.x   | 当前开发版本 |

## 安全模型

Claude Code Telegram Bot 实现了纵深防御的安全模型，包含多个层次：

### 1. 认证与授权（TODO-3）
- **用户白名单**：仅预先批准的 Telegram 用户 ID 可以访问 bot
- **会话管理**：安全的会话处理，带超时和清理

### 2. 目录边界（TODO-3）
- **已批准目录**：所有操作限制在预配置的目录树内
- **路径验证**：防止目录遍历攻击（../../../etc/passwd）
- **权限检查**：操作前验证文件系统权限

### 3. 输入验证（TODO-3）
- **命令清理**：所有用户输入经过清理以防止注入攻击
- **文件类型验证**：仅允许的文件类型可以上传
- **路径清理**：移除危险字符和模式

### 4. 运行时保护（TODO-3）
- **Fail-closed 鉴权**：鉴权组件不可用时拒绝继续执行
- **Callback 鉴权守卫**：按钮回调与消息入口统一执行鉴权
- **异常隔离**：错误统一收敛并记录审计事件

### 5. 审计日志（TODO-3）
- **认证事件**：记录所有登录尝试和认证失败
- **命令执行**：记录所有命令和文件操作
- **安全违规**：记录路径遍历尝试和其他违规

## 当前安全状态

### 已实现的安全功能

#### 配置安全
- **环境变量保护**：敏感值（令牌、密钥）使用 SecretStr 处理
- **验证**：所有配置值经过验证并带有正确的错误消息
- **路径安全**：已批准的目录必须存在且可访问

#### 输入验证基础
- **类型安全**：完全符合 mypy 确保类型安全
- **验证框架**：Pydantic 验证器处理所有配置输入
- **错误处理**：全面的安全错误异常层级

#### 开发安全
- **代码中无密钥**：所有敏感数据通过环境变量传递
- **安全默认值**：生产默认值优先考虑安全而非便利
- **审计追踪**：结构化日志记录所有配置和验证事件

### 已规划的安全功能（TODO-3）

#### 认证系统
```python
# 已规划的实现
class AuthenticationManager:
    async def authenticate_user(self, user_id: int) -> bool
    async def check_permissions(self, user_id: int, action: str) -> bool
    async def create_session(self, user_id: int) -> Session
```

#### 路径验证
```python
# 已规划的实现
class SecurityValidator:
    def validate_path(self, path: str) -> Tuple[bool, Path, Optional[str]]
    def sanitize_command_input(self, text: str) -> str
    def validate_filename(self, filename: str) -> Tuple[bool, Optional[str]]
```

## 安全配置

### 必需的安全设置

```bash
# 所有操作的基础目录（关键）
APPROVED_DIRECTORY=/path/to/approved/projects

# 用户访问控制
ALLOWED_USERS=123456789,987654321  # Telegram 用户 ID
```

### 推荐的安全设置

```bash
# 安全功能
ENABLE_TELEMETRY=true  # 用于安全监控
LOG_LEVEL=INFO         # 捕获安全事件

# 环境
ENVIRONMENT=production  # 启用严格安全默认值
```

## 安全最佳实践

### 对管理员

1. **目录配置**
   ```bash
   # 使用最小必要权限
   chmod 755 /path/to/approved/projects

   # 避免敏感目录
   # 不要使用: /, /home, /etc, /var
   # 应该使用: /home/user/projects, /opt/bot-projects
   ```

2. **白名单管理**
   ```bash
   # 获取 Telegram 用户 ID：给 @userinfobot 发消息
   # 仅加入可信用户
   export ALLOWED_USERS="123456789,987654321"
   ```

3. **用户管理**
   ```bash
   # 获取 Telegram 用户 ID：给 @userinfobot 发消息
   # 添加到白名单
   export ALLOWED_USERS="123456789,987654321"
   ```

4. **监控**
   ```bash
   # 启用日志和监控
   export LOG_LEVEL=INFO
   export ENABLE_TELEMETRY=true

   # 监控日志中的安全事件
   tail -f bot.log | grep -i "security\|auth\|violation"
   ```

### 对开发者

1. **永远不要提交密钥**
   ```bash
   # 添加到 .gitignore
   .env
   *.key
   *.pem
   config/secrets.yml
   ```

2. **使用类型安全**
   ```python
   # 始终使用类型标注
   def validate_path(path: str) -> Tuple[bool, Optional[str]]:
       pass
   ```

3. **验证所有输入**
   ```python
   # 使用安全验证器
   from src.security.validators import SecurityValidator

   validator = SecurityValidator(approved_dir)
   valid, resolved_path, error = validator.validate_path(user_input)
   ```

4. **记录安全事件**
   ```python
   # 使用结构化日志
   logger.warning("Security violation",
                 user_id=user_id,
                 violation_type="path_traversal",
                 attempted_path=user_input)
   ```

## 威胁模型

### 防护的威胁

1. **目录遍历**（高优先级）
   - 尝试访问已批准目录之外的文件
   - 路径遍历攻击（../、~/等）
   - 符号链接攻击

2. **命令注入**（高优先级）
   - 通过用户输入进行 shell 命令注入
   - 环境变量注入
   - 进程替换攻击

3. **未授权访问**（中优先级）
   - 非白名单用户的访问
   - 会话伪造和复用攻击
   - 会话劫持

4. **资源滥用**（中优先级）
   - 重复请求与滥用调用
   - 拒绝服务攻击

5. **信息泄露**（低优先级）
   - 敏感文件暴露
   - 配置信息泄漏
   - 错误消息中的信息泄漏

### 超出范围的威胁

- 网络层攻击（由托管基础设施处理）
- Telegram API 漏洞（由 Telegram 处理）
- 主机操作系统安全（由系统管理处理）
- 服务器物理访问（由托管基础设施处理）

## 报告漏洞

### 安全联系方式

**不要为安全漏洞创建公开的 GitHub issue。**

安全问题请发送邮件至：[请填写安全联系邮箱]

### 报告格式

请包含：

1. 漏洞**描述**
2. **复现步骤**
3. **潜在影响**评估
4. **建议的缓解措施**（如有）
5. **披露时间线**偏好

### 响应流程

1. 48 小时内**确认收到**
2. 1 周内**初步评估**
3. 尽快**修复开发**
4. 修复后发布**安全公告**
5. 向报告者致**谢**（如本人同意）

## 安全检查清单

### 每次发布

- [ ] 所有依赖已更新至最新安全版本
- [ ] 安全测试通过
- [ ] 仓库中未提交密钥
- [ ] 安全文档已更新
- [ ] 威胁模型已审查
- [ ] 安全配置已验证

### 生产部署

- [ ] APPROVED_DIRECTORY 已正确配置和限制
- [ ] ALLOWED_USERS 白名单已配置
- [ ] Callback 鉴权与审计已验证
- [ ] 日志已启用和监控
- [ ] 环境变量已正确配置
- [ ] 文件权限已正确设置
- [ ] 网络访问已正确限制

## 安全资源

### 工具和库

- **Pydantic**：输入验证和类型安全
- **structlog**：安全的结构化日志
- **SecretStr**：敏感字符串的安全处理
- **pathlib**：安全的路径操作

### 参考资料

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [OWASP API Security Top 10](https://owasp.org/www-project-api-security/)
- [Telegram Bot 安全最佳实践](https://core.telegram.org/bots/faq#how-do-i-make-sure-that-webhook-requests-are-coming-from-telegram)
- [Python 安全指南](https://python-security.readthedocs.io/)

---

**最后更新**：2025-06-05
**安全审查**：TODO-3 实现阶段
