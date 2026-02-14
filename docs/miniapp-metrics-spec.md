# Mini App 指标口径与采集方案（P3-4.8 前置定义）

## 1. 目标

为 iOS 立项评估提供统一、可复算的三类核心指标：

1. 活跃（活跃用户与活跃会话）
2. 审批频次（请求量、通过率、拒绝率、超时率）
3. 会话时长（会话持续时间分布）

## 2. 指标口径

### 2.1 活跃

1. `DAU`：自然日内有至少一次有效交互的去重用户数。
2. `WAU`：最近 7 天有有效交互的去重用户数。
3. `MAU`：最近 30 天有有效交互的去重用户数。
4. `有效交互` 判定：
   - `messages`（消息表）新增一条用户消息；或
   - `audit_log`（审计日志）中存在成功命令事件（`event_type = 'command'` 且 `success = 1`）。

### 2.2 审批频次

1. `approval_requests_total`：周期内审批请求总数。
2. `approval_approved`：状态为 `approved` 的请求数。
3. `approval_denied`：状态为 `denied` 的请求数。
4. `approval_expired`：状态为 `expired` 的请求数。
5. `approval_rate`：`approval_approved / approval_requests_total`。
6. `approval_per_active_user`：`approval_requests_total / DAU`（DAU 为 0 时记为 0）。

### 2.3 会话时长

1. `session_duration_seconds`：`sessions.last_used - sessions.created_at`（最小为 0）。
2. `session_duration_p50/p90`：周期内会话时长分位值。
3. `long_session_ratio`：时长 >= 300 秒（5 分钟）的会话占比。

## 3. 数据来源

1. `sessions`：会话创建时间、最后活跃时间。
2. `messages`：用户交互活跃与消息频次。
3. `approval_requests`：审批请求生命周期状态。
4. `audit_log`：命令维度审计补充（用于活跃与链路诊断）。

## 4. 采集方案

### 4.1 现阶段（不改交互链路）

1. 直接基于现有表离线聚合（日级任务）产出指标。
2. 指标窗口固定支持：`1d/7d/30d`。
3. 产出结果保存为日报快照（建议后续新增 `metrics_daily_snapshot`）。

### 4.2 下一阶段（事件标准化）

为 Mini App 专用行为增加审计事件名，避免与 Telegram 行为混淆：

1. `miniapp_open`
2. `miniapp_timeline_view`
3. `miniapp_timeline_page`
4. `miniapp_session_export`

> 本阶段先定义口径，不强制绑定前端实现节奏。

## 5. 建议 SQL（示例）

```sql
-- DAU（最近 1 天）
SELECT COUNT(DISTINCT user_id) AS dau
FROM messages
WHERE timestamp >= datetime('now', '-1 day');

-- WAU（最近 7 天）
SELECT COUNT(DISTINCT user_id) AS wau
FROM messages
WHERE timestamp >= datetime('now', '-7 day');

-- 审批状态分布（最近 7 天）
SELECT status, COUNT(*) AS cnt
FROM approval_requests
WHERE created_at >= datetime('now', '-7 day')
GROUP BY status;

-- 会话时长（最近 30 天，单位秒）
SELECT
  session_id,
  MAX(CAST((julianday(last_used) - julianday(created_at)) * 86400 AS INTEGER), 0)
    AS session_duration_seconds
FROM sessions
WHERE created_at >= datetime('now', '-30 day');
```

## 6. iOS 立项准入建议（占位）

1. 连续 14 天指标稳定可得（无缺失日）。
2. 审批链路成功率可观测（批准/拒绝/过期均可追踪）。
3. 会话时长分布稳定（可计算 p50/p90，且样本量满足最小阈值）。

