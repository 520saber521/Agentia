# AgentHub v2 产品规格（SPEC）

> 写作规约：每个 Feature 用 **User Story + Acceptance Criteria（EARS / Given-When-Then）** 描述；只描述"是什么"和"怎么算做完"，**不**约束实现细节（实现交给 `docs/ARCHITECTURE.md` 与 `ai-collab/skills/`）。
>
> 状态枚举（按 [`REBUILD_PLAN.md`](../REBUILD_PLAN.md) 5-Sprint 划分）：
>
> - `Done` —— 已合入主干、被自动化测试覆盖、已写进对应 record。
> - `In Progress` —— 已在当前 Sprint 中开始动手；至少有一个 PR / 分支正在改。
> - `Planned` —— 仅在路线图里，未动代码（包括 Sprint 已启动但 Feature 排在后面的情况）。
>
> 当前 Sprint 重心：**W2（Adapter + 群聊）**，详见 [`REBUILD_PLAN.md §5 Sprint W2`](../REBUILD_PLAN.md)。

---

## 课题要求覆盖矩阵

> 这份 SPEC 的目标是把课题原文转成可验收的产品契约。P1 必须在 W1-W5 内形成可演示闭环；P2 允许做轻量实现、演示入口或明确降级说明，但不能在文档里消失。

| 课题要求 | 优先级 | SPEC 覆盖 | 验收口径 |
| --- | --- | --- | --- |
| IM 聊天式交互：会话列表 / 新建 / 单聊 / 群聊 / 历史 | P1 | W1 + W2 | 用户能像 IM 一样创建多个会话、切换会话、单聊或群聊，并看到持续历史 |
| 多 Agent 接入：Claude Code + Codex/OpenCode | P1 | F-W2-2 + F-W3-4 | 至少 2 个真实 Adapter 通过同一协议流式回复、取消、错误降级 |
| `@mention` 与群聊 fan-out | P1 | F-W2-1 + F-W2-3 | 群聊中可精确 @ 一个或多个 Agent，并按独立消息气泡返回 |
| Orchestrator 主 Agent 协调 | P1 | F-W3-1 ~ F-W3-3 | 复杂任务能自动拆解、分派、追踪进度、汇总结果 |
| 上下文连续与 pin 长上下文 | P1 | F-W1-4 + F-W5-2 | 会话历史自动注入，用户可 pin 关键消息作为长期上下文 |
| 富媒体消息：代码 / Diff / Preview / 文件 / 任务卡 | P1 | F-W3-3 + F-W4-1 ~ F-W4-5 | 消息流不只显示文本，能内联展示和操作产物 |
| 产物预览与编辑：iframe / Monaco / 版本历史 | P1 | F-W4-2 ~ F-W4-5 | Agent 产物落为 artifact，可预览、编辑、生成新版本 |
| 用户自建 Agent | P1 | F-W5-1 | 用户能配置 system prompt、能力标签、模型 endpoint 并加入会话 |
| 部署发布 | P2 | F-W5-6 | 至少提供静态站点预览发布状态卡片；生产部署可作为降级演示 |
| 多端支持 | P2 | F-W5-7 | Web 为主力端；桌面/移动给出响应式或封装预留验收，不作为核心开发 |
| AI 协作沉淀 | P1 | 阶段 B + `ai-collab/records/*` | 每个 Sprint 至少 1 份 record，最终能说明 AI 协作如何改进工程质量 |

---

## 阶段 W1：骨架打通

### F-W1-1 — 单聊会话基础链路 · `Done`

**User Story**：作为用户，我想在浏览器里打开 AgentHub Web，看到一个默认会话，发一条文本消息后能立刻看到 Mock Agent 流式回复，并且刷新页面后历史不丢。

**Acceptance Criteria**

- GIVEN BFF 已启动且 SQLite 已初始化默认 seed
- WHEN 用户访问 `http://127.0.0.1:5173/`
- THEN 页面左侧应显示至少 1 条会话（`conv_demo`），中栏应能拉到历史消息列表，右侧 Header 应显示 `connected` 状态
- AND WHEN 用户在 Composer 输入文本并发送
- THEN 该消息应作为用户气泡立即出现，紧随其后出现一条 Agent 气泡，其内容以 `stream_chunk` 速度逐字增长
- AND 在 `message_done` 事件之后，该 Agent 气泡的内容应与服务端 DB 中持久化的内容完全一致
- AND 关闭浏览器再打开，上述历史消息仍可见

**反例（应失败）**

- 同一秒内连续发送 2 条消息：每条都应有独立的 Agent 回复，不应串包
- 服务端 5xx：UI 应在 Header 显示 `disconnected`，并自动指数退避重连

---

### F-W1-2 — 流式回复与取消 · `Done`

**User Story**：作为用户，我希望 Agent 在打字过程中我可以"按一下取消"立即让它停下，并且已经显示出来的内容会作为最终内容保留下来。

**Acceptance Criteria**

