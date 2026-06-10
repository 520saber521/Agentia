# 主从式 AI 协作工作流技术规范

## 1. 概述

本规范定义「1 个主 AI + N 个成员 AI」的协作模式，适用于：设计审查 → 任务分配 → 并行编码的完整开发流程。

**与主协议关系**：本文档基于 `README.md` 定义的消息协议，所有消息必须遵守其必填字段约束（`v/session/epoch/seq/id/agent_instance/from/to/type/ts`）。

## 2. 角色定义

| 角色 | 职责 | 窗口标题 | agent_id | from 字段 |
|------|------|---------|----------|----------|
| MAIN | 调度者、文档作者、任务分配者、问题解答者 | `[MAIN]` | MAIN | MAIN |
| A/B/C/D | 审查者、任务执行者 | `[Agent A]` ... | A/B/C/D | A/B/C/D |
| A-runner/B-runner/... | Agent 的 Runner 进程 | - | A-runner/B-runner | A-runner/B-runner |

**沟通规则**：
- 成员 AI 之间**不直接沟通**，所有消息通过 MAIN
- 成员 AI 不懂就找主 AI，主 AI 来安排

**reviewer 集合**：由 `team review --to` 参数指定，如 `A,B,C,D`

**一致性规则**：
- `to` 字段（外层）：定义消息路由目标，如 `A,B,C,D`
- `reviewers` 字段（body 内）：必须与 `to` 完全一致
- 统计"已响应"时以 `to` 解析结果为准，body 内 `reviewers` 仅用于确认

## 3. 消息格式约定

### 3.1 body 编码规则

- `body` 字段**必须为字符串**（单行 JSON 字符串），便于控制帧解析
- `body_encoding` 默认为 `json`，可选 `base64` 用于二进制
- 复杂结构使用 `body_ref` 指向外部存储（超过 4KB 时）

**注意**：与主协议 README.md 中 `body` 可以为普通字符串的约定不同，本文档要求 `body` 必须为 JSON 字符串，以支持结构化审查反馈。

### 3.2 时间字段约定

- `deadline`：Unix 秒级时间戳（如 `1710003600`），**外层字段**，仅用于 `action=assign` 任务分配
- `review_deadline`：Unix 秒级时间戳，**body 内字段**，仅用于 `action=review` 审查截止时间（默认当前时间 + 1 小时）
- clarify/verify 为问答类消息，不需要 `deadline` 或 `review_deadline`
- `ttl_ms`：毫秒级 TTL（如 `600000` = 10 分钟）
- CLI `--deadline` 支持两种格式：
  - 相对时间：`--deadline 3600` = 1 小时后（CLI 转换为 Unix 秒）
  - 绝对时间：`--deadline 1710003600` = 直接使用
- CLI 映射规则：
  - `team review --review-deadline` 或 `team review --deadline` → 写入 body `review_deadline`
  - `team assign --deadline` → 写入外层 `deadline`

### 3.3 必填字段清单

所有消息必须包含：
```json
{
  "v": 1,
  "session": "sess-8f3c",
  "epoch": 1,
  "seq": 101,
  "id": "MAIN-1-101",
  "agent_instance": "MAIN-aaaa",
  "from": "MAIN",
  "to": "A",
  "type": "ask",
  "ts": 1710000000
}
```

可选但推荐：
```json
{
  "task_id": "DOC-20240318-0001",
  "action": "review",
  "owner": "MAIN",
  "deadline": 1710003600,
  "corr": "MAIN-1-101",
  "ttl_ms": 600000
}
```
注：`deadline` 仅适用于 `action=assign`；review 使用 body `review_deadline`。

## 4. 消息类型定义

### 4.1 审查请求 (MAIN → Members)

```json
{
  "v": 1,
  "session": "sess-8f3c",
  "epoch": 1,
  "seq": 101,
  "id": "MAIN-1-101",
  "agent_instance": "MAIN-aaaa",
  "from": "MAIN",
  "to": "A,B,C,D",
  "type": "ask",
  "task_id": "DOC-20240318-0001",
  "action": "review",
  "owner": "MAIN",
  "ts": 1710000000,
  "body": "{\"doc_path\":\"docs/design.md\",\"focus\":[\"ux\",\"perf\",\"func\"],\"reviewers\":[\"A\",\"B\",\"C\",\"D\"],\"review_deadline\":1710003600}"
}
```

**字段说明**：
- review 请求使用 body 内的 `review_deadline` 定义截止时间（不使用外层 `deadline`）
- `review_deadline`：Unix 秒级时间戳，默认当前时间 + 1 小时
- MAIN 提示词中的"Always include deadline"要求不适用于 review 请求（特殊情况）

