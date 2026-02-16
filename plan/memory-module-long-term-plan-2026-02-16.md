# CLI-TG 记忆模块长期实施计划（本地优先）

## 1. 目标与范围

### 1.1 目标
- 在 `cli-tg` 中引入可持续演进的“长期记忆”能力。
- 第一阶段保持纯本地部署（不新增独立服务进程）。
- 在保证现有稳定性的前提下，实现：
  - 记忆沉淀（从交互中提炼）
  - 记忆检索（按用户/项目相关性召回）
  - 记忆注入（在请求前增强 prompt）

### 1.2 非目标（当前阶段不做）
- 不引入远程向量数据库。
- 不做跨机器同步。
- 不做复杂自动本体构建（知识图谱级别）。

## 2. 方案总览（分阶段）

### Phase 0：规划与守护（当前）
- 输出计划文档与验收标准。
- 明确可回滚点与 feature flag。

### Phase 1：Memory Lite（建议先落地）
- 存储：SQLite 新增 `memory_items` 表。
- 检索：SQLite FTS5（全文检索）+ 时间/置信度重排。
- 注入：在 `handle_text_message` 请求前注入记忆块。
- 提炼：规则驱动（偏好、约束、长期背景、近期目标）。
- 治理：容量上限、去重、TTL/归档策略。

### Phase 2：Memory Plus
- 增加 embedding 检索（本地模型或轻量向量库）。
- 混合召回（FTS + 向量）。
- 引入反馈闭环（用户纠正记忆、置顶/屏蔽）。

### Phase 3：Service 化（仅当规模需要）
- 抽离为独立 memory service（可选 OpenViking 或自研）。
- 提供多实例共享、跨 bot 复用、可观测性增强。

## 3. 架构设计（Phase 1）

### 3.1 数据模型
新增 `memory_items`（建议字段）：
- `id`、`user_id`、`session_id`、`project_path`
- `memory_type`（preference/context/constraint/task/episode）
- `content`、`tags`、`content_hash`
- `confidence`、`access_count`、`last_accessed_at`
- `created_at`、`updated_at`、`is_active`

### 3.2 写入链路
- 触发点：一次成功交互完成后。
- 输入：用户 prompt、模型响应、工具使用摘要。
- 处理：
  1. 候选提炼（规则）
  2. 去重（`content_hash` + 类型 + scope）
  3. Upsert
  4. 超量裁剪（保留高价值 + 新近）

### 3.3 检索链路
- 触发点：每次用户请求前。
- 检索条件：`user_id` 必选，`project_path` 优先。
- 召回：FTS5 TopK + 类型权重（偏好/约束优先）+ 新近度。
- 输出：受预算控制的 memory context（字符数上限）。

### 3.4 注入策略
- 注入模板（简化示例）：
  - “以下为历史记忆，仅在相关时使用；与用户当前明确请求冲突时，以当前请求为准。”
- 预算：
  - `MEMORY_MAX_RETRIEVAL`
  - `MEMORY_CONTEXT_MAX_CHARS`
- 降级：检索失败时不阻塞主流程，直接走原始 prompt。

## 4. 配置与开关

新增配置（建议）：
- `ENABLE_MEMORY=true|false`
- `MEMORY_MAX_RETRIEVAL=6`
- `MEMORY_CONTEXT_MAX_CHARS=1200`
- `MEMORY_MAX_ITEMS_PER_USER=1500`
- `MEMORY_MIN_PROMPT_CHARS=12`

要求：
- 任何问题可通过 `ENABLE_MEMORY=false` 一键关闭。

## 5. 里程碑与交付

### M1（1-2 天）
- 完成 migration、repository、基础 service。
- 完成交互后写入 + 请求前注入闭环。
- 单元测试覆盖：database/repository/service。

### M2（1-2 天）
- 加入治理策略（去重、上限、失效、黑白名单类型）。
- 增加日志与可观测指标（命中率、注入大小、检索耗时）。

### M3（2-3 天）
- 引入混合检索实验分支（可选）。
- AB 对比（开启/关闭记忆）观察质量与成本变化。

## 6. 验收标准

功能验收：
- 同一用户跨会话可稳定召回偏好/约束。
- 记忆检索失败不影响正常响应。
- 能通过配置开关完全停用记忆链路。

质量验收：
- 关键路径新增测试通过。
- 不降低现有核心命令可用性。
- 不引入敏感信息泄露（默认不写入 token/secret 模式文本）。

## 7. 风险与应对

- 风险：错误记忆污染回答。
  - 应对：置信度阈值 + 类型优先级 + 用户可纠正。
- 风险：Prompt 变长导致成本上升。
  - 应对：严格预算与 TopK 限制。
- 风险：数据膨胀。
  - 应对：每用户上限 + 定期裁剪。

## 8. 回滚与安全策略

- 回滚优先级：
  1. `ENABLE_MEMORY=false`（运行时关闭）
  2. 关闭注入，仅保留写入
  3. 完整回退 memory 相关代码
- 数据安全：
  - 保留原有 SQLite 备份策略。
  - memory 表独立，避免影响既有会话主链路。

## 9. 下一步执行建议

- 按 M1 开始最小可用实现，先不引入外部服务。
- 每完成一个子阶段即提交可回滚的小步 PR。
- 在真实 Telegram 对话中做 2-3 天观察，再决定是否进入 Phase 2。

