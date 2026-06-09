# Skill：新增一个消息内容类型

> 本 Skill 是 [new-feature.md](new-feature.md)（端到端新功能开发）的子技能。如果是全新 Feature 开发，请先阅读元技能了解完整流程。

## 使用场景

当需要扩展 `Message.content.type` 时使用本 Skill。例如新增任务卡片、部署状态、Artifact 引用、工作区变更、权限确认、Trace 摘要等富媒体消息。

## 预读材料

1. `ai-collab/SPEC.md`：确认新类型属于哪个 Feature。
2. `server/services/content_schema.py`：服务端内容校验。
3. `server/services/message.py`：消息创建与持久化。
4. `web/src/types.ts`：前端类型联合。
5. `web/src/components/ContentRenderer/index.tsx`：渲染分发。
6. `web/src/stores/reducer.ts`：事件如何进入消息列表。

## 命名规则

- `content.type` 使用小写蛇形，例如 `task_status`、`deploy_status`、`workspace_change`。
- 类型名必须前后端一致。
- 错误码不得复用类型名，避免协议含义混淆。

## 实施步骤

### 1. 先定义 schema

在开始写代码前，先写清楚 JSON 结构。示例：

```json
{
  "type": "deploy_status",
  "artifact_id": "art_xxx",
  "status": "building",
  "preview_url": "http://localhost:8788/api/artifacts/art_xxx/preview",
  "message": "正在生成本地预览"
}
```

schema 必须明确：

- 必填字段。
- 可选字段。
- 字段类型。
- 状态枚举。
- 失败或空状态如何表达。

### 2. 更新规格

在 `ai-collab/SPEC.md` 对应 Feature 中补充验收标准：

- 何时生成该类型。
- 后端如何校验。
- 前端如何渲染。
- 失败时如何降级。

### 3. 更新后端校验

在 `server/services/content_schema.py` 或当前项目等价位置增加校验分支。

要求：

- 非法 `content.type` 返回稳定错误。
- 缺失必填字段返回 `invalid_content` 或项目现有等价错误码。
- 服务端持久化前应规范化字段，例如补默认值、过滤未知字段。

### 4. 更新前端类型

在 `web/src/types.ts` 中扩展 `MessageContent` 联合类型。

要求：

- 字段名与后端 schema 一致。
- 状态枚举使用 TypeScript 字面量联合。
- 不使用 `any` 绕过类型检查。

### 5. 更新渲染组件

新增或扩展 `web/src/components/ContentRenderer/` 下组件，并在分发入口接入。

要求：

- 未加载、加载失败、空数据都要有稳定 UI。
- 长文本、长代码、iframe、文件列表不能撑破消息流。
- 用户操作通过 props 回调或 store action，不在组件内直接请求散落 API。

### 6. 判断是否需要新 ServerEvent

- 如果新类型只在 `message_created` 或 `message_done` 中出现，通常不需要新事件。
- 如果内容会持续变化，例如任务进度、部署状态、工具确认，应新增专用事件。
- 禁止把结构化卡片状态塞进 `stream_chunk` 文本 delta 中。

### 7. 编写测试

最低测试：

- 后端：合法 content 可写入，非法 content 被拒绝。
- 前端：`message_created` 携带新 content type 时能进入消息列表。
- 渲染：组件能渲染成功态和失败态。
- 如果新增事件：reducer 覆盖事件更新逻辑。

## 验证命令

```powershell
cd D:\桌面\Agentia_v7\Agentia
python -m pytest -c server\pyproject.toml server\tests
```

```powershell
cd D:\桌面\Agentia_v7\Agentia\web
npm.cmd test
```

## 常见错误

- 只改前端类型，忘记后端 schema。
- 只改后端写库，忘记 `ContentRenderer`。
- 在 `stream_chunk` 中拼半截 JSON。
- 新状态枚举没有测试，导致 UI 分支漏掉。
- 大文件正文直接塞进消息，导致历史加载变慢。

## PR 自检

- [ ] `SPEC.md` 已补验收标准。
- [ ] 后端 schema 已更新。
- [ ] 前端类型已更新。
- [ ] 渲染分支已接入。
- [ ] 后端和前端测试已覆盖。
- [ ] 如涉及动态更新，已新增专用 ServerEvent。