**body schema**：
```json
{
  "doc_path": "string (必填)",
  "focus": ["func", "perf", "ux"],
  "reviewers": ["A", "B", "C", "D"],
  "review_deadline": 1710003600
}
```

### 4.2 审查反馈 (Member → MAIN)

**有问题的反馈**：
```json
{
  "v": 1,
  "session": "sess-8f3c",
  "epoch": 1,
  "seq": 77,
  "id": "A-1-77",
  "agent_instance": "A-bbbb",
  "from": "A",
  "to": "MAIN",
  "type": "report",
  "action": "review_feedback",
  "task_id": "DOC-20240318-0001",
  "corr": "MAIN-1-101",
  "ts": 1710001200,
  "body": "{\"doc_path\":\"docs/design.md\",\"has_issues\":true,\"issue_count\":1,\"issues\":[{\"code_path\":\"src/router.py\",\"doc_path\":\"docs/design.md#3.4\",\"issue\":\"ACK stage semantics are inconsistent\",\"category\":\"func\",\"severity\":\"high\",\"suggested_fix\":\"Clarify delivered vs accepted\"}],\"summary\":\"1 high\",\"questions\":[]}"
}
```

**无问题的反馈**：
```json
{
  "v": 1,
  "session": "sess-8f3c",
  "epoch": 1,
  "seq": 78,
  "id": "A-1-78",
  "agent_instance": "A-bbbb",
  "from": "A",
  "to": "MAIN",
  "type": "report",
  "action": "review_feedback",
  "task_id": "DOC-20240318-0001",
  "corr": "MAIN-1-101",
  "ts": 1710001200,
  "body": "{\"doc_path\":\"docs/design.md\",\"has_issues\":false,\"issue_count\":0,\"summary\":\"No issues found\"}"
}
```

**body schema**：
```json
{
  "doc_path": "string (必填)",
  "has_issues": "boolean (必填)",
  "issue_count": "number (必填)",
  "issues": [
    {
      "code_path": "string (可选)",
      "doc_path": "string (必填)",
      "issue": "string (必填)",
      "category": "func|perf|ux|security|docs (必填，默认 func)",
      "severity": "high|medium|low (必填，默认 medium)",
      "suggested_fix": "string (可选)"
    }
  ] (可选，has_issues=false 时可省略),
  "summary": "string (可选)",
  "questions": ["string (可选)"]
}
```

### 4.3 审查完成 (Member → MAIN)

**无问题时直接发 done**：
```json
{
  "v": 1,
  "session": "sess-8f3c",
  "epoch": 1,
  "seq": 79,
  "id": "A-1-79",
  "agent_instance": "A-bbbb",
  "from": "A",
  "to": "MAIN",
  "type": "done",
  "task_id": "DOC-20240318-0001",
  "corr": "MAIN-1-101",
  "ts": 1710001200,
  "body": "{\"status\":\"no_issues\"}"
}
```

### 4.4 验证请求 (MAIN → Member)

用于"待确认"阶段，询问成员是否还有新问题。

```json
{
  "v": 1,
  "session": "sess-8f3c",
  "epoch": 1,
  "seq": 201,
  "id": "MAIN-1-201",
  "agent_instance": "MAIN-aaaa",
  "from": "MAIN",
  "to": "A",
  "type": "ask",
  "action": "verify",
  "task_id": "DOC-20240318-0001",
  "owner": "MAIN",
  "ts": 1710003600,
  "body": "{\"doc_path\":\"docs/design.md\",\"changes_summary\":\"Fixed 5 high issues\",\"question\":\"Any remaining issues?\"}"
}
```

**body schema**：
```json
{
  "doc_path": "string (必填)",
  "changes_summary": "string (可选)",
  "question": "string (必填)"
}
```

### 4.5 验证响应 (Member → MAIN)

**无问题**：
```json
{
  "v": 1,
  "session": "sess-8f3c",
  "epoch": 1,
  "seq": 80,
  "id": "A-1-80",
  "agent_instance": "A-bbbb",
  "from": "A",
  "to": "MAIN",
  "type": "done",
  "action": "verified",
  "task_id": "DOC-20240318-0001",
  "corr": "MAIN-1-201",
  "ts": 1710003700,
  "body": "{\"has_new_issues\":false}"
}
```

**有新问题**：发 `report` 消息（见 4.2）

**verified body schema**：
```json
{
  "has_new_issues": "boolean (必填)",
  "new_issue_count": "number (可选，has_new_issues=true 时必填)"
}
```

### 4.6 任务分配 (MAIN → Members)

