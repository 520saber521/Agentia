# 窗口间消息通信修复文档

## 问题分析

### 原始架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                           Router Server                              │
│                        (http://127.0.0.1:8765)                       │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐           │
│  │  MAIN   │    │    A    │    │    B    │    │    C    │    ...    │
│  │  inbox  │    │  inbox  │    │  inbox  │    │  inbox  │           │
│  └─────────┘    └─────────┘    └─────────┘    └─────────┘           │
└─────────────────────────────────────────────────────────────────────┘
         ↑              ↑              ↑              ↑
         │              │              │              │
    ┌────┴────┐    ┌────┴────┐    ┌────┴────┐    ┌────┴────┐
    │ Window  │    │ Window  │    │ Window  │    │ Window  │
    │  MAIN   │    │    A    │    │    B    │    │    C    │
    │ (codex) │    │ (codex) │    │ (codex) │    │ (codex) │
    └─────────┘    └─────────┘    └─────────┘    └─────────┘
```

### 问题根因

1. **启动脚本未使用 Shell Proxy**
   - 原来的启动脚本直接运行 `codex`，没有通过 `shell_proxy.py` 包装
   - `listen` 命令虽然在后台运行，但依赖 AppleScript 自动输入（需要辅助功能权限，且不可靠）

2. **消息投递链路断裂**
   ```
   发送者 → Router → 接收者 inbox → ❌ 无法传达给 codex
   ```

## 解决方案

### 已完成的修复

1. **修改启动脚本** (`scripts/terminal/launch_terminal.sh` 和 `scripts/iterm2/launch_iterm2.sh`)
   - 现在 codex 通过 `shell_proxy.py` 运行
   - Shell Proxy 在后台轮询 Router，获取新消息

2. **增强 Shell Proxy** (`src/launcher/shell_proxy.py`)
   - 添加 `wait_for_router()` 等待 Router 服务可用
   - 改进消息格式，更容易被 Agent 理解
   - 添加 `send_message()` 函数支持发送消息

### 消息流程（修复后）

```
┌─────────────────────────────────────────────────────────────────────┐
│                           Router Server                              │
│                        (http://127.0.0.1:8765)                       │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐           │
│  │  MAIN   │    │    A    │    │    B    │    │    C    │    ...    │
│  │  inbox  │    │  inbox  │    │  inbox  │    │  inbox  │           │
│  └─────────┘    └─────────┘    └─────────┘    └─────────┘           │
└─────────────────────────────────────────────────────────────────────┘
         ↑↓             ↑↓             ↑↓             ↑↓
    ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐
    │shell_proxy │ │shell_proxy │ │shell_proxy │ │shell_proxy │
    │  (轮询)    │ │  (轮询)    │ │  (轮询)    │ │  (轮询)    │
    └────────────┘ └────────────┘ └────────────┘ └────────────┘
         ↓              ↓              ↓              ↓
    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
    │ Window  │    │ Window  │    │ Window  │    │ Window  │
    │  MAIN   │    │    A    │    │    B    │    │    C    │
    │ (codex) │    │ (codex) │    │ (codex) │    │ (codex) │
    └─────────┘    └─────────┘    └─────────┘    └─────────┘
```

## 使用方法

### 1. 启动系统

```bash
cd /Users/a1/Desktop/366.1/codex_team_architecture_v2

# 启动 Router 服务（在后台运行）
python3 src/api/server.py . --host 127.0.0.1 --port 8765 &

# 启动多窗口
python3 src/cli/team.py start --roles MAIN,A,B,C,D
```

### 2. 发送消息

在任意窗口中，使用 CLI 发送消息：

```bash
# 从 MAIN 向 A 发送消息
python3 src/cli/team.py say --from MAIN --to A --text "请帮我实现一个函数"

# 从 A 回复 MAIN
python3 src/cli/team.py reply --from A --to MAIN --corr <message_id> --text "收到，正在处理"
```

### 3. 在 Codex 中响应

当 Agent 收到消息时，会在终端看到类似这样的输出：

```
============================================================
📨 TEAM MESSAGE FROM: MAIN
   Type: ask/clarify | Task: CHAT-MAIN-20260117-161853
------------------------------------------------------------
请帮我实现一个函数
------------------------------------------------------------
💡 To reply, use: python3 src/cli/team.py reply --from A --to MAIN --corr xxx-1-1 --text "your reply"
============================================================
```

## 环境变量

Shell Proxy 支持以下环境变量：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ROUTER_URL` | `http://127.0.0.1:8765` | Router 服务地址 |
| `POLL_INTERVAL` | `1.0` | 轮询间隔（秒） |
| `TEAM_AGENT_ID` | `UNKNOWN_AGENT` | Agent 实例 ID |
| `TEAM_ROLE` | `AGENT` | Agent 角色名 |

## 已知限制

1. **消息显示在终端**：消息会打印到终端 stdout，Agent (Codex) 需要被提示去查看并响应
2. **需要手动回复**：当前需要使用 CLI 命令手动发送回复消息
3. **Router 必须先启动**：在启动窗口之前，Router 服务必须已经运行

## 后续改进

1. **自动响应**：可以扩展 shell_proxy 来自动将消息注入到 Codex 的对话上下文
2. **双向 WebSocket**：使用 WebSocket 替代 HTTP 轮询，提高实时性
3. **消息持久化**：确保消息在 Router 重启后不会丢失
