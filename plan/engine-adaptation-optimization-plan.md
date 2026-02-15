# Engine Adaptation & Optimization Plan

## 目标
- 让 Telegram 端不仅适配 Claude，还能以统一的方式支持 Codex 及未来引擎，尤其在 `/context timeline`、命令/回调/菜单一致性与错误提示方面。 
- 补足 TODO-7 描述的“高级功能”，同时盘点安全、测试与部署的缺口，形成清晰行动列表。

## 关键改进项
1. **恢复/增强 Timeline 输出能力**
   - 让 `/context timeline` 命令与回调分页（`next_cursor`）能够在 Telegram 上渲染加载态、空数据态、错误态与分页按钮，且不干扰默认 `/context` 行为。  
   - 引入 `session_timeline_service`（或等价模块）负责事件分页及缓存；由 `SessionInteractionService`/`SessionService` 调用。  
   - 增加针对命令、回调、游标校验、无事件、會話不匹配的单测。  

2. **Codex 直聊体验一致化**
   - 核实现有 `message.py`、`callback.py` 的事件解析与渲染是否适配 Codex 的 `reasoning` 等字段，在 Bot 端补充 Codex 专用标识、气泡颜色或文字提示。  
   - 兼容 `resume`、`engine` 切换后的命令列表与 `status`/`context` 别名。  

3. **安全与基础设施 TODO 补全（TODO-3 回顾）**
   - 将 `InMemoryTokenStorage` 替换为数据库-backed token 存储，使用 `storage/repositories` 中的 repo。  
   - 核对 `SECURITY.md` 列表，确保认证、目录边界、输入验证、限流与审计各项都有实现或明确计划；必要时增加测试/文档。  

4. **测试完善（TODO-8）**
   - 扩展 `tests/unit` 针对 session timeline、Codex command/message 回调、rate limit summary 的 coverage。  
   - 建立常规 `pytest` + `coverage` + `black/isort/mypy` 运行节奏，确认不会因为 Codex/Claude 切换而缺少测试。  

5. **部署与文档（TODO-9）**
   - 对 README、docs 下的 TODO-9 文档进行统一，列出运行/部署/更新步骤（包含 Codex CLI 配置、`engine` 切换指南、菜单同步指引）。  
   - 提供 `plan/` 目录下的路线图 (如本计划) 作为每次改动的入口，保持 `plan/daily` 与 `plan/` 的同步与进度更新。  

## 下步动作
- 选定某一项（优先级建议：1. Timeline + Codex、2. 安全 token、3. 测试、4. 部署）。  
- 按需创建 PR，附上相关测试/日志/plan 更新说明。  
