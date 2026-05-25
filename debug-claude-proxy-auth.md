# Debug Session: claude-proxy-auth

Status: [OPEN]

## Symptom

用户使用中转站 Key 与 `https://api.apikey.fun` 后，Orchestrator 子任务仍返回：
`Anthropic API 401 authentication_error invalid x-api-key`。

## Hypotheses

1. 数据库中的 `agent_claude.config.base_url` 没有实际写入，后端仍请求官方 Anthropic 地址。
2. `base_url` 写入为 `https://api.apikey.fun/v1`，但中转站要求的是不同路径或不同协议格式。
3. 中转站 Key 本身无效、过期、余额不足或不支持 Anthropic Messages API。
4. Adapter 使用 Anthropic Header `x-api-key`，但中转站要求 OpenAI 风格 `Authorization: Bearer`。
5. 后端服务读取的是另一个 SQLite 数据库实例，导致配置更新写到了不同 DB。

## Evidence Plan

- 查询当前 server/.agenthub/bff.db 中 agent_claude 的 masked key、model、base_url。
- 检查 Claude Adapter 请求头与 URL 拼接逻辑。
- 用不泄露 key 的方式测试中转站 endpoint 的鉴权格式。
- 根据证据决定是否改 Adapter 支持 proxy auth header。
