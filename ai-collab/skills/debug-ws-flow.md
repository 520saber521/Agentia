# Skill: 排查 WebSocket 流式链路问题

**When to use**：用户报"消息卡住不动了 / 取消没反应 / 重连后消息错位 / 刷新后历史丢了 / 连不上"。

**Time budget**：15 ~ 60 分钟。多数问题在 5 个常见原因之一。

---

## 第一原则：分层逼近，不要乱猜

W1 链路一共 6 层，问题必然落在其中某一层。**按这个顺序逐层 ping**：

```
浏览器 UI  →  Zustand store  →  WSClient  →  Vite proxy  →  BFF /ws  →  MockAdapter
   ①              ②              ③              ④              ⑤              ⑥
```

> 建议直接复制下面的 5 个 ping 步骤，"哪步红就停在哪步"。

### Step 1 — 浏览器是否真的连上了？

打开 DevTools → Network → WS：

- 看 `ws` 状态是不是 `101 Switching Protocols`
- 不是 → 检查 Vite 是否在跑 (`netstat -ano | findstr :5173`)、BFF 是否在跑 (`Get-NetTCPConnection -LocalPort 8788`)
- 是 → 进 Step 2

### Step 2 — UI 状态有没有上对？

DevTools Console 里：

```js
useChatStore.getState()
// 重点看：status / currentConvId / streamingMessageId / messages.length
```

- `status === "disconnected"`：WS 没接上 → Step 4
- `currentConvId === null`：没选会话 → 是不是初始拉 `/api/conversations` 失败了？看 Console 红字
- `streamingMessageId !== null` 但 UI 没动：reducer 没把 chunk 拼进去 → Step 3

### Step 3 — Reducer 是不是收到事件了？

临时打开：

```ts
// web/src/stores/useChatStore.ts 的 init() 里
ws.onEvent((evt) => {
  console.log("[ws<<]", evt.type, evt);   // ←临时加
  // ...原逻辑
});
```

- 没 log → 事件根本没到客户端 → Step 4
- 有 log 但 UI 没更新 → 90% 是 `conversation_id ≠ currentConvId`：reducer 默认忽略他会话事件。检查 BFF 用的 conversation_id 是不是你以为的那个

### Step 4 — Vite proxy 有没有把 WS 透传？

```powershell
# 直连 BFF（绕开 Vite）
Invoke-WebRequest -Uri http://127.0.0.1:8788/health
```

200 → BFF 自己没问题，问题在 Vite proxy；检查 `web/vite.config.ts` 的 `/ws` 块里 `ws: true` 必须开。

### Step 5 — BFF 日志里有没有报错？

BFF 启动时是 `INFO` 日志级别，每条 WS 事件都会有结构化日志：

```
ws[abc12345] recv send_message conv=conv_demo
ws[abc12345] send agent_typing
ws[abc12345] send stream_chunk seq=0
```

- 看不到 `stream_chunk`：MockAdapter 一开始就报错了 → Step 6
- 看到 `stream_chunk` 但前端没收到：`outbound` 队列卡了？检查 `Connection` 的 maxsize 是否被打满（极少）

### Step 6 — MockAdapter / 真 Adapter 本体

直接跑 `server/tests/test_mock_adapter.py` 看是否绿。绿 → Adapter 本身没问题，回到 Step 5。

---

## 5 个最常踩的坑

| # | 症状 | 真因 | 修法 |
|---|---|---|---|
| 1 | "刷新后历史只剩 1 条" | join 时 `limit` 缺省被设小了 | 检查 `selectConversation` 里 `fetchMessages(id, 200)` 与 `ws.send({join, limit: 200})` |
| 2 | "取消按钮没反应" | `streamingMessageId` 已被 `message_done` 清掉，但 UI 上 cancel 仍可点 | 让按钮在 `streamingMessageId === null` 时 disable |
| 3 | "断网回来消息重了" | 重连后客户端再次 join，服务端推 history，reducer 又走 `message_created` 路径 | reducer 里已有 `messages.some(x => x.id === m.id)` 兜底；如果还重，看 ID 是不是被改了 |
| 4 | "Header 一直 disconnected" | Vite proxy 没把 `Upgrade` 头透传 | `proxy['/ws'].ws` 必须 `true`；用 `http://127.0.0.1:5173/ws` 直连测试 |
| 5 | "agent_typing 一直亮着" | `message_done` 之后没清 typing | reducer 已经清了；如果还亮，看 reducer.test.ts 是不是被旁路了 |

---

## 把这次调试沉淀回来

修完之后，**回 `ai-collab/SPEC.md` 对应 Feature 加一条反例（"WHEN ... THEN must not ..."）**，并在 `reducer.test.ts` 里把这个反例固化成断言。否则下次还会犯同一个错。
