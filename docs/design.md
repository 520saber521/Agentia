# Codex 团队编排 - 设计文档

## 1. 概述
本文档定义本地多窗口 Codex 团队协作的完整设计方案。系统支持用一条命令
启动多个 Codex 窗口（MAIN + A/B/C/D），并通过本地消息路由实现可靠、严格
符合协议的通信。文档作为主架构参考，完整覆盖启动与运行流程。

## 2. 目标
- 一条命令启动完整团队（MAIN + A/B/C/D），每个角色独立终端窗口。
- 成员仅通过本地路由通信，严格遵守统一消息 schema。
- 支持 review -> improve -> verify -> assign -> execute -> done/fail 全流程。
- 可靠投递：ACK、超时、重试规则明确。
- 可追溯：可按 session/task 查询状态与消息历史。
- 适配 macOS 终端（默认 Terminal.app），支持可选适配器。

## 3. 非目标
- 云端部署或多机互联。
- 成员间直连通信（A/B/C/D 不直接沟通）。
- 替代 Codex CLI，本系统只负责编排与通信。

## 4. 运行环境
- 操作系统：macOS。
- 终端：默认 Terminal.app，可选 iTerm2。
- 工作区：本地目录（如 /Users/...）。
- 网络：本地回环通信，不依赖外部消息服务。

## 5. 系统架构

核心组件：

1) 启动器（Launcher）
- 启动 Router 并打开多个终端窗口。
- 为每个角色注入环境变量（TEAM_ROLE, TEAM_AGENT_ID, TEAM_SESSION）。

2) 路由器（Router / Message Bus）
- 本地服务，负责消息路由到各自 inbox。
- 管理 ACK、重试、超时、持久化。

3) Agent Runner
- 每个窗口里的 Codex 包装层。
- 连接 Router 发送/接收消息，发送应用层 ACK。

4) Team CLI
- 生成符合协议的消息（review/assign/ask/send/done/fail）。
- 查询 Router 的 status/trace。

5) 存储层（Storage）
- 会话元数据、消息日志、各 agent inbox。
- 支持崩溃恢复和消息回放。

ASCII 图示：

  +-----------+     +--------+     +------------------+
  | Launcher  | --> | Router | <-> | Storage (local)  |
  +-----------+     +--------+     +------------------+
       |                ^
       v                |
  +-----------+         |
  | Agent A   | --------+
  +-----------+
  +-----------+
  | Agent B   | --------+
  +-----------+
  +-----------+
  | Agent C   | --------+
  +-----------+
  +-----------+
  | Agent D   | --------+
  +-----------+

## 6. 核心工作流程（与协议对齐）

1) 启动会话
- team start 创建 session/epoch，启动 Router，打开 MAIN + A/B/C/D。

2) 审查阶段
- MAIN 发 review 请求给 A/B/C/D。
- 成员返回 report 或 done。

3) 改进阶段
- MAIN 汇总问题、修改文档，然后发 verify 请求。
- 成员返回 verified（done）或新的 report。

4) 分配阶段
- MAIN 发送 assign 任务，包含 deadline 和成功标准。

5) 执行阶段
- 成员需要时发 clarify。
- MAIN 回复 answer；成员完成后发 done 或 fail。

6) 完成阶段
- MAIN 查询状态并闭环。

## 7. 消息协议（与 main-members-workflow 对齐）

通用必填字段：
- v, session, epoch, seq, id, agent_instance, from, to, type, ts

消息类型（type）：
- ask, report, send, done, fail

动作类型（action）：
- review, review_feedback, assign, clarify, answer, verify, verified

body 编码规则：
- body 始终为单行字符串（不含换行）。
- body_encoding=json（默认）：body 为 JSON 字符串，顶层必须是 object。
- body_encoding=base64：body 为 base64 字符串；如需结构化内容，可在解码后再解析。
- 超过 4KB 或需要外部存储时，用 body_ref 指向外部存储；此时 body 可为空字符串，读取端优先使用 body_ref。

deadline 规则：
- review 使用 body 内 review_deadline。
- assign 使用外层 deadline。
- clarify/verify 不需要 deadline。