```json
{
  "v": 1,
  "session": "sess-8f3c",
  "epoch": 1,
  "seq": 301,
  "id": "MAIN-1-301",
  "agent_instance": "MAIN-aaaa",
  "from": "MAIN",
  "to": "A",
  "type": "ask",
  "action": "assign",
  "task_id": "FEAT-001-A",
  "owner": "MAIN",
  "deadline": 1710007200,
  "ts": 1710004000,
  "body": "{\"task_type\":\"implement\",\"files\":[\"src/auth.py\"],\"success_criteria\":[\"Tests pass\",\"Code reviewed\"],\"dependencies\":[]}"
}
```

**body schema**：
```json
{
  "task_type": "implement|review|test|refactor (必填)",
  "files": ["string (必填)"],
  "success_criteria": ["string (必填)"],
  "dependencies": ["task_id (可选)"]
}
```

**说明**：外层 `action=assign` 表示"分配任务"，body 内 `task_type` 表示具体任务类型。

### 4.7 编码阶段询问 (Member → MAIN)

```json
{
  "v": 1,
  "session": "sess-8f3c",
  "epoch": 1,
  "seq": 88,
  "id": "A-1-88",
  "agent_instance": "A-bbbb",
  "from": "A",
  "to": "MAIN",
  "type": "ask",
  "action": "clarify",
  "task_id": "FEAT-001-A",
  "owner": "A",
  "ts": 1710005000,
  "body": "{\"code_path\":\"src/router.py#L145\",\"question\":\"retry backoff strategy?\",\"context\":\"Implementing ACK retry\",\"expected\":\"exponential or linear?\"}"
}
```

**body schema**：
```json
{
  "code_path": "string (必填)",
  "question": "string (必填)",
  "context": "string (必填)",
  "expected": "string (可选，期望的解答方向)"
}
```

### 4.8 编码阶段解答 (MAIN → Member)

```json
{
  "v": 1,
  "session": "sess-8f3c",
  "epoch": 1,
  "seq": 302,
  "id": "MAIN-1-302",
  "agent_instance": "MAIN-aaaa",
  "from": "MAIN",
  "to": "A",
  "type": "send",
  "action": "answer",
  "task_id": "FEAT-001-A",
  "owner": "MAIN",
  "corr": "A-1-88",
  "ts": 1710005100,
  "body": "{\"strategy\":\"exponential_backoff\",\"base_delay_ms\":100,\"max_delay_ms\":5000,\"max_retries\":3,\"doc_updated\":true}"
}
```

### 4.9 通用控制消息

**ACK**（传输层，Runner 自动发送）：
```json
{
  "v": 1,
  "session": "sess-8f3c",
  "epoch": 1,
  "seq": 1,
  "id": "runner-ack-1",
  "agent_instance": "runner-xxxx",
  "from": "A-runner",
  "to": "MAIN",
  "type": "ack",
  "corr": "MAIN-1-101",
  "ack_stage": "delivered",
  "ts": 1710000001
}
```

**NACK**（拒绝）：
```json
{
  "v": 1,
  "session": "sess-8f3c",
  "epoch": 1,
  "seq": 2,
  "id": "runner-nack-1",
  "agent_instance": "runner-xxxx",
  "from": "A-runner",
  "to": "MAIN",
  "type": "nack",
  "corr": "MAIN-1-101",
  "reason": "queue_full",
  "ts": 1710000001
}
```

**应用层 ACK**（Agent 发送）：
```json
{
  "v": 1,
  "session": "sess-8f3c",
  "epoch": 1,
  "seq": 76,
  "id": "A-1-76",
  "agent_instance": "A-bbbb",
  "from": "A",
  "to": "MAIN",
  "type": "ack",
  "corr": "MAIN-1-101",
  "ack_stage": "accepted",
  "ts": 1710000005
}
```

**FAIL**（任务失败）：
```json
{
  "v": 1,
  "session": "sess-8f3c",
  "epoch": 1,
  "seq": 99,
  "id": "A-1-99",
  "agent_instance": "A-bbbb",
  "from": "A",
  "to": "MAIN",
  "type": "fail",
  "task_id": "FEAT-001-A",
  "corr": "MAIN-1-301",
  "ts": 1710006000,
  "body": "{\"reason\":\"Cannot proceed without clarification\",\"blocked_by\":[\"DOC-20240318-0001\"]}"
}
```

**fail body schema**：
```json
{
  "reason": "string (必填)",
  "blocked_by": ["task_id (可选，阻塞此任务的任务ID列表)"]
}
```

## 5. 字段枚举值

### 5.1 category (必填，默认 func)

