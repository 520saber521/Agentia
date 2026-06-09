# Skill：端到端新功能开发（元技能）

## 使用场景

当需要在 AgentHub 中新增一个 Feature 时使用本 Skill。它描述从需求到交付的完整协作流程，确保每一步都留下可追溯的协作资产。适用场景包括：

- 新增后端 API + 前端 UI 的完整功能。
- 新增 Agent Adapter 或消息类型（可结合 `new-adapter.md` / `new-message-type.md` 子技能）。
- 对现有 Feature 做重大行为变更。

## 预读材料

1. `ai-collab/SPEC.md`：确认当前 Feature 状态和验收标准格式。
2. `ai-collab/rules/collaboration.mdc`：协作运行规则，尤其是 R-C-2（先规格后实现）。
3. `ai-collab/records/README.md`：记录模板，最终要写复盘。
4. 与目标模块相关的 `rules/*.mdc`。

## 实施步骤

### 1. 需求 → SPEC

在 `ai-collab/SPEC.md` 中完成以下操作：

- [ ] 新增或更新 Feature 条目（如 `F-9`），包含：用户故事、验收标准（EARS 格式）。
- [ ] 在验收矩阵中新增一行，标注优先级和初始状态（`Planned`）。
- [ ] 明确不做什么（边界）、降级策略（如有 P2/P3 项）。
- [ ] 写清楚验收口径：至少包含正常路径、失败路径、边界条件。

### 2. SPEC → Rule 检查

遍历相关 `rules/*.mdc`，确认：

- [ ] 新设计是否违反任何已有硬约束。
- [ ] 如果设计需要突破某条规则，先在规则文件中更新并说明取舍原因。
- [ ] 预计会产生新规则时，先在记录中标记候选，实现完成后再提炼。

### 3. 判断是否需要新 Skill

- [ ] 如果这是**第一次做某类操作**（如"第一次接 PostgreSQL"），本次不新建 Skill，但要在 records 中详细记录步骤。
- [ ] 如果这是**第二次做同类操作**（如"再接一个新模型"），必须从 records 中提炼步骤，新建或更新 Skill。

### 4. 实现

- [ ] AI 先读相关代码、规则和已有 Skill，再动手改文件。
- [ ] 优先沿用现有服务、类型、组件和测试模式。
- [ ] 后端变更：service → API/handler → 测试。
- [ ] 前端变更：types → API client → store/reducer → 组件 → 测试。
- [ ] 每完成一个可验证的里程碑，运行一次测试。

### 5. 测试

- [ ] 后端 pytest：至少覆盖成功路径和关键失败路径。
- [ ] 前端 vitest：reducer 逻辑必须覆盖；关键交互补组件测试。
- [ ] 手动 smoke：走通至少一条完整用户链路。
- [ ] 未运行的测试必须记录原因。

### 6. 更新协作资产

实现完成后必须同步更新：

- [ ] `SPEC.md`：Feature 状态更新为 `Done`（或 `In Progress` 如果仍有遗留）。
- [ ] `rules/*.mdc`：如果实现过程中发现新踩坑，提炼为规则。
- [ ] `skills/*.md`：如果操作步骤值得复用，新建或更新 Skill。
- [ ] `records/`：写一份复盘记录（按 `records/README.md` 模板）。

### 7. 交付检查

按 `SPEC.md` §8 交付前检查清单逐项确认。

## 常见错误

- 写完代码才补 SPEC → 规格变成"事后解释"，失去约束力。
- 跳过后端校验直接改前端 → 数据可能非法写入 DB。
- 新 content type 忘了更新 `ContentRenderer` → 前端白屏。
- Adapter 里直接读环境变量 → 违反 R-A-6。
- AI 擅自扩展范围加 UI → 违反 R-C-7。

## PR 自检

- [ ] SPEC Feature 状态已更新。
- [ ] 相关 rules 未被违反，新规则已沉淀。
- [ ] 相关 skill 已更新或新建。
- [ ] records 复盘已写入。
- [ ] 后端/前端测试已运行，失败项有说明。
- [ ] 手动 smoke 已走通或已说明不可运行原因。