- GIVEN Agent 正在产出（`streamingMessageId` 非空）
- WHEN 用户点击 Composer 上的取消按钮
- THEN 客户端应发送 `{type:"cancel", message_id}` 到 BFF
- AND BFF 应在 50 ms 内停止 outbound 的 chunk 推送
- AND BFF 应推送 `message_cancelled`，其 `final_content.text` 必须等于截至取消时刻已推送的全部 delta 拼接 + 标记后缀（例如 `…[cancelled]`），不能丢字
- AND 该 Agent 气泡的最终文本应与 DB 中保存的 `content.text` 完全一致

---

### F-W1-3 — WebSocket 心跳与重连 · `Done`

**User Story**：作为用户，即使我的网络抖了一下、或者服务器重启了，我希望页面"自己回来"，并且不要每隔几秒就疯狂占用 CPU。

**Acceptance Criteria**

- GIVEN WebSocket 已建立
- WHEN 客户端每 20 s 触发一次心跳
- THEN 应发送 `{type:"ping"}`，并在 5 s 内收到 `pong`
- AND WHEN socket 异常关闭
- THEN 客户端应使用 **指数退避**（1s → 2s → 4s → 8s，上限 30 s + 随机抖动）触发重连
- AND 重连成功后应自动 `join` 上一次进入的 `conversation_id`，UI 上不应出现 message 错位

---

### F-W1-4 — 历史回放 · `Done`

**User Story**：作为用户，进入一个会话时我希望看到最近的几十条历史消息，而不是空白。

**Acceptance Criteria**

- GIVEN 客户端发送 `{type:"join", conversation_id, limit}`
- WHEN `limit ∈ [1, 500]` 且 `conversation_id` 存在
- THEN 服务端必须立即推送 1 条 `history` 事件，包含按 `created_at ASC` 排序的最近 `limit` 条消息
- AND 同一连接上后续不会再次重发同一批 history（除非客户端再次 `join`）
- AND WHEN `limit` 超出范围 OR `conversation_id` 不存在
- THEN 服务端必须推送 `{type:"error", code:"bad_request"|"not_found"}`，且不应中断连接

---

### F-W1-5 — 新建会话（REST + 前端） · `Done`

**User Story**：作为用户，我想能不止跟默认的 `conv_demo` 聊，而是按需开新会话。

**Acceptance Criteria**

- GIVEN BFF 已启动
- WHEN 客户端 `POST /api/conversations`，body 包含合法 `title` 与可选 `type ∈ {"single","group"}` 与可选 `agent_ids[]`
- THEN 服务端应返回 `201 Created`，body 含完整 `conversation` 对象（含 owner + 自动注入的 `user_demo` 成员 + 所有 `agent_ids` 成员）
- AND 前端 UI 上应立即出现这个新会话且被选中，无需手动点刷新
- AND WHEN `title` 为空 或 `type` 非法
- THEN 服务端应返回 `4xx`，前端模态应展示错误文案而不是静默失败

---

### F-W1-6 — 单一真源的事件 reducer · `Done`

> 这是工程规范，不是用户感知功能，但它会作为后续所有"消息 UI 状态"问题的回归基准。

**Acceptance Criteria**

- GIVEN 任何 `ServerEvent`
- WHEN 调用 `reduceEvent(state, evt)` 这一**纯函数**
- THEN 函数必须返回 `{ next, effects }`，其中 `next` 是新的状态切片、`effects` 是要由调用方执行的副作用清单（如 `refresh_conversations`）
- AND 函数体内禁止读取 `Date.now()` / 网络 / Zustand 之外的任何模块
- AND 仓库内必须存在覆盖以下事件的单元测试：`hello / history / message_created (本会话 vs 他会话 vs 重复 id) / agent_typing / stream_chunk (找到 vs 找不到) / message_done / message_cancelled / error (命中流式 vs 不命中) / 未知 type`，且测试断言"无副作用 case 应返回 state 引用相等"

---

## 阶段 W2：真 Adapter 接入与群聊 · `Planned`