| 值 | 说明 |
|----|------|
| func | 功能完整性 |
| perf | 性能 |
| ux | 用户体验 |
| security | 安全 |
| docs | 文档 |

### 5.2 severity (必填，默认 medium)

| 值 | 说明 |
|----|------|
| high | 阻塞问题，必须解决 |
| medium | 重要问题，建议解决 |
| low | 优化建议 |

### 5.3 action 类型

| 值 | 方向 | 说明 |
|----|------|------|
| review | MAIN→Members | 审查文档/代码 |
| review_feedback | Member→MAIN | 反馈审查结果 |
| assign | MAIN→Members | 分配任务 |
| clarify | Member→MAIN | 询问问题 |
| answer | MAIN→Member | 解答问题 |
| verify | MAIN→Members | 验证是否还有问题 |
| verified | Member→MAIN | 确认无问题 |

### 5.4 reason (NACK/Fail)

| 值 | 说明 |
|----|------|
| queue_full | 队列满 |
| invalid_format | 格式错误 |
| not_authorized | 无权限 |
| task_cancelled | 任务已取消 |
| deadline_exceeded | 超时 |
| missing_dependency | 依赖缺失 |

## 6. 状态机

### 6.1 文档审查阶段

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  文档审查中  │ ──▶ │  问题收集   │ ──▶ │   改进中    │ ──▶ │   待确认    │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
       ▲                                                            │
       │                                                            │
       └──────────────── 新 report 重新进入 ◄──────────────────────┘
```

| 状态 | 触发条件 | 结束条件 | MAIN 行为 | 超时处理 |
|------|---------|---------|-----------|----------|
| 文档审查中 | MAIN 发 review ask | 所有 reviewer 响应或超时 | 等待所有反馈 | 超时后未回复者标记 done |
| 问题收集 | 有 reviewer 报告问题 | 所有问题汇总完成 | 汇总并分类问题 | 继续汇总 |
| 改进中 | 开始编辑文档 | 修改完成 | 更新文档 | 无超时（人工控制） |
| 待确认 | 发送 verify ask | 无新问题（全 verified 或超时） | 询问成员 | 超时后视为无问题 |

### 6.2 编码阶段

| 状态 | 触发条件 | 结束条件 | MAIN 行为 | 超时处理 |
|------|---------|---------|-----------|----------|
| 任务分配 | MAIN 发 assign | 所有成员收到任务 | 追踪任务状态 | 超时后重发或标记 fail |
| 编码执行 | 成员开始工作 | 成员发 done/fail | 回答 clarify | 按 deadline 处理 |
| 完成 | 所有任务 done | - | 进入下一阶段 | - |

**reviewer 响应规则**：
- 有问题：发 `report` 消息（has_issues=true）
- 无问题：发 `done` 消息或发 `report`（has_issues=false）
- 两者都算"已响应"

**超时规则**：
- review_deadline：默认 1 小时（`team review --review-deadline` 或 `--deadline`，均写入 body `review_deadline`）
- verify 超时：默认 10 分钟，无回复视为"无问题"

## 7. CLI 命令

### 7.1 命令与协议映射

| CLI 命令 | 协议类型 | action |
|---------|---------|--------|
| team review | ask | review |
| team report | report | review_feedback |
| team assign | ask | assign |
| team ask | ask | clarify/verify |
| team send | send | answer |
| team done | done | verified (验证响应) / 任务完成 |
| team fail | fail | - (任务失败) |
| team broadcast | broadcast | - |
| team status | - | - (查询) |
| team trace | - | - (查询) |

### 7.2 命令示例

```bash
# 分配审查任务
team review \
  --to A,B,C,D \
  --task DOC-20240318-0001 \
  --owner MAIN \
  --file docs/design.md \
  --focus func,perf,ux \
  --review-deadline 3600 \
  --wait accepted

# 分配实现任务
team assign \
  --to B \
  --task FEAT-001-B \
  --action implement \
  --files src/router.py \
  --success-criteria "Tests pass,Code reviewed" \
  --deadline 3600

# 注：CLI --action implement 映射到 body 内 task_type=implement，外层 action 保持为 assign
# 注：team review 的 --deadline 是 --review-deadline 的别名，都会写入 body review_deadline

# 验证是否还有问题
team ask \
  --to A \
  --action verify \
  --task DOC-20240318-0001 \
  --doc-path docs/design.md \
  --changes-summary "Fixed 5 high issues" \
  --question "Any remaining issues?"

# 查看任务状态
team status --tasks --filter DOC-20240318-0001

# 消息追踪
team trace --task DOC-20240318-0001
team trace --id MAIN-1-101

