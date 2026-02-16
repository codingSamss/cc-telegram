# OpenClaw TG 交互对标与增强计划

## 背景与基线

- 对标仓库：`openclaw` 最新 `main`
- 基线提交：`e86647889c316980cc4b6643d417318e990e282a`
- 提交时间：`2026-02-16T07:47:36Z`
- 目标：提炼可迁移到 `cli-tg` 的 Telegram 交互能力，优先提升稳定性、可用性与交互完整度。

## 当前进度（2026-02-16）

- `P2-A / reaction`：完成（已完成线上验收，确认入站/出站与反馈注入链路可用）。
- `P2-A / poll`：暂停（按当前需求移除 `decide/poll` 对话能力，本轮不继续推进）。
- `P2-B / voice`：取消（按当前需求不继续推进语音转写链路）。
- `P0-A`：完成（发送链路统一与容错收敛已落地）。
  - 已完成：新增统一发送助手 `src/bot/utils/telegram_send.py`。
  - 已完成：权限弹窗发送链路切到统一助手（含 parse fallback、threadless retry、DM/general-topic thread 裁剪）。
  - 已完成：`message.py` 主回复链路 `_reply_text_resilient` 已接入统一助手（主文本回复也支持统一降级）。
  - 已完成：`callback.py` 中 `query.message.reply_text` 入口补齐容错（失败时回退统一发送助手）。
  - 已完成：`callback.py` 关键交互链路（continue/quick action/export 等）的 `edit_message_text` 接入统一降级 helper（markdown parse fallback + no-op 容错）。
  - 已完成：`callback.py` 其余零散 `edit_message_text` 入口已全部收敛到统一 helper（文件内仅保留 helper 内部直调）。
  - 已完成：`command.py` 中 `/new` 与 `/continue` 回复链路补齐容错（失败时回退统一发送助手）。
  - 已完成：`command.py` 其余 `update.message.reply_text` 入口已迁移到同一助手。
  - 已完成：middleware（`auth.py`/`rate_limit.py`/`security.py`）用户提示发送链路接入统一容错（reply 失败回退统一发送助手）。
  - 已完成：`core.py` 全局 `_error_handler` 用户提示发送链路接入统一容错。
- `P0-B`：完成（update 幂等能力已落地并收口）。
  - 已完成：新增内存去重缓存 `src/bot/utils/update_dedupe.py`（TTL + max size）。
  - 已完成：新增 offset 持久化 `src/bot/utils/update_offset_store.py`（`data/state/telegram/update-offset.json`）。
  - 已完成：`core.py` 注册全局 update guard（group=-10），在业务 handler 前执行 stale/duplicate 拦截。
  - 已完成：处理成功 update 自动推进 offset，`stop()` 时强制 flush 落盘。
  - 已完成：新增单测 `tests/unit/test_bot/test_update_dedupe.py`、`tests/unit/test_bot/test_update_offset_store.py`、`tests/unit/test_bot/test_core_update_guard.py`。
  - 已完成：本地回归验证通过（核心幂等 8 passed；`tests/unit/test_bot` 全量 201 passed）。
  - 已完成：线上观察确认“重启/网络抖动后不重复回复”，满足收口标准。
- `P1-A`：完成（入站聚合 MVP 已接入并通过回归）。
  - 已完成：文本分片聚合缓冲（按 `chat+thread+user` 键）接入 `handle_text_message`，自动合并长文本分片后再送模型。
  - 已完成：`media_group` 图片聚合缓冲（按 `chat+media_group_id` 键）接入 `handle_photo`，同组多图一次送模型。
  - 已完成：多图场景下 Codex CLI 本地临时图片文件按张创建与统一清理。
  - 已完成：回复锚点统一到聚合首条消息（`reply_to_message_id` 使用 source message）。
  - 已完成：新增单测 `tests/unit/test_bot/test_inbound_aggregation.py`，覆盖文本分片合并与 media_group 合并。
  - 已完成：本地回归验证通过（`tests/unit/test_bot` 全量 205 passed）。
- `P1-B`：取消（经评估收益有限，且当前体验已基本达到目标效果）。
  - 说明：当前实现已是“单条进度消息为主 + 持续 edit”，与拟优化目标差异很小。
  - 处理：本轮不再继续投入开发，后续仅在明确痛点出现时再重启评估。
