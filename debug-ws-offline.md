# Debug Session: WS Offline

Status: [OPEN]

## Symptom

前端页面显示“离线”。用户截图显示 AgentHub 顶部连接状态为离线。

## Hypotheses

1. 前端 dev server 已停止或当前页面连接的是旧的前端实例。
2. 后端 FastAPI 服务仍运行，但 WebSocket `/ws` 握手失败。
3. 前端 WebSocket URL 计算错误，连接到了错误端口或路径。
4. 后端启动成功但运行时异常导致 WebSocket 处理未就绪。
5. 浏览器页面没有刷新，仍保留断开的旧 WebSocket 状态。

## Evidence Plan

- 检查后端进程状态和日志。
- 检查前端 dev server 是否仍在运行。
- 读取前端 WebSocket 客户端实现确认连接 URL。
- 验证后端 health 接口。
- 必要时添加最小网络日志采集。
