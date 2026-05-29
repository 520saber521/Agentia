# Skill: 新增一个消息类型（`content.type`）

**When to use**：要扩展 `Message.content`（例如：`task_card` / `diff_card` / `preview_card` / `artifact_ref`）。

**Time budget**：1 ~ 2 h，主要在前端组件 + 类型对齐。

**Pre-reads**

- `docs/ARCHITECTURE.md` §3.4 "消息内容结构（content 字段的 JSON 结构）"
- `server/services/message.py` — 当前 `content_type` 落库方式
- `web/src/components/MessageBubble.tsx` — UI 分发点
- `ai-collab/SPEC.md` — 看看新类型属于哪个 Feature

---

## Steps

### 1. 起草 schema（约 10 分钟）

在 PR/会话里先写 JSON Schema，类似：

```jsonc
{
  "type": "task_card",
  "title": "OAuth 全栈",
  "subtasks": [
    {"id": "st_1", "agent_id": "claude_code", "status": "pending"},
    {"id": "st_2", "agent_id": "codex",       "status": "pending"}
  ],
  "owner_message_id": "msg_xxx"
}
```

把 schema 贴进 `docs/ARCHITECTURE.md` §3.4 的对应小节。

### 2. 后端：类型守卫 + 落库

- 在 `server/services/message.py` 的 `create_message()` 前加个 `validate_content(content)` 调用。
- 校验失败抛 `ValueError`，由 BFF 转 `{type:"error", code:"bad_content"}`。
- DB 层无需改 schema —— `content` 字段就是 JSON，但要把 `content_type` 字段写成新的 `type` 值，便于按类型筛查。

### 3. 前端：类型 + 组件 + 分发

3 个改动点：

```
web/src/types.ts                          # 在 MessageContent 联合里加新分支
web/src/components/MessageBubble.tsx      # 根据 content.type 分发到具体组件
web/src/components/<NewCard>.tsx          # 新组件，纯展示，事件回调走 props
```

### 4. Reducer 兼容性 check

- 如果新类型会随 `message_created` 进来：**不需要改 reducer**，因为 reducer 不解析 content。
- 如果需要"流式更新卡片字段"（如 task 状态变化）：**必须** 走专用 `ServerEvent`（如 `task_status_changed`），不要在 `stream_chunk` 里塞 JSON。

### 5. 测试

- Vitest：`reducer.test.ts` 里加一个 `message_created` 带新 content type 的 case，断言它被追加到 messages 末尾。
- Pytest：`test_db.py` 加一个 "落库 + 读回，content_type 等于 'task_card'" 的 case。

---

## 反模式

- ❌ **在 `stream_chunk` 里夹 JSON delta 拼半个卡片**：reducer 会把 delta 当 text 拼上去。卡片"状态变化"必须走专用 `ServerEvent`。
- ❌ **直接改 `Message.content_type` 的枚举但忘了同步前端 types.ts**：会让 TypeScript 跑 `never` 类型 bug。

---

## 落地清单（PR 自检）

- [ ] `docs/ARCHITECTURE.md` §3.4 已加 schema
- [ ] `ai-collab/SPEC.md` 对应 Feature 已加 Acceptance Criteria
- [ ] 后端 `validate_content` 已加校验
- [ ] 前端 types.ts + MessageBubble + 新组件已联通
- [ ] Vitest + Pytest 各加 1 个 case
