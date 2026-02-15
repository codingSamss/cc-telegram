# TODO-7: Timeline & Codex Visualization

## 目标
1. 让 Telegram 端 `/context` 命令兼容 timeline 模式，同时保持默认输出不变。 
2. 让 Codex 的命令/消息/回调在 Telegram 展示时与 Claude 保持统一的“思考流＋结论”体验，并提供明显的模型标识与错误信息。
3. 为 timeline 分页、Codex 特殊展示以及方向反馈建立可测试的流程，方便后续扩展到其他引擎。

## 核心拆解
1. **命令入口**
   - 解析 `/context timeline`（或 `/context --timeline`）命令参数，决定是否启用分页视图。
   - 根据当前 Engine（Claude/Codex）决定是否附加特有提示（例如 Codex 自带 %/reasoning 字段）。
   - 首屏输出：加载提示、首批事件、分页按钮（下一页/返回），支持 `next_cursor`。

2. **服务层与模板**
   - 若尚无，新增 `SessionTimelineService`（或将逻辑并入 `SessionService`）负责：
     * 读取 `event_service` 结果并转为分页数据。
     * 跟 `next_cursor` 关联的游标校验与错误提示。
     * 缓存 timeline 快照，减少频繁 I/O。
   - `SessionInteractionService` 需支持 timeline 模式的：
     * 加载态、空数据、异常信息等模板文本。
     * 分页按钮文案一致（下一页/上一页/返回 context）。
     * Codex-specific 标识（气泡颜色、文案、error summary）。

3. **回调翻页**
   - 回调处理（`callback.py`）需能基于 `timeline:cursor:<value>` 识别分页并重用 template。
   - `next_cursor` 为空时隐藏“下一页”按钮；提供“返回上下文”按钮。
   - 校验无效游标、会话/目录不匹配时返回错误提示。

4. **Codex 事件适配**
   - `src/bot/handlers/message.py` 与 `callback.py` 中的“思考流”渲染需识别 Codex event schema（`reasoning`、`status_updates` 等）。
   - 显示 Codex 标识（可定制气泡前缀/颜色/emoji），并在 `context`/`status` 中补充 Codex 模型名称与上下文百分比。
   - 对 `resume`/`engine` 切换保持命令菜单与 quick action 同步。

5. **测试覆盖**
   - 命令 timeline 模式（含 Codex）
   - 回调分页、next_cursor 有效/失效
   - 非法游标、会话不匹配以及空事件情形
   - Codex 日志与错误提示是否触发逻辑（模拟 `message.py`/`callback` 中的 reasoning 解析）

## 验证与复盘
1. 手动执行 `/context timeline` + 翻页、`/context` 默认、Codex 与 Claude 切换的行为；确认菜单/按钮与标识一致。  
2. 撰写/更新单测（参照 `tests/unit/test_bot/test_status_progress_feedback.py`、`tests/unit/test_services/test_session_service.py`）并在本地运行 `pytest` + `black/isort/mypy`。
3. 完成后在 `plan/engine-adaptation-optimization-plan.md` 与新的 `plan/todo-7` 里更新状态与关键文件行号。  

## 迭代标记
- [ ] 命令解析 + timeline rendering
- [ ] 回调分页 + next_cursor
- [ ] Codex-specific rendering + model badge
- [ ] Timeline 单测覆盖
- [ ] Documentation/update plan status
