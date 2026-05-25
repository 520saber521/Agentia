# Debug Session: code-not-rendering

Status: [OPEN]

## Symptom

用户要求 Orchestrator 写一个 html 页面/代码，但网页里只显示普通文本和任务卡片，没有显示代码块或代码卡片。

## Hypotheses

1. Agent 回复内容是普通 `text` 消息，没有 Markdown fenced code block，因此前端没有可渲染的代码内容。
2. ContentRenderer 只在 `content.type === "code"` 时渲染 CodeBlock，不会从文本 Markdown 中解析 ```html 代码块。
3. Orchestrator 子任务通过 Mock Agent 执行，Mock 模板只回显任务描述，不会真正产出代码。
4. Claude 子任务没有成功执行或被分派到非代码任务，导致没有生成实际代码输出。
5. Artifact 创建逻辑只对结构化 `code/file/preview` content 生效，普通文本里的代码不会自动入库为 artifact。

## Evidence Plan

- 查询当前会话最新消息 content.type 和 text 片段。
- 检查 ContentRenderer 是否支持 Markdown code fence。
- 检查 Orchestrator 分派到 Mock/Claude 的 Agent 输出形态。
- 根据证据修复：增加文本代码块解析或让代码任务产出结构化 code artifact。
