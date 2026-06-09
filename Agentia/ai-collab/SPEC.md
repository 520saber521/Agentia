# AgentHub AI 协作与产品规格

> 本规格描述 AgentHub 当前项目要求、AI 协作目标和可验收交付标准。实现细节放在 `docs/ARCHITECTURE.md`、`server/README.md`、`web/src/types.ts` 和 `ai-collab/skills/` 中维护。

## 1. 项目目标

AgentHub 要提供一个 IM 风格的多 Agent 协作工作台，让用户能够创建单聊或群聊、选择多个 Agent、通过 `@mention` 指派任务，并在同一对话中查看文本、代码、Diff、网页预览、文件、任务进度、部署状态和 Trace。

AI 协作交付的目标是让项目具备可复用、可审计、可继续扩展的工程过程：

- 用 `SPEC.md` 固化“做什么”和“怎样算完成”。
- 用 `skills/` 固化“某类任务怎么做”。
- 用 `rules/` 固化“哪些做法禁止出现”。
- 用 `records/` 保留真实协作痕迹和决策来源。

## 2. 状态与优先级

### 状态枚举

| 状态 | 含义 |
| --- | --- |
| `Done` | 已实现、已接入主流程，至少有测试或可复现手动验收 |
| `In Progress` | 当前正在实现或仍需修正测试、边界、文档 |
| `Planned` | 已确认要做，尚未开始 |
| `Deferred` | 有价值但本轮交付降级或延后 |
| `Dropped` | 明确不做，且有原因 |

### 优先级

| 优先级 | 含义 |
| --- | --- |
| P1 | 核心演示与评分闭环必须覆盖 |
| P2 | 可降级，但必须说明边界 |
| P3 | 加分或后续演进，不阻塞当前交付 |

## 3. 当前验收矩阵

| 能力 | 优先级 | 状态 | 验收口径 |
| --- | --- | --- | --- |
| IM 会话基础链路 | P1 | Done | 可创建、切换、搜索、置顶、归档单聊和群聊，会话历史可回放 |
| WebSocket 流式消息 | P1 | Done | 支持 `join`、`send_message`、`cancel`、`ping/pong`、断线重连和历史同步 |
| 多 Agent Adapter | P1 | Done | Mock、Claude Code、Claude Agent SDK、Codex 通过统一接口流式输出 |
| 群聊 fan-out | P1 | Done | 群聊中按 `mentions` 或会话成员触发多个 Agent，消息互不覆盖 |
| `@mention` 提示 | P1 | Done | Composer 中可选择 Agent，发送时携带去重后的 `mentions` |
| Orchestrator 协调 | P1 | Done | 能识别复杂任务、拆解子任务、推送 `task_update`、汇总结果 |
| 富媒体消息 | P1 | Done | 支持 `text`、`code`、`diff`、`preview`、`file`、`task_status`、`deploy_status` |
| Artifact 管理 | P1 | Done | Artifact 可落盘、预览、查看版本、保存新版本、应用 Diff |
| 自定义 Agent | P1 | Done | 支持创建、更新、删除、配置 endpoint 和 system prompt |
| Pin 长上下文 | P1 | Done | Pinned 消息会注入后续 Adapter 上下文，支持上下文统计 |
| Trace 与执行记录 | P1 | Done | 能查询 Agent 执行记录和 trace 事件，用于答辩追溯 |
| 部署状态卡片 | P2 | In Progress | 已有卡片和 API 基础，完整云端发布可降级为本地预览 |
| 桌面与移动端 | P2 | Deferred | 当前主力端为 Web，移动端保证核心只读与轻量回复边界 |
| 一键 Smoke | P1 | In Progress | 后端 pytest 与前端 vitest 是最低门槛，端到端脚本需继续收敛 |

## 4. 产品规格

### F-1 会话与历史

**用户故事**：作为用户，我希望像使用 IM 一样管理多个会话，随时切换上下文并看到历史消息。

**验收标准**

- GIVEN 后端服务和数据库已启动，WHEN 用户打开 Web 首页，THEN 默认会话列表和当前会话消息应可见。
- WHEN 用户创建单聊或群聊，THEN 新会话应立即出现在列表中并被选中。
- WHEN 用户搜索、置顶或归档会话，THEN 列表排序和过滤结果必须稳定可预测。
- WHEN 用户刷新浏览器或重新加入会话，THEN 服务端必须推送按时间升序排列的历史消息。

### F-2 WebSocket 消息流

**用户故事**：作为用户，我希望 Agent 回复能逐字流式出现，并且能随时取消。

**验收标准**

- `send_message` 必须先创建用户消息，再创建 Agent 占位消息。
- `stream_chunk` 必须携带 `message_id`，前端只能更新对应气泡。
- `message_done` 后，DB 中持久化内容必须等于前端最终展示内容。
- `cancel` 只取消指定 `message_id`，不能影响其他 Agent 的流。
- 预期错误必须转成 `{type:"error", code, message}`，不能让 WS writer 崩溃。

### F-3 多 Agent 与 Adapter

**用户故事**：作为用户，我希望不同 Agent 以一致体验参与协作，而不是每个模型一套交互。

**验收标准**

- 所有 Adapter 必须实现统一 `send()` 与 `capabilities()`。
- Adapter 不得直接读取数据库或 WebSocket。
- API key、endpoint、model 必须由 BFF 注入，不得在 Adapter 内硬读环境变量。
- 上游错误、超时、限流必须 yield 错误 chunk，而不是直接 raise。
- 新 Adapter 必须按 `skills/new-adapter.md` 完成 5 类测试。

### F-4 群聊 fan-out 与 `@mention`

