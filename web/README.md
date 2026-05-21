# AgentHub Web

AgentHub v2 的 **React + Vite + TypeScript** 前端。当前进度：**W1 Day5（W1 收尾）**。

> 设计来源：`docs/ARCHITECTURE.md` §5.1 / §7.2 / §7.3。
> 行为契约（含验收标准）在 [`ai-collab/SPEC.md`](../ai-collab/SPEC.md) W1 F-W1-1 ~ F-W1-6。
> 前端硬约束：[`ai-collab/rules/frontend.mdc`](../ai-collab/rules/frontend.mdc)。

## 当前能力（Day5）

- 三栏 IM 布局：Header + 会话列表 + 消息流 + 输入区
- 自研 `WSClient`：25 s 心跳 + 指数退避重连 + 显式断开
- Zustand `useChatStore` + **纯 reducer** `stores/reducer.ts`：所有 `ServerEvent → state` 的映射收敛在一个纯函数里，调用方按返回的 `effects` 触发副作用
- REST 客户端：`/api/conversations` 与 `/api/conversations/{id}/messages` + Day5 新增 `POST /api/conversations`
- "新建会话" 模态（`NewConversationDialog`）：支持 single / group 类型 + 表单校验
- 完整 send_message → stream_chunk → message_done 链路
- 取消支持：用户中途按"取消"会让 BFF 把 partial 写库
- Vitest 单测：`stores/reducer.test.ts` 覆盖 15 个 case（含未知事件 / 重复 id / 非当前会话 / 错误信号清流式标志）

视觉风格继承 W1 Day3 调色板（暗色 + 蓝色高亮）；W3 起接入 shadcn/ui + 富媒体卡片。

## 技术栈

| 类别 | 选择 |
| --- | --- |
| 框架 | React 18 + TypeScript 5 |
| 构建 | Vite 6 |
| 样式 | TailwindCSS 3 |
| 状态 | Zustand 5 |
| 通信 | 原生 `WebSocket` + `fetch`，无第三方库 |

## 快速启动

> 先确保 [BFF](../server/README.md) 已在 `127.0.0.1:8788` 运行。

```powershell
cd web
npm install
npm run dev          # → http://localhost:5173
```

打包 / 测试：

```powershell
npm run build        # → web/dist/（typecheck + vite build）
npm run preview      # 本地静态预览
npm run typecheck    # 只跑 tsc
npm test             # vitest run（reducer 单测，15 个用例）
npm run test:watch   # 监听模式
```

Vite dev server 自动把 `/api`、`/ws`、`/health` 代理到 BFF，开发期无 CORS 问题。

## 目录结构

```
web/
├── index.html                       ← Vite 入口
├── package.json
├── tsconfig.json / *.app.json / *.node.json
├── vite.config.ts                   ← 含 /api & /ws proxy
├── postcss.config.js
├── tailwind.config.js
└── src/
    ├── main.tsx                     ← React 入口
    ├── App.tsx                      ← 三栏布局
    ├── index.css                    ← Tailwind base
    ├── vite-env.d.ts
    ├── types.ts                     ← 与 BFF 的事件契约
    ├── api/
    │   └── client.ts                ← fetch wrapper（GET + POST）
    ├── ws/
    │   └── client.ts                ← WSClient（重连 / 心跳）
    ├── stores/
    │   ├── useChatStore.ts          ← Zustand store（动作 + 副作用）
    │   ├── reducer.ts               ← Day5 纯 reducer：ServerEvent → state
    │   └── reducer.test.ts          ← Vitest 15 个用例
    └── components/
        ├── Header.tsx
        ├── ConversationListPanel.tsx
        ├── NewConversationDialog.tsx  ← Day5 新增
        ├── MessagePanel.tsx
        ├── MessageBubble.tsx
        └── Composer.tsx
```

## 设计要点速览

- **单 store**：Day4 没有多会话并行需求，所有状态收敛在 `useChatStore`；后续拆 `useTaskStore` / `useArtifactStore`。
- **WS 单写者**：与 BFF 的 `Connection.outbound` 对称，前端这边由 `WSClient` 串行 send。
- **流式拼接**：`stream_chunk` 直接对 `messages[idx].content.text` 做字符串拼接，`MessagePanel` 用一个 `ref` 自动滚到底。
- **state 与 server 双源真值**：每条 `message_done` 都触发 `refreshConversations`，让侧栏的 `last_msg_preview` 与 DB 一致。

## 验收（W1 全部）

- [x] `npm run build` 类型与打包都过（158 kB / gzip 51 kB）
- [x] `npm run dev` 起 :5173，浏览器加载 SPA
- [x] `npm test` 15 个 vitest 用例全绿
- [x] `/api/conversations` 经 vite proxy 返回 `conv_demo`
- [x] WS 经 vite proxy 升级，能收到 `hello` 帧
- [x] 用户输入 → 流式 token → 入库 → 侧栏预览刷新
- [x] 取消按钮可在生成中途中断，partial 落盘
- [x] **(Day5)** 会话列表顶部"＋新建"按钮 → 模态 → POST 创建 → 立即选中

## 与 Day1-3 控制台的关系

`server/static/index.html` 是 Day1-3 留下的"内置调试控制台"，仍由 BFF 在 `/` 直接托管，便于不启动 npm 也能验证 WS。W3 起会改为 mount `web/dist/`。

## 接下来（W2 启动）

- 接入 AgentHub Router（`src/router/*`）→ 群聊 + Orchestrator（见 [`ai-collab/SPEC.md`](../ai-collab/SPEC.md) F-W2-1）
- Composer 加 `@mention` 弹层 + 任务卡片展示位
- 真 Adapter（Claude / Codex）—— 按 [`ai-collab/skills/new-adapter.md`](../ai-collab/skills/new-adapter.md) 走
- 组件层 Vitest + RTL 渲染测（Composer / MessageBubble 边界）
