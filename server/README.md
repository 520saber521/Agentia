# AgentHub BFF

`server/` 是 AgentHub v2 的 BFF / Gateway 层，负责把 Web IM 前端、Agent Adapter、Orchestrator、SQLite 持久化和 WebSocket 实时通信连接起来。

## 主要能力

### REST API

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查 |
| `GET` | `/api/agents` | Agent 列表 |
| `POST` | `/api/agents` | 创建自定义 Agent |
| `PUT` | `/api/agents/{id}` | 更新 Agent |
| `DELETE` | `/api/agents/{id}` | 删除 Agent |
| `GET` | `/api/agents/{id}/prompt` | 查看 Agent 系统提示词 |
| `GET` | `/api/agents/{id}/executions` | 查看 Agent 执行记录 |
| `GET` | `/api/conversations` | 会话列表，支持归档过滤和搜索 |
| `POST` | `/api/conversations` | 创建单聊或群聊 |
| `GET` | `/api/conversations/{id}` | 会话详情 |
| `PATCH` | `/api/conversations/{id}` | 更新标题、置顶、归档状态 |
| `GET` | `/api/conversations/{id}/messages` | 分页读取历史消息 |
| `POST` | `/api/messages/{id}/pin` | pin 关键消息 |
| `POST` | `/api/messages/{id}/unpin` | 取消 pin |
| `GET` | `/api/conversations/{id}/pinned-messages` | 读取长期上下文消息 |
| `GET` | `/api/conversations/{id}/context-stats` | 上下文统计 |

Artifact、Trace、Animation 相关 API 分布在 `server/api/` 下。

### WebSocket

WebSocket 地址：`/ws`

客户端事件：

- `ping`
- `join`
- `send_message`
- `cancel`
- `tool_confirm_response`

服务端事件：

- `hello`
- `pong`
- `history`
- `message_created`
- `agent_typing`
- `stream_chunk`
- `message_done`
- `message_cancelled`
- `usage`
- `error`
- `agents`
- `task_update`
- `artifact_ready`
- `message_pinned`
- `message_unpinned`
- `context_info`
- `tool_call`
- `tool_confirm_request`
- `anim_agent_created`
- `anim_agent_status`
- `anim_beam`
- `anim_event`

## 数据库

默认数据库文件：`server/.agenthub/bff.db`

主要表：

- `conversation`
- `conversation_member`
- `message`
- `agent`
- `agent_execution`
- `artifact`
- `task`
- `trace_entry`

启动时会执行数据库初始化和默认数据 seed。

## 核心模块

```text
server/
├── main.py                  # FastAPI 应用入口
├── ws.py                    # WebSocket Hub 与事件封装
├── orchestrator.py          # 主 Agent 协调器
├── dag_engine.py            # 子任务 DAG 执行
├── router_client.py         # Router 客户端
├── adapters/                # Agent Adapter
├── api/                     # REST 路由
├── db/                      # ORM 模型、engine、seed
├── handlers/                # WS 事件处理器
├── services/                # 业务服务
└── tests/                   # 后端测试
```

## 启动

```powershell
cd D:\Agentia\Agentia
python -m venv server\.venv
server\.venv\Scripts\python.exe -m pip install -r server\requirements.txt
server\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8788 --app-dir server
```

访问：

- 健康检查：<http://localhost:8788/health>
- 会话 API：<http://localhost:8788/api/conversations>

## 测试

```powershell
cd D:\Agentia\Agentia
python -m pytest -c server\pyproject.toml server\tests
```

当前仍需对齐的测试主要集中在默认 seed 数据、Diff 应用后的消息类型、群聊 fan-out 流式事件和取消时机。