**用户故事**：作为用户，我希望在群聊中精确指定一个或多个 Agent 并行处理同一任务。

**验收标准**

- `mentions` 中的 Agent 必须属于当前会话成员。
- 重复 mention 必须去重，保持首次出现顺序。
- 每个目标 Agent 必须拥有独立 `message_id`、任务上下文和终止状态。
- 单个 Agent 失败不能阻塞其他 Agent 完成。
- 前端 `mentions` 必须与 Composer 文本中的有效 `@<name>` 保持一致。

### F-5 Orchestrator 与任务状态

**用户故事**：作为用户，我希望复杂任务能被拆解、分派、跟踪进度并最终汇总。

**验收标准**

- Orchestrator 必须能把复杂任务拆成子任务，并分配给具备相应能力的 Agent。
- 状态枚举仅允许 `planning`、`pending`、`running`、`done`、`failed`、`blocked`、`conflict`。
- 服务端状态变化必须推送 `task_update`。
- 前端必须在消息流或侧栏中展示任务进度、失败原因和对应消息入口。

### F-6 富媒体消息与 Artifact

**用户故事**：作为用户，我希望 Agent 输出不只是文本，而是可查看、可编辑、可追溯的工作产物。

**验收标准**

- `content.type` 必须经过服务端 schema 校验。
- 前端 `ContentRenderer` 必须显式处理所有合法类型，未知类型不能导致白屏。
- 大内容必须落为 Artifact，消息中只保留 `artifact_id` 与预览元数据。
- Artifact 必须支持元数据查询、内容读取、版本历史和新版本保存。
- Diff 应用必须基于明确的 base artifact，冲突时返回稳定错误码。

### F-7 自定义 Agent 与上下文

**用户故事**：作为用户，我希望能创建自己的 Agent，并让它在会话中带着配置和长期上下文工作。

**验收标准**

- 自定义 Agent 至少包含 `name`、`adapter_type`、`model`、`endpoint`、`system_prompt`、`capabilities`。
- 密钥不得明文暴露到前端响应或日志。
- Pinned 消息必须按时间顺序注入 Adapter 上下文。
- 上下文超过预算时，必须采用确定性裁剪策略并向用户暴露降级信息。

### F-8 Trace、执行记录与答辩证据

**用户故事**：作为开发者或评审，我希望能追溯一次多 Agent 协作的完整链路。

**验收标准**

- Agent 调用、任务拆解、Artifact 写入、错误和取消都应留下 trace 或 execution 记录。
- Trace 查询为空时应返回空状态，不得报错。
- 答辩材料必须能引用至少一条真实 trace 或 record 证明协作链路。

## 5. AI 协作规格

### C-1 需求进入开发前

- 必须先确认需求映射到现有 Feature，或新增 Feature 编号。
- 必须写清楚验收标准，避免只写“优化体验”“完善能力”。
- 涉及 P2/P3 降级时，必须写明不做什么、为什么不做、如何演示替代方案。

### C-2 AI 执行开发时

- AI 必须先读相关代码和规则，再改文件。
- AI 不得重构无关模块，不得覆盖用户已有改动。
- AI 必须优先沿用现有服务、类型、组件和测试模式。
- AI 必须把失败命令、未运行测试和剩余风险如实反馈。

### C-3 协作记录沉淀

- 每个 Sprint 至少一份 `records/YYYYMMDD-Wx.md`。
- 关键记录必须包含：目标、上下文、AI 建议、人类决策、执行结果、踩坑、规则或 Skill 更新。
- 从记录中提炼出来的长期规则，应迁移到 `rules/`；可复用步骤应迁移到 `skills/`。

## 6. 测试与验收命令

后端：

```powershell
cd D:\桌面\Agentia_v7\Agentia
python -m pytest -c server\pyproject.toml server\tests
```

前端：

```powershell
cd D:\桌面\Agentia_v7\Agentia\web
npm.cmd test
```

手动 smoke 最低链路：

1. 启动后端和前端。
2. 创建群聊，选择 Orchestrator、Frontend、Backend、Test Agent。
3. 发送带 `@Orchestrator` 的复杂任务。
4. 观察任务拆解、多个 Agent 回复、Artifact 预览、Diff 或版本历史。
5. 测试取消、刷新历史、Pin 消息和 Trace 查询。

## 7. 协作资产覆盖度

| Feature | Skill 覆盖 | Rule 覆盖 | 记录覆盖 |
| --- | --- | --- | --- |
| F-1 会话与历史 | — | backend, frontend | W1 |
| F-2 WebSocket 消息流 | ws-flow-debug | backend, frontend | W1 |
| F-3 多 Agent Adapter | new-adapter | adapter, backend | W1 |
| F-4 群聊 fan-out | — | backend, frontend | W2-D1 |
| F-5 Orchestrator | — | backend | — |
| F-6 富媒体消息 | new-message-type | backend, frontend | W4-Diff |
| F-7 自定义 Agent | — | backend, frontend | — |
| F-8 Trace 执行记录 | — | backend, collaboration | — |

**覆盖率缺口**：F-5 Orchestrator 和 F-7 自定义 Agent 尚无专属 Skill，应在下次相关开发时补齐。

## 8. 交付前检查

- [ ] `SPEC.md` 状态与当前实现一致。
- [ ] 新增能力有对应 Skill 或明确说明不需要。
- [ ] 相关 `rules/*.mdc` 未被违反。
- [ ] 后端或前端测试已运行，失败项有明确原因。
- [ ] Demo 路径能覆盖至少一个真实 Adapter，不全依赖 Mock。
- [ ] AI 协作记录能说明至少一个关键工程决策。