一致性规则：
- review 请求中 body.reviewers 必须与外层 to 完全一致。

ACK 规则：
- delivered：传输层 ACK（runner）。
- accepted：应用层 ACK（agent）。

字段要求与生成规则：
- 必填字段：v, session, epoch, seq, id, agent_instance, from, to, type, ts。
- 推荐字段：task_id, action, owner, deadline, corr, ttl_ms。
- seq 由 Router 生成并在 session 范围内全局单调递增；agent 不应自行自增。
- id 由 Router 生成，推荐格式 <session>-<epoch>-<seq>；必须与 session/epoch/seq 一致且唯一。
- corr 指向被回复消息 id，用于链路追踪；对 report/send/done/fail/verified 类回复消息必填。
- ts 由 Router 生成（ms），用于事件排序；校验需保证大体递增即可。
- body_encoding 默认 json；二进制或非 JSON 内容用 base64。

字段校验要点（Router）：
- 必填字段完整且类型正确（to 为非空数组，type/action 为合法枚举）。
- seq=last_seq+1；id 与 session/epoch/seq 组合一致。
- corr 若存在必须引用已知 id。
- body_encoding=json 时 body 必须可解析为 JSON object。

枚举值（对齐主流程文档）：
- category：func / perf / ux / security / docs。
- severity：high / medium / low。
- nack/fail reason：queue_full / invalid_format / not_authorized / task_cancelled /
  deadline_exceeded / missing_dependency。

常用消息 body 摘要：
- review ask：doc_path, focus[], reviewers[], review_deadline
- review_feedback report：doc_path, has_issues, issue_count, issues[], summary, questions[]
- done（无问题）：body={"status":"no_issues"}
- verify ask：doc_path, changes_summary, question
- verified done：has_new_issues, new_issue_count(可选)
- assign ask：task_type, files[], success_criteria[], dependencies[]
- clarify ask：code_path, question, context, expected(可选), doc_path(可选)
- answer send：结构化解答字段，可包含 doc_updated=true
- fail：reason, blocked_by[]
- nack：reason（queue_full/invalid_format 等）

JSON 示例（body 为单行字符串）：
- clarify ask：
```json
{
  "v": "1",
  "session": "sess-123",
  "epoch": 2,
  "seq": 101,
  "id": "sess-123-2-101",
  "agent_instance": "A-01",
  "from": "A",
  "to": ["MAIN"],
  "type": "ask",
  "action": "clarify",
  "task_id": "DOC-20240318-0001",
  "ts": 1690000100000,
  "body_encoding": "json",
  "body": "{\"code_path\":\"src/router.py#L145\",\"question\":\"retry backoff?\",\"context\":\"当前是固定500ms\",\"expected\":\"是否需要指数退避？\",\"doc_path\":\"docs/design.md#L120\"}"
}
```
- review_feedback report（多问题/多路径）：
```json
{
  "v": "1",
  "session": "sess-123",
  "epoch": 2,
  "seq": 140,
  "id": "sess-123-2-140",
  "agent_instance": "B-02",
  "from": "B",
  "to": ["MAIN"],
  "type": "report",
  "action": "review_feedback",
  "task_id": "DOC-20240318-0001",
  "corr": "sess-123-2-120",
  "ts": 1690000200000,
  "body_encoding": "json",
  "body": "{\"doc_path\":\"docs/design.md\",\"has_issues\":true,\"issue_count\":2,\"issues\":[{\"issue_group\":\"msg-format-1\",\"doc_path\":\"docs/design.md#L110\",\"code_paths\":[\"src/router.py#L50\",\"src/router.py#L88\"],\"code_span\":{\"start_line\":50,\"end_line\":88},\"category\":\"func\",\"severity\":\"high\",\"summary\":\"seq/id 规则与数据模型冲突\",\"suggestion\":\"由 Router 生成并使用 <session>-<epoch>-<seq>\"},{\"doc_path\":\"docs/design.md#L140\",\"doc_paths\":[\"docs/ops.md#L30\",\"docs/design.md#L150\"],\"category\":\"docs\",\"severity\":\"medium\",\"summary\":\"ack 规则缺少超时说明\",\"suggestion\":\"补充 ack_timeout 行为\"}],\"summary\":\"发现2处需要调整以匹配流程\",\"questions\":[\"report 是否允许无 corr？\",\"issue_count 是否必须与 issues 长度一致？\"]}"
}
```
- assign ask：
```json
{
  "v": "1",
  "session": "sess-123",
  "epoch": 2,
  "seq": 155,
  "id": "sess-123-2-155",
  "agent_instance": "MAIN-01",
  "from": "MAIN",
  "to": ["C"],
  "type": "ask",
  "action": "assign",
  "task_id": "FEAT-001-C",
  "owner": "MAIN",
  "deadline": 1690003600000,
  "ts": 1690000300000,
  "body_encoding": "json",
  "body": "{\"task_type\":\"implement\",\"files\":[\"src/router.py\",\"src/state.py\"],\"success_criteria\":[\"按第7节更新 seq/id/corr 规则\",\"补充相关测试\"],\"dependencies\":[\"DOC-20240318-0001\"]}"
}
```

