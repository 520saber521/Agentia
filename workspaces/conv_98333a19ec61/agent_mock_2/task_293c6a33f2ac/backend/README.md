# 仿 QQ 网页后端

基于 FastAPI + WebSocket 的实时聊天后端，提供用户注册/登录、好友管理、实时消息功能。

## 启动方式

1. 安装依赖：`pip install -r requirements.txt`
2. 运行服务：`uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
3. 打开前端 `static/index.html` 即可使用

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/auth/register | 注册新用户 |
| POST | /api/auth/login | 登录并获取 token |
| GET | /api/friends | 获取好友列表 |
| POST | /api/friends/add | 添加好友 |
| WS | /ws?token={token} | WebSocket 实时聊天 |

详细文档请查看源码注释。