- 里程碑状态：
  - `M1`（稳定发送与幂等）：完成（代码、单测与线上观察均已收口）。
  - `M2`（入站聚合 + 流式复用）：完成（入站聚合已落地；流式草稿复用经评估取消）。
  - `M3`（reaction/poll/voice 能力补齐）：阶段完成（reaction 已闭环，poll 暂停、voice 取消）。
- 收口验证（2026-02-16）：
  - `make test`：通过（`476 passed`）。
  - `make lint`：未通过（仓库历史基线问题，非本轮单点阻塞）。
    - `black --check`：7 个文件待格式化。
    - `isort --check-only`：2 个文件导入顺序不符合。
    - `flake8`：187 条告警。
    - `mypy src`：`Found 371 errors in 27 files (checked 72 source files)`。

## 先解释：reaction/poll「原生支持」是什么意思

这里的“原生支持”指：不是仅在业务层拼字符串模拟，而是直接接入 Telegram Bot API 对应能力，包含入站事件、出站发送、错误处理和线程参数处理。

### 1) Reaction 原生支持

- OpenClaw 既能收（`message_reaction` update），也能发（`setMessageReaction`）。
- 参考实现：
  - 入站 reaction 处理：`/tmp/openclaw/src/telegram/bot.ts:360`
  - 出站设置/移除 reaction：`/tmp/openclaw/src/telegram/send.ts:605`
- 示例：
  - 用户在群里给机器人上一条消息点了 `👍`。
  - 机器人收到 `message_reaction` 事件后，把“谁在什么消息上点了什么表情”写入系统事件上下文，供后续推理使用。
  - 机器人也可以主动对某条消息打 `👀` 作为 ACK，或移除已有 reaction。

### 2) Poll 原生支持

- OpenClaw 直接调用 Telegram `sendPoll`，支持多选、匿名、时长、topic/thread 参数，并做 thread 失败回退。
- 参考实现：`/tmp/openclaw/src/telegram/send.ts:984`
- 示例：
  - 机器人在项目群发起投票：“本周发布窗口？”
  - 选项：`周三`、`周四`、`周五`，可配置匿名或非匿名、单选或多选。
  - 如果 topic thread 参数异常（例如 thread 不存在），会自动降级重试，避免消息直接失败。

## 可优化点（每点一个直观示例）

### 1) 并发与顺序控制（按 chat/topic 串行）

- 借鉴点：按 `chat/topic` 做顺序键，避免并发更新导致乱序。
- 示例：
  - 同一 topic 内用户连续发 3 条消息，当前实现可能并发交错。
  - 目标行为是严格按顺序处理，避免“后发先回”。

### 2) 更新幂等与断点恢复（dedupe + offset 持久化）

- 借鉴点：处理过的 update 做去重，`last_update_id` 落盘。
- 示例：
  - 服务重启后 Telegram 重放旧 update。
  - 目标行为：不重复执行旧命令、不重复发历史回复。

### 3) thread/topic 规则精细化（DM/forum/general topic）

- 借鉴点：DM 不发送 `message_thread_id`，forum general topic(`id=1`) 发送消息时也不带该字段。
- 示例：
  - 私聊内回调按钮触发权限弹窗时，如果带了 thread 参数，可能触发 Telegram 拒绝。
  - 目标行为：按 chat 类型自动裁剪线程参数。

### 4) 发送链路统一降级（parse fallback + threadless retry）

- 借鉴点：`parse_mode` 失败自动降纯文本；thread not found 自动去 thread 重试。
- 示例：
  - 模型输出包含复杂 markdown，Telegram 报 entity parse 错。
  - 目标行为：自动降级 plain text 继续送达，不让用户“看不到回复”。

### 5) 流式草稿到最终消息复用

- 借鉴点：先发草稿并持续 edit，最终直接把草稿 edit 成终稿，减少消息噪音。
- 示例：
  - 长任务当前可能产生多条中间消息。
  - 目标行为：用户只看到一条“会变化”的进度消息 + 最终稳定内容。

### 6) 入站长文本分片重组

- 借鉴点：将 Telegram 自动拆分的超长文本片段重组后再喂给模型。
- 示例：
  - 用户粘贴一段 8000+ 字日志，Telegram 分成两条。
  - 目标行为：模型看到的是完整一段日志，而不是两次独立问答。