人类可读显示格式（问答类消息）：
- 用于 clarify/verify 等提问场景，终端统一输出单行格式，便于快速扫描。
- 格式：窗口:<from> | 问题:<question> | 文档路径:<doc_path or -> | 代码路径:<code_path or ->
- 示例：窗口:A | 问题: retry backoff? | 文档路径: docs/design.md | 代码路径: src/router.py#L145

多文件/多行问题表达（兼容扩展）：
- 标准做法：issues[] 多条记录，每条绑定一个 doc_path + 可选 code_path。
- 需要归并同一问题时，使用可选字段 issue_group 标记同组问题。
- 若必须在同一条 issue 内表达多个路径，可加扩展字段：
  - code_paths[] / doc_paths[]（数组）
  - code_span（结构化行号：{start_line, end_line}）
- 推荐写法与顺序（issue 记录内）：
  - issue_group -> doc_path/doc_paths[] -> code_path/code_paths[] -> code_span -> category/severity -> summary/suggestion
  - code_paths[]/doc_paths[] 先按路径字典序，再按行号升序，保证确定性
- Router 仅透传扩展字段，兼容现有 schema。

## 8. 数据模型

Session：
- session_id：首次 team start 生成（UUID v4），写入 meta/session.json；同一 workspace 重启复用。
- epoch：Router 每次冷启动自增（从 1 开始），写入 state/router.json。
- seq：单调递增的全局序号（以 session 为范围）；Router 发送消息前先读取 last_seq，seq=last_seq+1 并落盘。
- created_at, workspace, roles

Message：
- id, session, epoch, seq, corr, from, to, type, action, task_id, ts, body（string）
- body_ref（可选，大体积 body 的落盘路径）

Inbox：
- 每个 agent 的消息队列（message ids），仅保留 delivered 未 accepted

State：
- router：epoch, last_seq, last_ts
- tasks：task_id -> {status, owner, deadline, retries, last_update_seq}
- delivery：id -> {status, retry_count, last_ts}

存储结构（根目录为 <workspace>/.codex_team/）：
- meta/session.json（session_id, created_at, workspace, roles）
- state/router.json（epoch, last_seq）
- state/tasks.json（任务快照）
- inbox/<agent>.jsonl（inbox 事件流）
- logs/messages-<epoch>.jsonl（消息事件）
- logs/acks-<epoch>.jsonl（ACK 事件）
- blobs/<id>.json（body_ref 内容，按需生成）

日志格式（JSONL，每行一条，append-only）：
- message：{"event":"message","session":"...","epoch":1,"seq":12,"id":"...","from":"MAIN","to":["A"],"type":"ask","action":"assign","task_id":"T1","ts":1690000000000,"body":"...","body_ref":null}
- ack：{"event":"ack","id":"...","ack":"delivered|accepted","agent":"A","ts":1690000000100}
- inbox：{"event":"deliver","id":"...","ts":1690000000000} / {"event":"accepted","id":"...","ts":1690000000200}

## 9. 可靠性与投递