# 广播通知
team broadcast --body "Design review complete, starting implementation phase"

# 成员完成任务
team done --task FEAT-001-A --to MAIN

# 成员确认验证（无新问题）
team done --action verified --task DOC-20240318-0001 --to MAIN

# 成员任务失败
team fail --task FEAT-001-A --to MAIN --reason "Cannot proceed without clarification"
```

### 7.3 --wait 语义

| 参数 | 等待级别 | 说明 |
|------|---------|------|
| `--wait delivered` | 传输层 ACK | 消息已投递到 Runner |
| `--wait accepted` | 应用层 ACK | Agent 已读取并进入处理 |
| `--wait done` | 完成事件 | 等待 done/fail（注意：review 可能仅返回 report） |
| 无参数 | 立即返回 | 仅确认消息入队 |

## 8. MAIN 调度提示词框架

```
You are MAIN, the coordinator of this AI team.

CORE RULES:
- Members (A/B/C/D) NEVER talk to each other directly
- All questions route through YOU
- Always include: v, session, epoch, seq, id, agent_instance, from, to, type, ts
- Task assignment (assign) MUST include: task_id, action, owner, deadline
- Review requests use review_deadline in body (not outer deadline)
- Clarify/verify questions: include task_id, action, owner (no deadline needed)
- Reply messages (answer/verified/done): include task_id, action (owner optional, no deadline needed)
- Send status updates when state changes

REVIEW PROTOCOL:
1. Dispatch review asks with focus areas: func, perf, ux
2. Wait for response (report or done) from each reviewer
3. Aggregate issues and improve documentation
4. Send verify ask to confirm fixes
5. Loop until no new issues

WORK ASSIGNMENT:
1. Split tasks by file ownership
2. Include files, success_criteria, dependencies
3. Require done/fail on completion
4. Answer clarification questions from members

OUTPUT FORMAT:
# 文档审查阶段
STATE: <文档审查中|问题收集|改进中|待确认>
# 编码阶段
STATE: <任务分配|编码执行|完成>
NEXT ACTIONS: <team commands to send>
DOC CHANGES: <files/sections to edit>
QUESTIONS: <clarifications needed>
```

## 9. 典型工作流

```
1. 用户: "我们来做项目 X"
   └─▶ MAIN 和用户讨论，写 docs/design.md

2. MAIN: team review --to A,B,C,D --file docs/design.md --task DOC-001
   └─▶ 消息: type=ask action=review
   └─▶ A/B/C/D 发: type=ack ack_stage=accepted

3. A/B/C 审查完成
   └─▶ A/B/C 发: type=report (有 issues)
   └─▶ D 发: type=done (无 issues)

4. MAIN 收集响应，发现 5 个问题
   └─▶ MAIN 改进 docs/design.md

5. MAIN: team ask --to A,B,C --action verify --task DOC-001
   └─▶ A/B 发: type=done action=verified (无新问题)
   └─▶ C 发: type=report (发现新问题)

6. MAIN 继续改进 → 循环直到所有人都 verified

7. MAIN: team assign --to A --task FEAT-001-A --files src/auth.py
   MAIN: team assign --to B --task FEAT-001-B --files src/router.py
   MAIN: team assign --to C --task FEAT-001-C --files src/state.py

8. A 遇到问题
   └─▶ A 发: type=ask action=clarify
   └─▶ MAIN 发: type=send action=answer
   └─▶ MAIN 可能更新 docs/design.md

9. A/B/C 完成
   └─▶ A/B/C 发: type=done task_id=FEAT-001-A/B/C

10. MAIN 组织 code review
```

## 10. 编码阶段规则

文档审查完成后进入编码阶段（细节见 4.6-4.9 与 6.2），关键要求：

1. **任务分配**：MAIN 使用 `team assign` 分配任务，必须包含 `files`、`success_criteria`、`deadline`
2. **问题询问**：成员用 `team ask --action clarify` 询问，body 必须包含 `code_path` / `question` / `context`（`expected` 可选）
3. **完成报告**：成功 `type=done`；失败 `type=fail` 并说明原因

## 11. 错误处理

### 11.1 NACK 处理

| reason | 处理策略 |
|--------|---------|
| queue_full | 等待后重试 |
| invalid_format | 修正格式后重试 |
| not_authorized | 检查权限配置 |
| task_cancelled | 停止处理 |
| deadline_exceeded | 申请新 deadline |
| missing_dependency | 等待依赖完成 |

### 11.2 超时处理

- 审查超时：标记未回复者 done（视为无问题），继续流程
- 验证超时：视为无问题，进入下一阶段
- 任务超时：标记为 fail，通知 MAIN