> 范围对齐：[`REBUILD_PLAN.md §5 Sprint W2`](../REBUILD_PLAN.md)。
> Sprint W2 工程任务 W2-T1（拆 `server/main.py`）是结构性重构、不影响外部行为，**不写 SPEC**；其余 W2-T2 ~ W2-T6 对应下列 5 个 Feature。
> Orchestrator 相关行为已挪至 [W3](#阶段-w3agenthub-router--orchestrator--planned)。
>
> **Feature 间依赖**（绿色路径推荐顺序）：
>
> ```
> F-W2-1 fan-out ── 提供"群聊多 Agent 并发回复"基础设施
>      │
>      ├── F-W2-2 Claude Adapter  ── 让 fan-out 之一是"真 Agent"
>      │
>      ├── F-W2-3 @mention popover ─ 让用户能在 Composer 里精准触发 fan-out
>      │
>      ├── F-W2-4 三栏 + 成员侧栏 ── 让群聊成员可见，与 @mention 互为印证
>      │
>      └── F-W2-5 新建会话支持多 Agent ─ 让群聊会话能被真的"建出来"
> ```
>
> 推荐落地顺序：**F-W2-5 → F-W2-1 → F-W2-2 → F-W2-3 → F-W2-4**（先有"群聊能被建出"，再有"群聊能 fan-out"，再"接真 Agent"，再"打 @"，最后"成员侧栏"）。
>
> **W2-T1 拆 `server/main.py` 的硬约束**：本次决定（2026-05-21）跳过 W2-D1 直接做 F-W2-5；但 `server/main.py` 当前 449 行，F-W2-1 fan-out + F-W2-2 Adapter 落地后必将膨胀。**门禁**：F-W2-2 落地完成那一刻 `server/main.py` 若 > 350 行，**必须**先做 W2-T1 拆分，再启动 F-W2-3，否则违反 [`ai-collab/rules/frontend.mdc`](rules/frontend.mdc) R-F-8 的精神（虽然规则原写在前端，但单文件大小是项目级约定）。

### F-W2-1 — 多 Agent 群聊 fan-out · `Planned`

**User Story**：作为用户，我想在一个群聊会话里同时 `@` 多个 Agent，让他们都基于我这条消息各自给出回复，并按到达顺序串行/并发地出现在群聊里。

**Acceptance Criteria**

- GIVEN 当前会话 `type = "group"` 且 `conversation_member` 包含 ≥2 个 `member_type = "agent"` 的成员
- WHEN 用户发送 `{type:"send_message", content:{type:"text", text:"@<agent_a_name> @<agent_b_name> ..."}, mentions:[agent_a_id, agent_b_id]}`
- THEN BFF 必须**先**写一条 user 消息（含完整 `mentions` 数组），**再为每个被 @ 的 agent 各写一条**占位 agent 消息（共 `1 + N` 条 `message_created`）
- AND 必须为每个被 @ 的 agent **并发**创建一个 `in_flight` task；每个 task 独立持有其 `(agent_id, message_id)` 上下文
- AND 任何一个 agent 的 `stream_chunk` 必须携带其自己的 `message_id` 与 `sender_id`；前端按 `sender_id` 渲染到对应气泡
- AND 当且仅当**所有**被 @ 的 agent 都进入 `message_done` / `message_cancelled` / `error` 终态后，本轮 fan-out 才算结束；任一 agent 失败**不得**影响其他 agent 继续
- AND `cancel` 事件**只**取消指定 `message_id` 对应的那个 agent，其他兄弟消息不受影响

**反例（应失败）**

- `mentions` 数组为空但 `text` 中出现裸 `@xxx`：BFF 必须 `error code="bad_mentions"`，**不**触发任何 agent
- `mentions` 含不在当前会话成员表中的 `agent_id`：BFF 必须 `error code="not_member"`，可允许部分降级（其他合法 mention 仍正常 fan-out）
- 同一条消息 `mentions = [a, a, b]`：BFF 必须按 a/b 各发一次，**不**重复发给 a
- 群聊会话但 `mentions` 为空且 `text` 不含 `@`：按"默认 Orchestrator 路由"处理（W3 实现；W2 阶段允许返回 `error code="no_target"` 直到 W3 落地）

---

### F-W2-2 — Claude Adapter 接入 · `Planned`

**User Story**：作为用户，我想在群聊里 `@Claude` 让真正的 Claude 模型回答我，看到的体验和现在 Mock Agent 完全一致（流式打字 + 即按即停）。

**Acceptance Criteria**

- GIVEN `agent` 表中存在 1 行 `adapter_type = "claude_code"`、`config.api_key` 非空、`config.model` 为有效 Anthropic 模型名（如 `claude-sonnet-4.5-20250101`）
- WHEN 该 agent 被 `send_message` 触发
- THEN `ClaudeCodeAdapter.send()` 必须按 SSE 增量 yield `{type:"text", delta:...}` chunk，**W2 阶段硬验收只要"用户能看到逐字打字效果"**（操作上：两次 chunk 间隔 P95 ≤ 1 s）；`docs/ARCHITECTURE.md §10.3` 中"P95 ≤ 200 ms"作为软目标，留到 W4 端到端 demo 时实测
- AND `ClaudeCodeAdapter` 必须满足 [`ai-collab/rules/adapter.mdc`](rules/adapter.mdc) 五条契约：无状态 / 流式 / 取消是 `return` 不是 `raise` / 错误也 yield / 注册到 `ADAPTER_REGISTRY`
- AND 调用 `__init__` 时**不读** `os.environ`；`api_key` 与 `base_url` 必须从 `config` 参数注入
- AND `cancel` 事件触发到 yield 停止 ≤ 100 ms；已发送的 partial 内容必须写回 DB（沿用 W1 `_persist_final` 路径）
- AND Anthropic 上游返回 429 / 5xx / 网络超时（30 s）时必须 yield `{type:"error", code:"rate_limited"|"upstream_error"|"timeout", message:str}`，**禁止 raise**
- AND `capabilities()` 返回的列表必须只包含约定枚举：`text` / `tool_use` / `vision` / `code` / `web_search` / `file`
- AND 必须配套 `server/tests/test_adapter_claude.py` 覆盖 5 类场景：成功流式 / 取消 / 超时 / 上游 429 / api_key 缺失（与 `ai-collab/skills/new-adapter.md` Step 5 对齐）

**反例（应失败）**

- `config.api_key` 缺失：`build_adapter()` 必须 `error code="missing_api_key"`，**不**抛 `KeyError`
- 上游 SSE 中断（断开连接）：必须 yield `{type:"error", code:"stream_interrupted"}`
- 上游一次性返回完整 JSON 而不是流：Adapter 必须**自行**按 token / 标点切片再 yield（来自 R-A-2）

---

### F-W2-3 — `@mention` 提示器 · `Planned`

**User Story**：作为用户，我在 Composer 里输入 `@` 时应立即弹出一个候选列表，告诉我这个群里有哪些 Agent 可以 @，我用键盘上下选就能精准带上他们。

**Acceptance Criteria**

- GIVEN Composer 已获焦且当前会话 `type = "group"`
- WHEN 用户在输入框内输入 `@` 字符
- THEN 必须在光标下方弹出 `MentionPopover`，列出当前会话所有 `member_type = "agent"` 的成员（按 `name` 字母升序），每行显示头像 + 名字 + capabilities 前 3 个标签
- AND 弹层支持 `ArrowUp` / `ArrowDown` 切换高亮、`Enter` 选中、`Esc` 关闭、`Tab` 选中
- AND 选中后，Composer 文本中 `@` 触发位置后的字符被替换为 `@<agent_name> `（**含尾随空格**），且 store 的 `mentions` 数组追加对应 `agent_id`（按集合去重，保持插入顺序）
- AND 用户在弹层打开期间继续输入字符：按已输入的前缀（不区分大小写）过滤候选；候选为空时弹层自动关闭、不写 `mentions`
- AND 删除一个已 @ 的 token（按退格删完 `@<name>`）时，必须**同步**从 `mentions` 移除对应 `agent_id`
- AND `mentions` 的最终值在 `send_message` 触发时**必须**等于 Composer 文本里实际 `@<name>` 的去重后 `agent_id` 集合

**反例（应失败）**

- 单聊场景（`type = "single"`）：输入 `@` **不**弹层（单聊语义里 `@` 是普通字符）
- 群聊但当前会话仅 1 个 Agent 成员：仍弹层（用户可能想精确指定唯一目标，且 W3 起 Orchestrator 是默认 fallback）
- 用户手动键入了 `@xxx` 但 xxx 不在成员表：发送时**不**写入 `mentions`，UI 把这段文本当普通字符渲染（不阻塞发送）

---

### F-W2-4 — 三栏布局 + 成员侧栏 · `Planned`

**User Story**：作为用户，进入群聊会话时我希望右侧能看到本群所有 Agent 的列表（头像、能力标签），让我清楚"这个群里有谁可以帮我做什么"。

**Acceptance Criteria**

- GIVEN 当前会话 `type = "group"` 且 viewport 宽度 ≥ 1024 px
- WHEN App 渲染
- THEN 主区必须为三栏 grid：会话列表（左 260 px）+ 消息流 + 成员侧栏（右 320 px）
- AND 成员侧栏每行渲染：头像 + 名字 + 在线状态（W2 阶段允许全部显示 "online"，真在线 W3 起复用 Router presence）+ capabilities 标签
- AND 鼠标悬停头像 ≥ 200 ms 后弹出名片浮层（W5 完整实现；W2 阶段只要 hover 改变光标即可）
- AND GIVEN `type = "single"` THEN 必须隐藏右栏，回到二栏 grid（与 W1 行为一致）
- AND GIVEN viewport 宽度 < 1024 px THEN 右栏必须折叠为可点击展开的浮层；折叠不得阻塞中栏 60 fps 滚动

**反例（应失败）**

- 群聊会话但 `conversation_member` 异常无数据：右栏显示"暂无成员，请刷新"，**不**报错也**不**让 React 崩溃
- 单聊会话但用户手动把 viewport 拉到 < 480 px：左栏会话列表必须折叠为抽屉式，避免压扁中栏（与 R-F-8 保持）

---

### F-W2-5 — 新建会话支持多 Agent · `Done`

> 落地于 2026-05-21（W2-D1）。详见 [`ai-collab/records/20260521-W2-D1.md`](records/20260521-W2-D1.md)。

**User Story**：作为用户，在"新建会话"弹窗里我想能勾选多个 Agent 组成一个群聊，不再被局限到默认的 1v1 Mock。

**Acceptance Criteria**

- GIVEN `NewConversationDialog` 已打开
- WHEN 用户在 `type` 选择器里选 `"group"`
- THEN 模态必须显示一个 Agent 多选列表，数据源为 `GET /api/agents` 的返回，按 `name` 升序，每行显示 checkbox + 头像 + 名字 + capabilities 标签
- AND 用户必须至少勾选 1 个 Agent 才允许提交；未勾选时提交按钮 disabled 并显示文案"群聊需要至少 1 个 Agent"
- AND 提交触发 `POST /api/conversations`，body 必须含 `{title, type:"group", agent_ids:[...]}`；服务端必须把每个 `agent_id` 写入 `conversation_member`（`member_type="agent"`）
- AND 创建成功后前端**必须**自动 `selectConversation(new_id)` 并 `join`，与 W1 F-W1-5 行为一致
- AND GIVEN `type = "single"` THEN Agent 选择器降级为单选（与 W1 行为一致）

**反例（应失败）**

- `type = "group"` 但 `agent_ids = []`：服务端必须 `422`，前端显示具体错误文案而非静默
- `agent_ids` 含不存在的 `agent_id`：服务端必须 `422 code="unknown_agent"`，且**不**创建会话（事务回滚）
- 同一 `agent_id` 在 `agent_ids` 里重复：服务端必须按集合去重后写入，不报错

---

## 阶段 W3：AgentHub Router + Orchestrator · `Planned`

> 范围对齐：[`REBUILD_PLAN.md §5 Sprint W3`](../REBUILD_PLAN.md)。

### F-W3-1 — Router 接入与 trace 链路 · `Planned`

**User Story**：作为用户，我希望群聊里的多 Agent 调度不是前端硬凑出来的，而是有一条可追踪的消息链路；当某个 Agent 回复异常时，我能看到它经过了哪些节点。

**Acceptance Criteria**

- GIVEN BFF 与 Router 服务均已启动
- WHEN BFF 启动完成
- THEN BFF 应向 Router 注册自身节点，注册信息至少包含 `node_id`、`role = "bff"`、`capabilities`
- AND WHEN 群聊消息包含合法 `mentions`
- THEN BFF 应把每个目标 Agent 的投递请求写入 Router，并保留同一个 `trace_id`
- AND Router 返回 ACK 后，BFF 才允许把对应 agent 占位消息标记为 `running`
- AND WHEN 用户请求 `GET /api/trace/{message_id}`
- THEN 服务端应返回从用户消息、Router 投递、Adapter 调用到最终回复的有序节点列表
- AND trace 查询失败时 UI 应显示"暂无 trace"，不得影响聊天主流程

**反例（应失败）**

- Router 不可用：群聊消息必须降级为 `error code="router_unavailable"`，不能假装发送成功
- trace 节点乱序：前端时序图必须按 `created_at ASC` 或 `seq ASC` 渲染，不得按对象 key 顺序渲染

---

### F-W3-2 — Orchestrator 自动拆解与分派 · `Planned`

**User Story**：作为用户，我希望在群聊里直接描述复杂任务，由 `@Orchestrator` 判断需要哪些 Agent、拆成子任务，并让它们像群聊成员一样协作完成。

**Acceptance Criteria**

- GIVEN 当前会话 `type = "group"` 且成员中存在 `agent_orchestrator`
- WHEN 用户发送 `@Orchestrator <复杂任务描述>`
- THEN 3 s 内必须插入一条 `task_status` 消息卡片，初始状态为 `planning`
- AND Orchestrator 必须基于会话历史、pin 消息和当前请求生成至少 2 个 `subtask`（简单任务允许 1 个，但必须写明 reason）
- AND 每个 `subtask` 必须包含 `title`、`assignee_agent_id`、`status`、`input_summary`、`depends_on[]`
- AND 对无依赖或依赖已完成的子任务，Orchestrator 必须并发 dispatch 到对应 Agent
- AND 每个子 Agent 的回复必须作为普通 Agent 消息进入聊天流，不能只藏在任务卡片里
- AND 所有必需子任务进入 `done` / `failed` 后，Orchestrator 必须发送一条汇总消息，说明已完成内容、失败项和下一步建议

**反例（应失败）**

- 没有合适 Agent：Orchestrator 必须回复可理解的降级说明，并把任务卡片标记为 `blocked`
- 子 Agent 失败：最多重试 1 次；仍失败时标记该子任务 `failed`，不得阻塞其他无依赖子任务
- 两个 Agent 同时修改同一 artifact：Orchestrator 必须标记 `conflict`，要求用户选择版本或触发合并任务

---

### F-W3-3 — 任务状态卡片与实时更新 · `Planned`

**User Story**：作为用户，我希望复杂任务不是黑盒等待，而是能在聊天流和右侧任务面板里实时看到每个子任务的状态。

**Acceptance Criteria**

- GIVEN Orchestrator 创建了 `task` 与 `subtask`
- WHEN 任意子任务状态变化
- THEN 服务端必须推送 `task_update` WS 事件，包含 `task_id`、`subtask_id`、`status`、`progress`、`message_id?`
- AND 状态枚举只允许 `planning` / `pending` / `running` / `done` / `failed` / `blocked` / `conflict`
- AND `TaskStatusCard` 必须在消息流中更新总进度、子任务列表和失败原因
- AND `TaskPanel` 必须显示当前会话所有任务，按最近更新时间倒序
- AND 点击子任务应滚动到对应 Agent 消息；若消息不存在，应显示"尚未产生消息"

---

### F-W3-4 — 第二个真实 Adapter 接入 · `Planned`

**User Story**：作为用户，我希望平台不只接入 Claude，还能接入 Codex 或 OpenCode，证明 AgentHub 的统一适配器层真的屏蔽了平台差异。

**Acceptance Criteria**

- GIVEN `agent` 表中存在 `adapter_type = "codex"` 或 `adapter_type = "opencode"` 的 Agent
- WHEN 用户在单聊或群聊中触发该 Agent
- THEN 该 Adapter 必须按统一 `Adapter.send(context)` 协议流式 yield 文本或 artifact chunk
- AND 必须支持取消、超时、上游错误、缺失配置四类降级
- AND `capabilities()` 必须返回统一能力枚举，至少包含 `text`，可选 `code` / `file` / `tool_use`
- AND 同一条用户消息同时触发 Claude 与第二 Adapter 时，二者必须生成独立 message_id，不得互相覆盖
- AND 必须配套单测覆盖：成功流式、取消、超时、上游错误、配置缺失

---

### F-W3-5 — 协议字段向后兼容扩展 · `Planned`

**User Story**：作为开发者，我希望 Router / Protocol 支持 AgentHub v2 的会话、卡片和产物字段，同时不破坏 v1 已有消息。

**Acceptance Criteria**

- GIVEN 现有 `src/protocol/*` fixtures
- WHEN 增加 `conversation_id`、`card_type`、`artifact_id`、`trace_id` 等可选字段
- THEN 旧 fixtures 必须继续 validate 通过
- AND 新字段缺失时 builder 必须给出 `None` 或省略字段，不得生成非法空字符串
- AND 新增枚举必须与前后端 `content.type` 枚举保持同名
- AND 任意未知字段必须被 validator 明确拒绝或放入 `metadata`，策略只能选一种并写入测试

---

## 阶段 W4：富媒体与产物 · `Planned`

> 范围对齐：[`REBUILD_PLAN.md §5 Sprint W4`](../REBUILD_PLAN.md)。

### F-W4-1 — 消息内容 schema 严格化 · `Planned`

**User Story**：作为用户，我希望 Agent 回复能稳定展示文本、代码、Diff、预览、文件和任务状态，而不是前端靠猜测渲染。

**Acceptance Criteria**

- GIVEN 客户端或 Adapter 写入任意消息 `content`
- WHEN `content.type` 为 `text` / `code` / `diff` / `preview` / `file` / `task_status` / `deploy_status`
- THEN 服务端必须按对应 schema 校验必填字段，并持久化规范化后的 JSON
- AND 非法 `content.type` 或缺失必填字段必须返回 `422 code="invalid_content"`
- AND 前端 `ContentRenderer` 必须对所有合法类型有显式分支；未知类型只能渲染错误占位，不得白屏
- AND reducer 单测必须覆盖每种 `content.type` 的 `message_created` 与 `message_done`

---

### F-W4-2 — Artifact 一等对象与版本链 · `Planned`

**User Story**：作为用户，我希望 Agent 生成的网页、代码、文档等产物可以被预览、编辑、回溯，而不是只作为一段聊天文本丢在历史里。

**Acceptance Criteria**

- GIVEN Adapter 产出可预览或可下载内容
- WHEN BFF 收到 `artifact` chunk
- THEN 必须创建 `artifact` 记录，字段至少包含 `id`、`conversation_id`、`kind`、`title`、`mime_type`、`storage_path`、`parent_id?`
- AND 消息 `content` 只保存 `artifact_id` 与预览元数据，不直接塞入大文件正文
- AND `GET /api/artifacts/{id}` 必须返回 artifact 元数据与可访问 URL
- AND `GET /api/artifacts/{id}/history` 必须沿 `parent_id` 返回版本链，按创建时间升序
- AND 删除或归档会话时，artifact 必须保持可读，除非用户显式删除产物

---

### F-W4-3 — 内联代码、文件与网页预览卡片 · `Planned`

**User Story**：作为用户，我希望在聊天流里直接查看代码块、下载文件、展开网页预览，而不是离开当前对话。

**Acceptance Criteria**

- GIVEN 消息 `content.type = "code"`
- WHEN 消息渲染
- THEN `CodeBlock` 必须显示语言、代码内容、复制按钮，并保证长代码可滚动不撑破消息流
- AND GIVEN `content.type = "file"`
- THEN `FileCard` 必须显示文件名、大小、类型、下载入口
- AND GIVEN `content.type = "preview"`
- THEN `PreviewCard` 必须显示 iframe 预览入口、artifact 标题和打开全屏按钮
- AND iframe 加载失败时必须显示失败状态和重试按钮，不得影响其他消息渲染

---

### F-W4-4 — Monaco 编辑与对话内保存新版本 · `Planned`

**User Story**：作为用户，我希望点击产物后能全屏编辑代码，保存后自动形成新版本，并把结果回插到聊天里。

**Acceptance Criteria**

- GIVEN 用户打开任意 `code` 或 `preview` artifact
- WHEN 点击"编辑"
- THEN 应打开全屏 `ArtifactEditor`，加载 artifact 当前版本内容
- AND 用户保存后，服务端必须创建一个新的 artifact 版本，其 `parent_id` 指向旧版本
- AND 保存成功必须向当前会话插入一条 `diff` 或 `preview` 消息，说明从哪个版本变更到哪个版本
- AND 编辑器关闭再打开时必须加载最新版本
- AND 保存失败时编辑器内容不得丢失，UI 必须显示可重试错误

---

### F-W4-5 — Diff 视图与一键应用 · `Planned`

**User Story**：作为用户，我希望 Agent 给出的修改建议能以 Diff 形式展示，并且可以一键应用到目标产物。

**Acceptance Criteria**

- GIVEN 消息 `content.type = "diff"` 且包含 `base_artifact_id`
- WHEN `DiffCard` 渲染
- THEN 必须展示 before / after 差异、目标文件名、变更摘要和"应用"按钮
- AND WHEN 用户点击"应用"
- THEN BFF 必须基于 `base_artifact_id` 创建新 artifact 版本，并把 diff 结果写入新版本
- AND 应用成功后必须推送 `artifact_ready`，并在聊天流插入新的 `preview` 或 `code` 卡片
- AND 对已过期 base 版本应用 diff 时，必须返回 `409 code="artifact_conflict"`，提示用户先选择版本或重新生成

---

### F-W4-6 — 文件上传与附件上下文 · `Planned`

**User Story**：作为用户，我希望能把文件拖进会话，让 Agent 基于附件理解任务，并在聊天流里看到附件卡片。

**Acceptance Criteria**

- GIVEN 用户在 Composer 上传文件
- WHEN `POST /api/upload` 成功
- THEN 服务端必须创建 `artifact kind="file"`，并返回 `artifact_id`
- AND Composer 必须把该 `artifact_id` 附加到下一条用户消息的 `attachments[]`
- AND Agent 调用上下文必须包含附件元数据；文本类附件允许注入摘要，二进制附件只注入文件名、类型、URL
- AND 上传失败、文件过大、类型不支持时必须显示明确错误，不得发送半成品消息

---

## 阶段 W5：用户自建 Agent + 打磨 · `Planned`

> 范围对齐：[`REBUILD_PLAN.md §5 Sprint W5`](../REBUILD_PLAN.md)。

### F-W5-1 — 用户自建 Agent · `Planned`

**User Story**：作为用户，我希望通过对话式或表单式配置创建自己的 Agent，指定 System Prompt、能力标签和模型 endpoint，然后把它加入任意会话。

**Acceptance Criteria**

- GIVEN 用户打开 Agent 管理页
- WHEN 创建 Agent 并填写 `name`、`system_prompt`、`adapter_type = "custom"`、`model`、`endpoint`、`capabilities`
- THEN `POST /api/agents` 必须创建一条用户自建 Agent，并返回可用于会话选择器的完整对象
- AND 新建 Agent 必须立即出现在新建会话 Agent 列表和群聊成员邀请入口
- AND `CustomAgentAdapter` 必须兼容 OpenAI 风格 streaming endpoint
- AND 用户自建 Agent 被触发时，Adapter 调用上下文必须包含该 Agent 的 `system_prompt`
- AND endpoint / key 缺失时必须返回可理解错误，不能泄漏密钥明文

---

### F-W5-2 — Pin 消息与长期上下文 · `Planned`

**User Story**：作为用户，我希望能把关键需求、约束或决策 pin 起来，让后续 Agent 回复始终记住这些上下文。

**Acceptance Criteria**

- GIVEN 任意消息气泡已渲染
- WHEN 用户执行 pin / unpin 操作
- THEN 服务端必须更新该消息的 `pinned` 状态，并推送 `message_updated`
- AND UI 必须在消息气泡和会话侧栏显示 pin 状态
- AND 调用任意 Adapter 时，BFF 必须把当前会话 pinned 消息按时间顺序注入上下文头部
- AND pinned 上下文超过 token 预算时，必须按"最新 pinned 优先 + 显式提示被截断"策略降级
- AND unpin 后下一次 Agent 调用不得继续注入该消息

---

### F-W5-3 — Trace 时序图 · `Planned`

**User Story**：作为用户或答辩评审，我希望能看到一次多 Agent 协作的完整链路，证明平台不是单个模型在伪装群聊。

**Acceptance Criteria**

- GIVEN 任意 Agent 消息存在 `trace_id`
- WHEN 用户点击"查看 trace"
- THEN `TraceViewer` 必须以时序图展示用户消息、Router、Orchestrator、各 Adapter、artifact 写入等节点
- AND 每个节点必须显示状态、耗时、失败原因（如有）
- AND trace 数据为空时必须显示空状态，不得报错
- AND 时序图必须支持复制 trace JSON，便于写入 `ai-collab/records/*`

---

### F-W5-4 — 圈选改对话式编辑 · `Planned`

**User Story**：作为用户，我希望在 Monaco 里选中一段代码后，直接回到聊天中描述修改需求，让 Agent 基于选区做局部修改。

**Acceptance Criteria**

- GIVEN `ArtifactEditor` 已打开且用户选中一段文本
- WHEN 用户点击"在聊天中修改"
- THEN Composer 必须自动插入一条引用上下文，包含 `artifact_id`、版本号、文件路径、选区起止行
- AND 用户发送修改请求后，目标 Agent 必须收到选区内容与周边上下文
- AND Agent 返回的修改应优先生成 `diff` 卡片，而不是覆盖整个 artifact
- AND 选区不存在或 artifact 已过期时，UI 必须提示用户重新选择

---

### F-W5-5 — 会话搜索、置顶与归档 · `Planned`

**User Story**：作为用户，我希望像 IM 一样管理多个并行任务会话，能搜索、置顶和归档，避免项目多了以后找不到上下文。

**Acceptance Criteria**

- GIVEN 左侧会话列表已有多个会话
- WHEN 用户输入搜索关键词
- THEN 列表必须按标题、成员名、最近消息摘要过滤
- AND 置顶会话必须排在非置顶会话之前，同组内按最近活跃时间倒序
- AND 归档会话默认隐藏，但可通过筛选器查看
- AND 已归档会话收到新消息时必须自动取消归档或显示未读提醒，策略必须固定并写入测试

---

### F-W5-6 — 部署状态卡片（P2） · `Planned`

**User Story**：作为用户，我希望在聊天里发送"部署"后，至少能得到一个可点击的预览 URL 和清晰的部署状态，而不是只拿到源码。

**Acceptance Criteria**

- GIVEN 当前会话存在可部署的 `preview` artifact
- WHEN 用户发送"部署这个网页"或点击部署按钮
- THEN BFF 必须创建 `deploy_status` 消息卡片，状态初始为 `pending`
- AND 部署流程必须至少支持本地静态预览 URL；若接入 Netlify 或其他平台，则必须返回外部 preview URL
- AND 状态变化必须按 `pending` → `building` → `success` / `failed` 推送更新
- AND 部署失败必须展示失败原因和重试入口
- AND 若本期不接真实云部署，最终答辩文档必须明确标注为 P2 降级实现

---

### F-W5-7 — 多端支持边界（P2） · `Planned`

**User Story**：作为评审，我希望看到平台对 Web、桌面、移动端定位有清晰边界，即使本期主力只实现 Web，也不是完全忽略多端需求。

**Acceptance Criteria**

- GIVEN Web 端在桌面宽屏、窄屏和移动宽度打开
- WHEN viewport 分别为 1440 px、1024 px、390 px
- THEN 主聊天流程必须可用：查看会话、发送消息、查看预览卡片
- AND 桌面端能力（本地文件访问、Agent 进程管理）必须在 README 或架构文档中列为后续封装点
- AND 移动端必须至少支持只读查看、轻量回复、预览卡片打开；Monaco 编辑可明确标注为桌面优先

---

### F-W5-8 — 多 Agent 投票模式（创新点 · 可选） · `Planned`

**User Story**：作为用户，我希望在方案选择时让多个 Agent 各自给出判断，再由我或 Orchestrator 做最终决策。

**Acceptance Criteria**

- GIVEN 当前会话 `type = "group"` 且存在至少 2 个 Agent
- WHEN 用户发送 `/vote <question>`
- THEN BFF 必须触发所有在场 Agent 各自回复一次意见
- AND Orchestrator 必须在所有回复结束后生成投票汇总，包含每个 Agent 的结论与理由
- AND 任一 Agent 失败不得阻塞其他 Agent 投票

---

## 阶段 B（Buffer）：答辩与交付物 · `Planned`

> 范围对齐：[`REBUILD_PLAN.md §5 Sprint B`](../REBUILD_PLAN.md)。

### F-B-1 — 端到端 Demo 脚本与视频 · `Planned`

**Acceptance Criteria**

- Demo 必须覆盖：新建群聊、@ 多 Agent、Orchestrator 拆任务、任务卡片、产物预览、Monaco 编辑、Diff 应用、自建 Agent
- 3 分钟视频必须包含至少一次真实 Adapter 回复，不得全程 Mock
- 视频脚本必须写入 `ai-collab/records/demo-script.md`

---

### F-B-2 — 答辩材料 · `Planned`

**Acceptance Criteria**

- Deck 必须包含：课题理解、产品形态、架构图、核心链路、创新点、风险降级、评分项自评
- 每个 P1 课题要求必须在 deck 中有截图或视频证据
- P2 的部署、多端必须明确说明完成程度和降级边界

---

### F-B-3 — 文档定稿 · `Planned`

**Acceptance Criteria**

- `README.md` 必须给出一键启动、Demo 路径、功能清单、已知限制
- `docs/ARCHITECTURE.md` 必须与本 SPEC 的 Feature 编号互相引用
- `ai-collab/SPEC.md` 中所有 `Planned` 在结项前必须改为 `Done`、`Deferred` 或 `Dropped`，不能留下模糊状态

---

### F-B-4 — 一键验收 · `Planned`

**Acceptance Criteria**

- `smoke_all.py` 必须串起 W1-W5 主流程，并输出逐项 PASS / FAIL
- smoke 至少覆盖：单聊、群聊 fan-out、真实 Adapter、Orchestrator、artifact、pin、自建 Agent
- 任一 P1 smoke 失败时最终交付不得标记为完成

---

### F-B-5 — AI 协作沉淀归档 · `Planned`

**Acceptance Criteria**

- 每个 Sprint 必须有一份 `ai-collab/records/YYYYMMDD-Wx.md`
- 归档必须包含：当周目标、关键决策、踩坑与规则沉淀、测试结果、下周风险
- 至少 2 条工程规则或 Skill 更新必须能追溯到真实开发问题