投递流程（receive -> enqueue -> ACK -> retry）：
- Router 接收消息，校验必要字段（message_id/ttl_ms/deadline）并补齐缺省值。
- 写入持久 outbox；写入失败则返回 error，不发送 ACK。
- 将消息入队到目标 inbox（持久化）；入队成功后返回 delivered。
- Agent Runner 拉取或被推送后读取消息，回 accepted；Router 标记 accepted 并停止重试。
- 若在 ack_timeout 内未收到 accepted，则进入重试队列，按重试策略重新入队（幂等依赖 message_id）。

ACK 策略：
- delivered：仅当 inbox 入队成功后发送。
- accepted：仅当 Runner 实际读取消息后发送。
- Router 持久化保存 delivered/accepted 状态，防止重启后重复重投。

重试与超时：
- ack_timeout 默认 2 分钟；首次投递后开始计时。
- retry_backoff 默认 30s、2m、5m、10m、10m（上限 10m，含抖动 ±20%）。
- max_retries 默认 5 次（不含首次投递）；达到 max_retries 或超过 ttl_ms/deadline 立即失败。
- 失败升级：失败时通知 MAIN，附 message_id、目标、最后错误与重试次数。
- 重试期间若收到 accepted，则立即终止后续重试与提醒。

幂等：
- Router 以 message id 去重。
- 客户端忽略重复消息，依赖 id 做去重。

默认时限与响应规则：
- review_deadline 必须存在；未指定时由 CLI/Router 填充默认 1 小时。
- verify 超时默认 10 分钟，无回复视为无新问题。
- reviewer 响应规则：report 或 done 都算“已响应”。
- review 超时：未回复者标记 done 继续流程。

在线状态与心跳（presence/heartbeat）：
- 仅用于标记窗口在线状态，不等同于消息 ACK。
- Runner 建立连接后发送 presence.register：
  - agent=agent_instance
  - meta={role, session, epoch, window_name, ts}
- 可选心跳：默认 30s 一次；Router 超过 2 个心跳间隔未收到视为离线。
- Router 侧逻辑由 C 窗口实现；D 窗口只负责客户端侧连接与注册调用。

## 10. 沟通机制与提醒

基本方式：
- A/B/C/D 通过 clarify 向 MAIN 提问，消息进入 MAIN 的 inbox。
- MAIN 通过 answer 回复，并在必要时完善文档后再发 verify 复核。

文档完善要求（避免成员看不懂）：
- 只要成员表示不清楚，MAIN 必须先补充对应文档，再回复 answer。
- 文档必须给出可执行细节：编码路径、方法/函数名、步骤或算法、边界条件。
- 明确落点：写清楚 doc_path 位置，引用代码路径与行号范围。
- 提供可验证标准：期望输出、测试要点或成功标准。
- 禁止含糊指令：不能只说“按常规处理”，必须具体到文件与实现方式。

MAIN 忙碌或忘记读取的兜底：
- inbox 持久化：消息不会丢失，可随时回看与追溯。
- 推送或轮询：Runner 主动拉取或 Router 推送新消息。
- 未读提醒：终端标题/通知展示未读数量与最久未读时长；新未读到达时高亮提示并置顶。
- 超时升级：accept_timeout（默认 2 分钟）未被 accepted 即重投并标记“需处理”；question_deadline（默认 30 分钟）未关闭则升级为 alert 提醒。
- 状态查询：MAIN 可用 team status/trace 获取待处理问题。

## 11. Agent 启动提示词模板

MAIN（主 AI）模板：
- 角色：协调、分配任务、完善文档、回答问题，不直接编码。
- 通信：只与 A/B/C/D 交互，所有问题必须回到 MAIN。
- 工作流：review -> 改进 -> verify -> assign -> 执行 -> done/fail。
- 处理原则：收到 clarify 必须先更新文档再回答，并持续沟通直到无问题。
- 文档要求：补充编码路径、方法/函数名、实现步骤、边界条件、成功标准。
- 输出约束：消息必须遵循协议，body 为单行 JSON 字符串。
- 人类可读显示：窗口:<from> | 问题:<question> | 文档路径:<doc_path or -> | 代码路径:<code_path or ->

