# Debug Session: stuck-agent-execution

Status: [OPEN]

## Problem
当前系统中存在两个 agent 长期处于“执行中”状态，疑似任务状态没有正确收敛或资源没有释放。

## Hypotheses
1. 任务完成后没有可靠地写回终态，导致前端/数据库仍显示为 executing。
2. 并发调度中存在未被等待的后台任务或异常分支，状态更新被跳过。
3. 超时控制缺失或超时后没有进入失败终态，导致任务无限挂起。
4. 某些 agent 的流式执行/网络调用没有关闭连接或结束流，阻塞后续状态清理。
5. 任务状态更新与消息事件广播存在竞态，前端收到开始事件但未收到结束事件。

## Evidence Log
- Pending

## Notes
- First code change must be instrumentation only.
- Collect runtime evidence before any fix.