### 7) media_group 聚合处理

- 借鉴点：同一个 `media_group_id` 的多图/多媒体合并为一次上下文输入。
- 示例：
  - 用户一次发 6 张截图用于排障。
  - 目标行为：模型一次性分析 6 张图，而不是逐张产生碎片化回复。

### 8) 语音链路完善（入站转写 + 禁止语音时回退文本）

- 借鉴点：语音消息优先转写；若发送语音被拒绝则自动回退文本。
- 示例：
  - 用户发语音提问，机器人应先转文字再推理。
  - 若目标聊天禁语音，机器人应改发文字总结，而不是报错终止。

### 9) 反应/投票能力补齐（能力面）

- 借鉴点：补 reaction 与 poll 的入站/出站能力。
- 示例：
  - 机器人在任务启动时给用户消息加 `👀` 表示接单。
  - 机器人在群内发“方案 A/B”投票，收集团队偏好。

### 10) 命令菜单治理（冲突校验与上限策略）

- 借鉴点：命令名称校验、冲突检测、数量上限治理。
- 示例：
  - 新增多个功能命令后出现同名覆盖或菜单过长。
  - 目标行为：启动时检测并提示冲突，超过上限时明确裁剪策略。

## 建议推进顺序

1. `P0`：thread 参数规则统一 + 发送降级链路统一。
2. `P0`：offset 持久化 + update dedupe。
3. `P1`：入站文本分片重组 + media_group 聚合。
4. `P2`：reaction 已完成并进入常规观察（poll/voice 不继续推进）。
5. `P1-B`：已取消（当前不推进）。

## 与当前仓库的对照锚点

- 当前 topic scope：`src/bot/utils/scope_state.py:44`
- 当前流式进度编辑：`src/bot/handlers/message.py:972`
- 当前 callback markdown 回退：`src/bot/handlers/callback.py:1817`
- 当前权限提示 thread 透传逻辑：`src/bot/handlers/message.py:2584`
- 当前 handler 注册范围（text/document/photo/callback）：`src/bot/core.py:149`

## 分周执行清单（可直接排期）

### 第 1 周（P0-A）：thread 规则统一 + 发送链路抽象

- 目标：先把“最容易出错、最影响可用性”的发送线程规则和降级逻辑统一到一个发送入口。
- 预估工作量：`2.5 ~ 3.5` 人天
- 任务：
  - 新增 Telegram 发送助手模块（建议 `src/bot/utils/telegram_send.py`），统一处理：
    - `parse_mode` 失败回退 plain text
    - `thread not found` 去 `message_thread_id` 重试
    - 长文本分片发送
  - 抽离 thread 规则函数：
    - DM 不发 `message_thread_id`
    - forum general topic(`id=1`) 消息发送不发 `message_thread_id`
  - 替换现有关键调用点：
    - `src/bot/handlers/message.py`
    - `src/bot/handlers/callback.py`
    - `src/bot/handlers/command.py`
- 示例验收：
  - 私聊触发权限按钮时，不再因为 thread 参数被 Telegram 拒绝。
  - 带复杂 markdown 的错误栈输出，仍能自动降级发出去。
  - topic 消失时，消息自动 threadless 重试成功。
- 测试补充：
  - 新增 `tests/unit/test_bot/test_telegram_send_wrapper.py`
  - 覆盖 parse fallback、threadless retry、DM/thread=1 分支。

### 第 2 周（P0-B）：update 幂等（dedupe + offset 持久化）

- 目标：解决“重启后重复处理”和“网络抖动导致重复 update”问题。
- 预估工作量：`2 ~ 3` 人天
- 任务：
  - 增加 update dedupe 缓存（TTL + max size）。
  - 增加 `last_update_id` 持久化文件（建议 `data/state/telegram/update-offset.json`）。
  - 在 polling 启动与处理链路接入读取/更新逻辑。
  - 保留当前 `drop_pending_updates=True`，但不再只依赖它。
- 示例验收：
  - bot 重启后不重复处理上一轮已响应消息。
  - 在网络闪断恢复后，回放 update 不会触发重复回复。
- 测试补充：
  - 新增 `tests/unit/test_bot/test_update_offset_store.py`
  - 新增 `tests/unit/test_bot/test_update_dedupe.py`