成员（A/B/C/D）模板：
- 角色：审查/执行任务，不与其他成员直接沟通，只与 MAIN 交互。
- 提问格式：clarify 必须包含 question/context/code_path，doc_path 建议提供。
- 多问题表达：使用 issues[] 分条列出；跨多文件可用 issue_group 或 code_paths[]。
- 无问题时：发送 done 或 report(has_issues=false)。
- 输出约束：消息必须遵循协议，body 为单行 JSON 字符串。

## 12. 安全与隔离
- 只有 MAIN 与 A/B/C/D 通信。
- Router 强制路由规则：to 仅允许 A/B/C/D/MAIN。
- 默认仅本地监听，不对外暴露。
- `--dangerously-bypass-approvals-and-sandbox` 仅限本地可信工作区使用；启动命令必须显式传入，禁止在远程/共享环境使用。

## 13. 终端启动策略

启动顺序（team start）：
1) team start 创建 session/epoch 并启动 Router。
2) Router ready 后，Launcher 打开 MAIN + A/B/C/D 窗口。
3) 每个窗口注入环境变量并启动 Runner。
4) Runner 连接 Router 并注册在线状态（presence/heartbeat），完成后进入消息循环。
   注：ACK 仅由消息投递触发（delivered/accepted），不用于启动握手。

环境变量（每窗口必填）：
- `TEAM_ROLE`：MAIN/A/B/C/D
- `TEAM_AGENT_ID`：<role>-<uniq>
- `TEAM_SESSION`：session id
- `TEAM_EPOCH`：epoch number
- `TEAM_WINDOW_NAME`：推荐 `team-<session>-<role>`，用于终端窗口标题

默认（macOS Terminal.app）：
- 使用 AppleScript 为每个角色打开窗口并执行：
  TEAM_ROLE=... TEAM_AGENT_ID=... TEAM_SESSION=... TEAM_EPOCH=... TEAM_WINDOW_NAME=... codex --dangerously-bypass-approvals-and-sandbox -C <workspace>

可选（iTerm2）：
- 使用 iTerm2 AppleScript 模板，环境变量一致。

备用（tmux）：
- 若无法开多窗口，单终端 5 个 pane。
- pane 标题使用 `TEAM_WINDOW_NAME` 方便识别。

## 14. CLI 能力范围（MVP）

team start
- 创建 session/epoch，启动 Router，打开窗口。

team review / assign / ask / send / done / fail
- 发送协议消息。

team status / trace
- 查询任务/会话状态与消息历史。

team inbox
- 拉取指定 agent 的 inbox；默认使用 TEAM_AGENT_ID，并自动回 accepted ACK。

人话沟通快捷命令：
- team say：用自然语言发问（内部转为 clarify），自动补充 task_id/owner/code_path/context。
- team reply：用自然语言回复（内部转为 answer），可自动从 corr 推断 task_id。
- team listen：人类可读方式监听消息（窗口/问题/路径）。
- 启动时自动监听：team start 会在每个窗口后台启动 listen（写入日志并通知）。
- 默认行为：所有窗口使用 listen --auto-input，确保消息直接注入到对应窗口并可见。
- 自动输入（成员窗口，默认）：listen --auto-input 会把消息注入对应终端窗口输入框并回车，确保可见。
  - 依赖 macOS Terminal/iTerm2 AppleScript；通过 `TEAM_WINDOW_NAME` 定位窗口，需要系统允许「辅助功能」访问。
  - 若自动输入失败，会回发一条提示消息（AUTO-INPUT FAILED）给发件人。
- 自动回复（可选）：listen --auto-reply 会调用 codex exec 自动生成回复并回发给 MAIN。
  - 默认提示词：prompts/agent_member.txt（可用 --prompt-path 指定）。
- 待处理提醒：listen 会记录未回复的 ask 到 `~/.codex_team/pending-<agent_id>.json`，超时自动提醒并可重复注入输入框。

命令与协议映射：
- team review -> type=ask, action=review（review_deadline 写入 body）。
- team report -> type=report, action=review_feedback。
- team assign -> type=ask, action=assign（deadline 在外层）。
- team ask -> type=ask, action=clarify 或 verify。
- team send -> type=send, action=answer。
- team done -> type=done（可用于 verified 或任务完成）。
- team fail -> type=fail。

