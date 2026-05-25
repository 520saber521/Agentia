# AgentHub BFF

AgentHub v2（IM 形态）的 **BFF / Gateway 层**。当前进度：**W1 Day5（W1 收尾完成）**。

> 设计来源：`COURSE_PROPOSAL.md` §三 / §九，`docs/ARCHITECTURE.md` §5.2 / §5.3 / §5.6。
>
> Day4 起前端真正的 SPA 在 [`web/`](../web/README.md)；本目录的 `static/index.html` 仅作"调试控制台"保留。
>
> 行为契约的权威版本在 [`ai-collab/SPEC.md`](../ai-collab/SPEC.md)（W1 F-W1-1 ~ F-W1-6）。

## 当前能力（Day5）

### REST

| Method | Path | 说明 |
| :--: | --- | --- |
| `GET` | `/health` | 健康检查（含连接数） |
| `GET` | `/api/conversations` | 列出所有未归档会话（按 pinned, updated_at desc） |
| `POST` | `/api/conversations` | **(Day5)** 新建会话，owner 默认为 `user_demo`，自动拉入 `agent_ids[]` |
| `GET` | `/api/conversations/{id}` | 单个会话详情（含成员） |
| `GET` | `/api/conversations/{id}/messages?before=&limit=` | 游标分页拉消息（时间正序） |
| `GET` | `/` | 内置 WS 控制台（`static/index.html`） |

### WebSocket（`WS /ws`）

| 方向 | type | 说明 |
| :-: | --- | --- |
| C→S | `ping` | 心跳 |
| C→S | `echo` | 任意 payload 原样回显 |
| C→S | `join` | 订阅会话并回放最近 N 条历史 |
| C→S | `send_message` | 触发 Mock 流式应答（消息真正入库） |
| C→S | `cancel` | 按 `message_id` 取消正在生成 |
| S→C | `hello` | 连接建立后立即下发 |
| S→C | `pong` | 心跳应答 |
| S→C | `echo` | 回显帧 |
| S→C | `history` | join 后的历史回放，`{messages, count}` |
| S→C | `message_created` | 新消息（user 或 agent 占位） |
| S→C | `agent_typing` | "对方正在输入…" |
| S→C | `stream_chunk` | 流式片段，含 `seq` / `delta` |
| S→C | `message_done` | 流式结束，含 `final_content`；DB 已写回 |
| S→C | `message_cancelled` | 取消完成；DB 写回已生成部分 |
| S→C | `usage` | token 用量 |
| S→C | `error` | 协议 / 适配器错误 |

### DB

- 存储：`server/.agenthub/bff.db`（可通过 `AGENTHUB_BFF_DB_URL` 覆盖）
- 引擎：SQLAlchemy 2.x async + aiosqlite
- 启动时自动 `init_db()` + `seed_defaults()`：内置一个 `agent_mock` + 一条 `conv_demo` 单聊
- 四张表：`conversation` / `conversation_member` / `message` / `agent`（schema 见 `docs/ARCHITECTURE.md` §6.2）

### 模块

```
server/
├── main.py              ← FastAPI 入口 + WS Hub + 事件分发
├── conftest.py          ← 把 server/ 加进 sys.path
├── pyproject.toml       ← pytest.asyncio_mode=auto
├── requirements.txt
├── adapters/            ← Day2：AgentAdapter 抽象 + MockAdapter
├── api/
│   ├── __init__.py
│   └── rest.py          ← /api/conversations + /messages
├── db/
│   ├── __init__.py
│   ├── engine.py        ← async engine + session maker
│   ├── models.py        ← 4 张表
│   └── seed.py          ← 默认数据（幂等）
├── services/
│   ├── __init__.py
│   ├── conversation.py  ← list_conversations / list_messages / get_conversation
│   └── message.py       ← create_message / update_message_content / message_to_dict
├── static/
│   └── index.html       ← 三栏 WS 控制台
└── tests/
    ├── conftest.py      ← 临时 DB fixture
    ├── test_mock_adapter.py  ← 8 个
    ├── test_db.py            ← 10 个（Day5 +2）
    ├── test_rest.py          ← 8 个（Day5 +2）
    ├── smoke_day1.py
    ├── smoke_day2.py
    ├── smoke_day3.py
    ├── smoke_day4.py
    └── smoke_w1.py            ← Day5 总验收（6 个 section）
```

