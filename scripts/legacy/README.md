# `scripts/legacy/` — v1 终端形态启动脚本（已归档）

> **本目录中的脚本不再是 AgentHub 的主入口。**
>
> 它们对应的是 **v1 形态**：本地 HTTP Router + 5 个终端窗口（MAIN / A / B / C / D），由 `src/launcher/` 通过 AppleScript / iTerm2 / tmux 拉起。
>
> v2 形态请使用根目录 `README.md` 中的"一键启动"步骤（启动 BFF + Web）。v1 详细说明见 [`docs/v1-terminal.md`](../../docs/v1-terminal.md)。

## 文件清单

| 文件 | 作用 | v2 替代 |
| --- | --- | --- |
| `start_team.sh` | 一键启动 Router + 5 终端窗口（macOS） | `scripts/dev.ps1` / `scripts/dev.sh`（W2 新建） |
| `stop_team.sh` | 停止全部 | `Ctrl+C` 终止 BFF / Web 即可 |
| `status_team.sh` | 状态查询 | `GET /health` + `GET /api/conversations` |
| `test_full.sh` | 端到端冒烟（v1） | `server/tests/smoke_w1.py` ~ `smoke_all.py` |
| `test_messaging.py` | Router 消息冒烟 | 同上 |
| `iterm2/launch_iterm2.sh` | iTerm2 窗口拉起 | （v2 不再需要） |
| `terminal/launch_terminal.sh` | Terminal.app 窗口拉起 | （v2 不再需要） |

## 为什么不直接删？

1. v1 后端模块（`src/router/`、`src/scheduler/`、`src/protocol/` 等）在 v2 仍**完整复用**，保留 v1 启动脚本能让贡献者快速验证这部分仍可独立运行。
2. v1 的协议契约（`review` / `assign` / `done` / ...）是 v2 群聊语义的底层；保留运行入口有助于排查 v2 Router 接入时的回归。
3. 课题答辩需要"v1 → v2 迁移"作为叙事支撑（"我们没有重写，而是换了一层外壳"）。

## 任何时候你都不应该

- 在 v2 BFF 启动脚本里调用本目录中的任何文件。
- 在 v2 SPEC / Skills / Rules 中引用本目录的路径作为现行行为。
- 把本目录里的脚本作为答辩 demo 的主入口。
