# AgentHub - 多 Agent 协作平台

AgentHub 是一个以 IM 聊天为核心交互范式的多 Agent 协作平台原型。用户可以像使用飞书或微信一样新建会话、选择 Agent、发送消息，并在群聊中通过 `@` 指定多个 Agent 协作完成任务。

## 当前完成度

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| Web IM 前端 | 已完成原型 | React + Vite + Tailwind，三栏布局：会话列表、聊天流、上下文侧栏 |
| 会话管理 | 已完成 | 新建、查询、置顶、归档、搜索、单聊/群聊 |
| WebSocket 消息流 | 已完成 | 连接、心跳、历史回放、流式回复、取消生成 |
| 多 Agent 适配器 | 已完成基础版 | Mock、Claude Code、Claude Agent SDK、Codex |
| 群聊 fan-out | 已完成基础版 | 根据会话成员和 `mentions` 分发给多个 Agent |
| Orchestrator | 已完成原型 | 复杂任务识别、拆解、子任务分派、进度事件、汇总 |
| 富媒体产物 | 已完成基础版 | 文本、代码、网页预览、文件、Diff、任务状态、部署状态卡片 |
| 产物编辑 | 已完成基础版 | Monaco 编辑器、版本历史、保存新版本、应用 Diff |
| 自建 Agent | 已完成基础版 | REST 创建/更新/删除 Agent，聊天命令创建 Agent |
| 部署发布 | P2/占位 | 有部署状态卡片类型，尚未形成完整一键部署闭环 |
| 桌面端/移动端 | P2 | 当前主力端为 Web |

## 技术栈

- 后端：FastAPI、SQLAlchemy 2.x async、SQLite、WebSocket、pytest。
- 前端：React 18、TypeScript、Vite、Tailwind CSS、Zustand、Monaco Editor、Vitest。

## 目录结构

```text
AgentHub/
├── server/                  # BFF / Gateway，FastAPI + WS + SQLite
├── web/                     # React 前端
├── src/                     # v1 多 Agent Router / Scheduler 能力沉淀
├── prompts/                 # Agent 角色提示词
├── docs/                    # 架构与任务文档
├── ai-collab/               # 协作记录、规则、技能说明
└── tests/                   # 旧调度器测试
```

## 快速启动

### 后端

```powershell
cd D:\Agentia\Agentia
python -m venv server\.venv
server\.venv\Scripts\python.exe -m pip install -r server\requirements.txt
server\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8788 --app-dir server
```

### 前端

```powershell
cd D:\Agentia\Agentia\web
npm install
npm.cmd run dev
```

浏览器打开：<http://localhost:5173/>

## 测试

```powershell
cd D:\Agentia\Agentia
python -m pytest -c server\pyproject.toml server\tests

cd D:\Agentia\Agentia\web
npm.cmd test
```

当前已知状态：

- 前端 reducer 测试通过。
- 后端 `server/tests` 大部分通过，仍有少量用例需要与最新行为对齐。
- 根目录 `tests/` 中存在 v1 调度器旧测试，部分接口名已与当前实现不一致。

## 推荐答辩 Demo

1. 新建群聊，选择 Orchestrator、Frontend、Backend、Database、Test Agent。
2. 发送：`@Orchestrator 帮我实现一个登录页，包括前端页面、后端接口、数据库表设计和测试建议`。
3. 展示 Orchestrator 拆解任务、多个 Agent 依次回复。
4. 展示网页预览卡片、代码编辑器、版本历史和 Diff 应用。
5. 说明部署发布、桌面端、移动端作为 P2 扩展方向。

## 后续优化重点

1. 修复后端剩余测试失败，保证 BFF 测试全绿。
2. 收敛一条稳定的端到端 Demo 链路。
3. 完善部署发布闭环：静态站点预览 URL、源码打包下载。
4. 强化 Agent 管理页：能力标签、密钥状态、执行记录。
5. 补充架构图和功能验收清单，方便答辩展示。