### 第 3 周（P1-A）：入站聚合（长文本分片 + media_group）

- 目标：提升“用户一次性输入完整性”，减少模型上下文碎片化。
- 预估工作量：`3 ~ 4` 人天
- 任务：
  - 增加长文本分片重组缓冲：
    - 按 `chat_id + thread_id + sender_id` 维度聚合
    - 通过消息 ID 间隔 + 时间窗口判定同批分片
  - 增加 `media_group_id` 聚合：
    - 同一组媒体合并后一次喂给模型
  - 结合现有限流与任务忙状态，避免聚合期间重复触发处理。
- 示例验收：
  - 用户粘贴超长日志（Telegram 自动拆成两条），模型看到合并后的完整日志。
  - 用户一次发送 6 张图，模型一次性分析并给出统一结论。
- 测试补充：
  - 新增 `tests/unit/test_bot/test_text_fragment_aggregation.py`
  - 新增 `tests/unit/test_bot/test_media_group_aggregation.py`

### 第 4 周（P1-B，已取消）：流式草稿消息复用（减少噪音）

- 目标：把“多条进度消息”收敛为“单条可编辑草稿 + 最终定稿”。
- 预估工作量：`2 ~ 3` 人天
- 当前状态：取消（收益评估后不继续推进）。
- 处理说明：
  - 现有实现已满足“单条进度消息为主 + 持续 edit”的核心体验目标。
  - 本项转为“需求再触发”策略：仅当线上出现明确噪音/混乱反馈时再恢复排期。

### 第 5 周（P2-A）：reaction / poll 能力补齐

- 目标：补全 TG 能力面，让交互方式更丰富。
- 预估工作量：`2.5 ~ 3.5` 人天
- 任务：
  - reaction：
    - 入站 `message_reaction` 事件接收与记录
    - 出站设置/移除 reaction 的 helper
  - poll：
    - 增加 poll 发送能力（单选/多选、匿名、时长）
    - 支持 topic/thread 参数和 threadless fallback
  - 可通过命令或 callback 暴露最小可用入口（先 MVP）。
- 示例验收：
  - 用户给机器人消息点 `👍`，系统可记录该交互事件。
  - 机器人在群内成功发起“方案 A/B”投票。
- 测试补充：
  - 新增 `tests/unit/test_bot/test_reaction_events.py`
  - 新增 `tests/unit/test_bot/test_poll_send.py`

### 第 6 周（P2-B，已取消）：语音链路与整体回归加固

- 目标：原计划补齐语音处理闭环，并完成跨功能回归。
- 预估工作量：`3 ~ 4` 人天
- 当前状态：按需求取消，不再继续开发语音转写链路。
- 任务：
  - 入站语音/音频：
    - 先做转写再入模型（最小可用可接现有能力）
  - 出站语音失败回退：
    - 若被 Telegram/隐私策略拒绝，自动回退文本
  - 整体回归：
    - topic/thread、stream、callback、permission、document/photo 全链路回归
- 示例验收：
  - 用户语音提问可得到文字理解后的有效回复。
  - 目标聊天禁语音时不会中断，自动改发文本。
- 测试补充：
  - 新增 `tests/unit/test_bot/test_voice_flow.py`
  - 补充 `tests/unit/test_bot/test_permission_prompt_topic.py` 相关边界。

## 里程碑与交付物

- M1（第 2 周末）：稳定发送与幂等能力上线，明显降低重复回复和发送失败。
- M2（第 4 周末）：入站聚合上线；流式复用经评估取消，不再单独排期。
- M3（第 6 周末）：reaction 能力闭环；poll/voice 按产品决策暂停或取消。

## 每周固定验收方式

- 功能验收：按本周“示例验收”逐条过一遍真实 Telegram 场景。
- 质量验收：执行 `make test`，关键新增模块覆盖率不低于 `80%`。
- 变更验收：检查 `git status` 与 PR 说明，确保仅包含本周范围改动。

## 风险与依赖提示

- Telegram 平台限制：部分行为依赖群类型、topic 状态、用户隐私设置（如语音权限）。
- 兼容性风险：PTB 与现有 handler 结构下，引入聚合缓冲需要小心避免消息漏处理。
- 范围控制：建议严格按周拆分 PR，避免一次性改动过大导致回归成本升高。
