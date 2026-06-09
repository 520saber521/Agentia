# Skill：调试 WebSocket 消息流

> 本 Skill 聚焦问题定位。调试完成后如需修改代码，请参考 [new-feature.md](new-feature.md) 的协作流程确保变更可追溯。

## 使用场景

当出现以下问题时使用本 Skill：

- 前端收不到 Agent 回复。
- 流式内容串到错误气泡。
- 取消按钮无效或取消了错误 Agent。
- 刷新后历史重复、乱序或缺失。
- 群聊 fan-out 中某个 Agent 失败影响其他 Agent。
- WS 断线重连后状态错乱。

## 预读材料

1. `server/ws.py`：连接、发送队列、Hub 逻辑。
2. `server/handlers/join.py`：历史回放。
3. `server/handlers/send_message.py`：消息创建、Adapter 调用、流式推送。
4. `server/handlers/cancel.py`：取消语义。
5. `web/src/ws/client.ts`：前端连接、心跳、重连。
6. `web/src/stores/reducer.ts`：服务端事件如何影响 UI 状态。

## 调试顺序

### 1. 确认连接状态

- 后端 `/health` 是否正常。
- 浏览器是否连接到正确的 `/ws`。
- 前端是否收到 `hello`。
- 心跳是否有 `ping` 和 `pong`。

如果没有 `hello`，优先查 WS 地址、CORS、服务端启动参数和浏览器控制台。

### 2. 确认 join 与 history

检查前端发送：

```json
{"type": "join", "conversation_id": "conv_xxx", "limit": 100}
```

服务端应返回：

```json
{"type": "history", "conversation_id": "conv_xxx", "messages": []}
```

验收：

- `conversation_id` 存在。
- `limit` 在合法范围内。
- 历史消息按 `created_at ASC`。
- 重连后不会重复追加同一批消息。

### 3. 确认发送链路

一次正常发送至少应看到：

```text
message_created    用户消息
message_created    Agent 占位消息
agent_typing       Agent 开始
stream_chunk       一个或多个文本增量
message_done       Agent 完成
```

群聊 fan-out 中，每个 Agent 都必须有独立 Agent 占位消息和独立 `message_id`。

### 4. 定位串流问题

如果内容进入错误气泡，按顺序检查：

- `stream_chunk.message_id` 是否正确。
- reducer 是否按 `message_id` 查找消息。
- 是否存在重复 `message_id`。
- 是否在组件中用“最后一条消息”推断 streaming 目标。

规则：任何流式更新都不能依赖数组末尾位置。

### 5. 定位取消问题

取消请求必须携带目标：

```json
{"type": "cancel", "message_id": "msg_agent_xxx"}
```

检查：

- 前端按钮绑定的是 Agent 消息 ID，不是用户消息 ID。
- 后端 in-flight 表中存在该 `message_id`。
- Adapter 收到 cancel 后 return。
- 其他 Agent 的 in-flight task 没有被误 set。

### 6. 定位历史重复

检查 reducer：

- `history` 是否按 ID 合并而不是盲目追加。
- `message_created` 收到已有 ID 时是否忽略或更新。
- 重连后的 `join` 是否清理了当前会话临时 streaming 状态。

### 7. 定位 fan-out 局部失败

检查服务端：

- 每个目标 Agent 是否独立创建 task。
- 单个 Adapter yield error 后是否只结束自己的消息。
- fan-out 聚合逻辑是否等待所有目标进入终态。

检查前端：

- 错误事件携带 `message_id` 时是否只标记对应气泡。
- 群聊成员面板和消息流是否按 `sender_id` 展示。

## 最小复现记录

复现必须记录：

- 会话 ID。
- 发送 payload。
- 收到的服务端事件序列。
- 期望事件序列。
- 实际偏差。

## 修复原则

- 协议字段缺失时，先补服务端事件，再改 reducer。
- 状态映射错误时，优先补 reducer 测试。
- Adapter 取消或错误异常时，按 `skills/new-adapter.md` 修复 Adapter。
- 不用前端定时器或延迟来掩盖服务端事件顺序问题。

## 验证清单

- [ ] 单聊流式回复正常。
- [ ] 群聊两个以上 Agent 并发回复互不覆盖。
- [ ] 取消一个 Agent 不影响另一个 Agent。
- [ ] 刷新后历史不重复、不丢失。
- [ ] 断线重连后能重新 join 当前会话。
- [ ] reducer 测试覆盖本次修复的事件序列。