## 快速启动（Windows / PowerShell）

```powershell
# 在项目根目录
python -m venv server/.venv
server/.venv/Scripts/Activate.ps1
pip install -r server/requirements.txt
uvicorn main:app --reload --port 8788 --app-dir server
```

或直接用 venv 解释器：

```powershell
server/.venv/Scripts/python.exe -m uvicorn main:app --port 8788 --app-dir server
```

启动后：

- 控制台：<http://localhost:8788/>
- 健康：  <http://localhost:8788/health>
- 会话：  <http://localhost:8788/api/conversations>

## 测试

```powershell
# 单元 + 集成（26 项）
server/.venv/Scripts/python.exe -m pytest -c server/pyproject.toml server/tests

# 端到端 smoke（需先启动 BFF；smoke_w1 §6 还会探测 Vite 是否在 :5173）
server/.venv/Scripts/python.exe server/tests/smoke_day1.py
server/.venv/Scripts/python.exe server/tests/smoke_day2.py
server/.venv/Scripts/python.exe server/tests/smoke_day3.py
server/.venv/Scripts/python.exe server/tests/smoke_day4.py
server/.venv/Scripts/python.exe server/tests/smoke_w1.py     # 一键 W1 总验收
```

## 验收清单

### Day1（✅）

- [x] `/health` ok / WS `hello` / `ping`-`pong` / `echo` / `bad_json`

### Day2（✅）

- [x] `send_message` 触发 `message_created × 2 → agent_typing → stream_chunk × N → message_done`
- [x] `cancel` 后 `message_cancelled`，无后续 chunk

### Day3（✅）

- [x] `pytest` 22 项全过（adapter / db / services / rest）
- [x] `/api/conversations` 含 `conv_demo` 且成员数 = 2
- [x] WS `join` 后收到 `history` 回放
- [x] `send_message` 真正写入 DB，`last_msg_preview` / `updated_at` 同步
- [x] `cancel` 时 partial 文本被 `update_message_content` 落盘
- [x] 新连接 `join` 能回放历史消息

## Day4 增量

- 前端工程 [`web/`](../web/README.md) 落地：Vite 6 + React 18 + TS + Tailwind 3 + Zustand 5
- `web/` 启动 `npm run dev` 后 `:5173` 通过 proxy 接 BFF（`/api` + `/ws` + `/health`）
- 新增 smoke：`server/tests/smoke_day4.py`（4 项：SPA HTML / REST proxy / WS proxy / 流式发送）

## Day5 增量（W1 收尾）

- 新增 `POST /api/conversations`：支持 `single`/`group` 类型；body 校验失败 422；owner 默认 `user_demo`，可注入 `agent_ids[]` 成员
- `services/conversation.py` 加 `create_conversation()`，自动 commit + 复读成员关系
- pytest +4：`test_db.py` 加 `create_conversation_with_members` / `create_conversation_rejects_bad_input`，`test_rest.py` 加 `create_conversation_ok` / `create_conversation_validation`
- 新增 `server/tests/smoke_w1.py`：把 Day1-Day4 全部用例 + Day5 的 POST 端点串成"一键总验收"
- 前端 [`web/`](../web/README.md) Day5 配套：reducer 抽纯函数 + Vitest 15 个用例 + "新建会话" 模态

## 接下来（W2 启动）

| 项 | 关键产出 |
| --- | --- |
| Router 接入 | 包装 `src/router/router.py` 与 `src/scheduler/scheduler.py` 为 `server/orchestrator.py` |
| 真 Adapter | 按 [`ai-collab/skills/new-adapter.md`](../ai-collab/skills/new-adapter.md) 接 Claude / Codex |
| 群聊 `@Orchestrator` | 见 [`ai-collab/SPEC.md`](../ai-collab/SPEC.md) F-W2-1 |
| `POST /api/agents` | 用户自建 Agent |
