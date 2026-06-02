# Debug Session: task-status-stuck

Status: [OPEN]

## Symptom

用户在网页测试 F-W3-3 任务状态卡片与实时更新时，Orchestrator 复杂任务已经产生 Agent 回复，并且父任务卡片显示“已完成 / All 4 subtasks completed”，但多个子任务卡片仍显示“执行中”。用户询问任务不能执行完成是否因为没有真实 API KEY。

## Hypotheses

1. 子任务真实执行已完成，但后端推送的 `task_update` 使用了旧的 Task ORM 对象，导致前端收到的子任务状态仍是 `running`。
2. 某些子任务分派到 `agent_claude` 或 `agent_deepseek`，由于缺少真实 API KEY，Adapter 初始化失败或错误 chunk 导致子任务失败/卡住。
3. 后端 Task 状态枚举与 F-W3-3 规格不一致，`planning` / `blocked` / `conflict` 等状态无法被持久化或正确推送。
4. 前端 reducer 已接收 `task_update`，但 TaskStatusCard 只做扁平展示，没有父子聚合、总进度和失败原因列表，所以视觉上像“未完成”。
5. 任务完成事件缺少 `message_id` 映射，导致点击子任务无法定位对应 Agent 消息，进一步造成“任务卡片没有闭环”的体验。

## Evidence Plan

- 检查后端最新日志，确认 Orchestrator 是否记录 all subtasks completed。
- 检查 `_dispatch_subtask_with_result` 是否在更新子任务状态后推送了最新 Task 对象。
- 检查 Task 状态枚举和前端 reducer/TaskStatusCard 对 F-W3-3 的覆盖范围。
- 检查默认 Agent 配置是否会因为缺少 API KEY 导致失败。
