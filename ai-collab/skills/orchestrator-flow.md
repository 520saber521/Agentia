# Orchestrator 流程 SOP

> 版本：v1.0 · 2026-05-27
> 范围：群聊 `@Orchestrator` 从触发到完成的完整状态机与降级策略

---

## 1. 状态机

```
                 ┌──────────┐
                 │  idle    │
                 └────┬─────┘
         收到 @Orchestrator
                      │
                 ┌────▼─────┐
                 │ planning  │  (3s 内必须推 task_status 卡片)
                 └────┬─────┘
          LLM 分类 / 关键词判断
                      │
          ┌───────────┼───────────┐
          │           │           │
     non_software  software   LLM 不可用
          │           │           │
     ┌────▼────┐ ┌───▼────┐ ┌───▼────┐
     │ single  │ │ complex│ │keyword │
     │ subtask │ │decompose│ │judge   │
     └────┬────┘ └───┬────┘ └───┬────┘
          │           │           │
          └───────────┼───────────┘
                      │
                 ┌────▼─────┐
                 │ running  │  (DAG 并行调度)
                 └────┬─────┘
          ┌───────────┼───────────┐
          │           │           │
     ┌────▼────┐ ┌───▼────┐ ┌───▼────┐
     │  done   │ │ failed │ │blocked │
     │ (全成功)│ │ (≥1失败)│ │(依赖卡死)│
     └────┬────┘ └───┬────┘ └───┬────┘
          │           │           │
          └───────────┼───────────┘
                      │
                 ┌────▼─────┐
                 │ aggregate│  (发汇总卡片 + 可选 HTML 预览)
                 └──────────┘
```

---

## 2. 触发路径

### 2.1 显式 @Orchestrator

```
用户: @Orchestrator 做一个登录页 + 后端 API
```

`send_message.py` 的 `resolve_targets()` 检测到 `@orchestrator`，将目标路由到 Orchestrator。

### 2.2 自动触发（复杂任务检测）

群聊中无 @mentions 时，`_looks_complex_task()` 判断文本是否 ≥24 字符或含关键词（设计/实现/开发/前端/后端/HTML/Web/应用...）。命中后默认路由给 Orchestrator。

---

## 3. LLM 分类（`_llm_classify_task`）

**目的**：替代关键词匹配的 `ComplexityJudge`，让 LLM 判断用户意图属于"软件开发"还是"非软件开发"。

**流程**：
1. 找第一个有 `api_key` 的非 mock Agent
2. 调其 Adapter 发分类 prompt（限时 20s）
3. 返回 `"software"` 或 `"non_software"`

**降级**：LLM 不可用 / 超时 / 错误 → 回退到关键词 `ComplexityJudge`

---

## 4. 子任务分派（`_dispatch_subtask_with_retry`）

### 4.1 Agent 选取（`_pick_agent_for_domain`）

**优先级**：
1. 会话成员 Agent（conversation_member）
2. 全局 Agent（排除 Orchestrator 自己）
3. 硬编码 fallback（A/B/C/D → agent_mock/agent_mock_2/agent_claude/agent_deepseek）

**打分逻辑**（`_agent_capability_score`）：
- Mock adapter → 减 999 分（绝不让 mock 参与真实工作）
- system_prompt 含 domain 关键词 → +30 分
- api_key 存在 → +5 分（微弱加成，防止偏置）

### 4.2 重试策略

- 失败子任务最多重试 1 次（`RETRY_LIMIT = 1`）
- 重试前 `update_task_status` 标记 running，附带 attempt 信息
- 仍失败 → 标记 `failed`，不阻塞其他无依赖子任务

### 4.3 Frontend 子任务的特殊处理

如果子任务 domain = "frontend" 且用户需求含 HTML/网页等关键词：
1. 压缩 prompt（`_compact_frontend_prompt`），限制输出为单文件 HTML
2. 设置 `max_tokens ≥ 24000`（`FRONTEND_PREVIEW_MAX_TOKENS`）
3. 完成后自动尝试 `_extract_html_from_text` 提取完整 HTML
4. 截断时调用 `_close_partial_html` 修复不完整的 HTML 标签

---

## 5. DAG 执行引擎

`dag_engine.py` 的 `DAGExecutor`：
- 入度为 0 的节点立即并发 dispatch
- 节点完成后检查依赖关系，释放被阻塞的节点
- `max_concurrency` = 子任务总数（全并行，因为依赖图已定义了顺序约束）

---

## 6. 汇总与冲突检测

### 6.1 汇总（aggregate）

所有子任务完成后，Orchestrator 在聊天流中推送：
- 每个子任务的状态（✅ / ❌ / ⏸️）
- 冲突检测结果（如有同 domain 多 Agent 修改同一 artifact）
- 可选：自动生成 HTML 预览产物（`_generate_preview_html_with_model`）

### 6.2 冲突检测（`_conflict_resolution_note`）

按 domain 聚合：同 domain 有 ≥2 个完成子任务 → 标记 competing outputs，降级为"保留为独立 review items"。

---

## 7. 失败降级 SOP

| 场景 | 降级策略 | 用户可见 |
|---|---|---|
| 没有可用 Agent | 任务卡片标记 `blocked`，提示"没有可执行该任务的 Agent" | 卡片静态展示 |
| 子 Agent 调用失败 | 重试 1 次 → 仍失败标记 `failed` | 错误消息 + 失败子任务红色标记 |
| LLM 分类不可用 | 回退关键词 ComplexityJudge | 无感知 |
| HTML 预览生成失败 | 展示 fallback 页面（"没有拿到可预览 HTML"） | 用户看到原因 |
| 两个 Agent 同 domain 冲突 | 保留为独立产物，不自动合并 | 汇总消息中标注冲突 |
| 子任务全部 failed | 父任务标记 `failed`，推送降级说明 | 汇总卡片显示失败清单 |
| 用户取消（cancel 事件） | 取消所有 in_flight task | `message_cancelled` |

---

## 8. 调试与可观测

- `DEBUG_ENV_PATH` 环境变量注入（`.dbg/html-preview-truncation.env`）用于 HTML 预览截断问题的远端遥测。
- Trace 链路：每个子任务 dispatch 时写入 `trace_entry` 表，可通过 `GET /api/trace/{message_id}` 查询完整时序。

---

## 9. 与代码的对应

| 流程阶段 | 关键函数 | 文件 |
|---|---|---|
| 入口 | `handle_orchestrator_mention()` | `orchestrator.py` |
| LLM 分类 | `_llm_classify_task()` | `orchestrator.py` |
| 关键词降级 | `ComplexityJudge.judge()` | `src/scheduler/complexity.py` |
| 任务拆分 | `EnhancedTaskDecomposer.decompose_with_contract()` | `src/scheduler/enhanced_decomposer.py` |
| Agent 选取 | `_pick_agent_for_domain()` | `orchestrator.py` |
| 子任务分派 | `_dispatch_subtask_with_retry()` / `_dispatch_subtask_with_result()` | `orchestrator.py` |
| DAG 执行 | `DAGExecutor.execute()` | `dag_engine.py` |
| 冲突检测 | `_conflict_resolution_note()` | `orchestrator.py` |
| HTML 预览生成 | `_generate_preview_html_with_model()` | `orchestrator.py` |
| HTML 提取修复 | `_extract_html_from_text()` / `_close_partial_html()` | `orchestrator.py` |