等待语义（可选）：
- --wait delivered：传输层 ACK。
- --wait accepted：应用层 ACK。
- --wait done：等待 done/fail（review 场景可能仅 report）。

推荐参数与用法（示例）：
- review：必须包含 `--to`、`--task`、`--file`；`--review-deadline/--deadline` 推荐显式提供，未提供则默认 1 小时（CLI/Router 自动填充）。推荐 `--wait accepted`。
- assign：必须包含 `--to`、`--task`、`--files`、`--success-criteria`、`--deadline`。
- ask：`--action clarify/verify`，clarify 需要 `--code-path` + `--question` + `--context`；verify 需要 `--doc-path` + `--changes-summary` + `--question`。
- send：`--to` + `--task`，建议带 `--corr` 并用 `--body` 传结构化 JSON（如 `doc_updated=true`）。
- done：`--to` + `--task`；verify 场景用 `--action verified`。
- fail：`--to` + `--task` + `--reason`（必要时加 `--blocked-by`）。

```bash
# review
team review \
  --to A,B,C,D \
  --task DOC-20240318-0001 \
  --owner MAIN \
  --file docs/design.md \
  --focus func,perf,ux \
  --review-deadline 3600 \
  --wait accepted

# assign
team assign \
  --to B \
  --task FEAT-001-B \
  --action implement \
  --files src/router.py \
  --success-criteria "Tests pass,Code reviewed" \
  --deadline 3600

# ask (clarify)
team ask \
  --to MAIN \
  --action clarify \
  --task FEAT-001-B \
  --code-path src/router.py#L145 \
  --question "retry backoff strategy?" \
  --context "Implementing ACK retry"

# send (answer)
team send \
  --to B \
  --task FEAT-001-B \
  --corr A-1-88 \
  --body '{"strategy":"exponential_backoff","base_delay_ms":100,"max_delay_ms":5000,"doc_updated":true}'

# done
team done --task FEAT-001-B --to MAIN

# fail
team fail --task FEAT-001-B --to MAIN --reason "Cannot proceed without clarification"
```

## 15. 配置

必填：
- workspace 路径
- terminal adapter（terminal / iterm2 / tmux）
- codex 命令路径（默认 "codex"）

可选：
- agent 数量（默认 4 个成员）
- 角色模型/配置 profile
- 默认 deadline 与 ttl_ms
- window_name_format（默认 "team-<session>-<role>"）

## 16. 故障与恢复

常见情况：
- Agent 窗口关闭：Router 保留 inbox；重连后继续消费。
- Router 崩溃：重启后回放日志，重建 inbox 与任务状态。
- 超时：标记 fail 并通知 MAIN。
- 格式错误：发送 NACK，reason=invalid_format。

恢复流程（Router 重启）：
1) 读取 meta/session.json；不存在则视为新会话并新建 session_id。
2) 读取 state/router.json 获取 last_epoch/last_seq；epoch=last_epoch+1。若缺失，扫描 logs/messages-*.jsonl 取最大 epoch/seq。
3) 重建 inbox：优先读取 inbox/<agent>.jsonl 事件流构造待处理列表；若缺失则回放 messages/acks 日志，保留 delivered 未 accepted 的 message id。
4) 重建任务状态：读取 state/tasks.json；若缺失则回放消息日志，按 action 更新任务状态（assign->open, done->done, fail->failed, verify->verify_pending, verified->verified）。
5) 恢复后继续投递：将待投递消息重新入队并按重试策略继续投递；超过 ttl/deadline 的任务标记 fail 并通知 MAIN。

## 17. 里程碑

M1：Router + storage + 消息 schema 校验。
M2：team CLI（review/assign/ask/send/done/fail）。
M3：Launcher（macOS Terminal 适配）。
M4：status/trace + 基础恢复能力。
M5：iTerm2 适配 + tmux 备用方案。

## 18. 未决问题

- 默认终端选 Terminal.app 还是 iTerm2？
- 是否支持超过 A/B/C/D 的更多角色？
- Router 用本地 WebSocket 还是文件队列？
- 不同角色是否使用不同模型配置？
