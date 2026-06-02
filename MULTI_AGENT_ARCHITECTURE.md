# Cowork Forge 多 Agent 协作架构详解

> 本文档基于源码深度分析，详细说明 Cowork Forge 如何通过多 Agent 协作完成从需求到交付的全流程软件开发。

---

## 一、整体架构：4 层解耦设计

```
┌─────────────────────────────────────────────────────────────┐
│                    交互适配层 (Interaction)                    │
│         CLI (clap+dialoguer)  │  Tauri GUI (React)          │
├─────────────────────────────────────────────────────────────┤
│                   流程编排层 (Pipeline)                       │
│   IterationExecutor → 7 Stage → StageExecutor → ADK Agent   │
├─────────────────────────────────────────────────────────────┤
│              配置驱动层 (config_definition)                   │
│   Registry + Agent/Stage/Flow Definition + AgentFactory     │
├─────────────────────────────────────────────────────────────┤
│              工具 & 指令 & 持久化 & LLM 基础设施层              │
│   40+ Tools │ 12 Instructions │ JSON Persistence │ LLM       │
└─────────────────────────────────────────────────────────────┘
```

核心入口文件：[lib.rs](crates/cowork-core/src/lib.rs)，它把所有模块组合起来。

---

## 二、Agent 定义方式：配置驱动 + JSON 声明 + 内置指令

每个 Agent 不是硬编码的类，而是通过 **JSON 配置声明** 描述其身份、能力、工具和指令。由 [AgentDefinition](crates/cowork-core/src/config_definition/agent_definition.rs#L70-L100) 数据结构承载：

```rust
pub struct AgentDefinition {
    pub id: String,           // 唯一标识，如 "coding_actor"
    pub name: String,         // 人类可读名称
    pub instruction: String,  // 指令来源："builtin://coding_actor"
    pub tools: Vec<ToolReference>,  // 分配的工具列表
    pub model: ModelConfig,   // 温度等模型参数
    // ...
}
```

以 **Coding Actor** 为例，JSON 配置 [coding_actor.json](crates/cowork-core/src/config_definition/default_configs/agents/built-in/coding_actor.json)：

```json
{
  "id": "coding_actor",
  "name": "Coding Actor",
  "instruction": "builtin://coding_actor",
  "tools": [
    { "tool_id": "get_implementation_plan" },
    { "tool_id": "read_file" },
    { "tool_id": "write_file" },
    { "tool_id": "list_files" },
    { "tool_id": "run_command" },
    { "tool_id": "goto_stage" },
    { "tool_id": "query_memory" },
    { "tool_id": "save_insight" },
    { "tool_id": "save_issue" },
    { "tool_id": "save_learning" }
  ],
  "model": { "temperature": 0.7 }
}
```

**Coding Critic** 的配置 [coding_critic.json](crates/cowork-core/src/config_definition/default_configs/agents/built-in/coding_critic.json) 则不同：

```json
{
  "id": "coding_critic",
  "name": "Coding Critic",
  "instruction": "builtin://coding_critic",
  "tools": [
    { "tool_id": "check_tests" },
    { "tool_id": "check_lint" },
    { "tool_id": "provide_feedback" },
    { "tool_id": "save_issue" }
  ],
  "model": { "temperature": 0.3 }    // 更低温度=更严格审查
}
```

所有内置 Agent 配置在启动时通过 [builtin.rs](crates/cowork-core/src/config_definition/builtin.rs#L17-L98) 从 `default_configs/` 目录加载到全局 Registry，同时支持用户自定义配置覆盖。

### Agent 完整列表

| Agent ID | 名称 | 温度 | 类型 | 关键工具 |
|----------|------|:---:|:----:|---------|
| `idea_agent` | Idea Agent | 0.7 | Simple | `save_idea` |
| `prd_actor` | PRD Actor | 0.7 | Actor | `create_requirement`, `add_feature`, `save_prd_doc` |
| `prd_critic` | PRD Critic | 0.3 | Critic | `check_feature_coverage`, `provide_feedback` |
| `design_actor` | Design Actor | 0.7 | Actor | `create_design_component`, `save_design_doc` |
| `design_critic` | Design Critic | 0.3 | Critic | `check_data_format`, `provide_feedback` |
| `plan_actor` | Plan Actor | 0.7 | Actor | `create_task`, `save_plan_doc` |
| `plan_critic` | Plan Critic | 0.3 | Critic | `check_task_dependencies`, `provide_feedback` |
| `coding_actor` | Coding Actor | 0.7 | Actor | `read_file`, `write_file`, `run_command`, `goto_stage` |
| `coding_critic` | Coding Critic | 0.3 | Critic | `check_tests`, `check_lint`, `provide_feedback` |
| `check_agent` | Check Agent | 0.3 | Simple | `run_command`, `check_tests`, `check_lint`, `goto_stage` |
| `delivery_agent` | Delivery Agent | 0.5 | Simple | `copy_workspace_to_project`, `save_delivery_report` |
| `knowledge_gen_agent` | Knowledge Gen Agent | 0.5 | Simple | `save_insight`, `promote_to_decision` |
| `pm_agent` | Project Manager Agent | 0.7 | Simple | `pm_goto_stage`, `pm_create_iteration`, `query_memory` |
| `summary_agent` | Summary Agent | - | Simple | 用于文档摘要生成 |

---

## 三、7 阶段流水线：Flow → Stage → Agent 的三级级联

### 3.1 Flow 定义流程顺序

[default.json](crates/cowork-core/src/config_definition/default_configs/flows/default.json) 定义了标准的 7 阶段顺序：

```json
{
  "id": "default",
  "stages": [
    { "stage_id": "idea",      "on_success": "prd" },
    { "stage_id": "prd",       "on_success": "design" },
    { "stage_id": "design",    "on_success": "plan" },
    { "stage_id": "plan",      "on_success": "coding" },
    { "stage_id": "coding",    "on_success": "check" },
    { "stage_id": "check",     "on_success": "delivery" },
    { "stage_id": "delivery" }
  ],
  "start_stage": "idea",
  "config": {
    "stop_on_failure": true,
    "inheritance": { "default_mode": "partial" }
  }
}
```

### 3.2 StageDefinition 决定执行方式

[StageDefinition](crates/cowork-core/src/config_definition/stage_definition.rs#L85-L140) 有两种类型：

| 类型 | 说明 | 代表阶段 |
|------|------|---------|
| `Simple` | 单个 Agent，执行一次 | idea, check, delivery |
| `ActorCritic` | Actor + Critic 循环 | prd, design, plan, coding |

例如 [prd.json](crates/cowork-core/src/config_definition/default_configs/stages/prd.json#L1-L31)：

```json
{
  "id": "prd",
  "stage_type": "actor_critic",
  "actor_critic": {
    "actor": "prd_actor",
    "critic": "prd_critic",
    "max_iterations": 1
  },
  "needs_confirmation": true
}
```

Idea 阶段是 Simple 型 [idea.json](crates/cowork-core/src/config_definition/default_configs/stages/idea.json)：

```json
{
  "id": "idea",
  "stage_type": "simple",
  "agent": "idea_agent",
  "needs_confirmation": true
}
```

### 3.3 AgentFactory 动态创建 Agent 实例

[agent_factory.rs](crates/cowork-core/src/config_definition/agent_factory.rs#L243-L285) 中的 `create_loop_agent_from_config()` 是 Actor-Critic 的核心工厂：

```rust
pub fn create_loop_agent_from_config(...) -> Result<Arc<dyn Agent>> {
    // 1. 从 registry 获取 actor 和 critic 的定义
    let actor_def = registry.get_agent(&actor_critic.actor)?;
    let critic_def = registry.get_agent(&actor_critic.critic)?;

    // 2. 分别创建 actor 和 critic agent 实例
    let actor = create_simple_agent_from_config_with_stage(&actor_def, ...)?;
    let critic = create_simple_agent_from_config_with_stage(&critic_def, ...)?;

    // 3. 用 LoopAgent 包装成循环 agent
    let mut loop_agent = LoopAgent::new(
        &stage_definition.id,
        vec![actor, critic],     // actor 先执行，critic 后执行
    );
    loop_agent = loop_agent.with_max_iterations(max_iterations);  // 设为 1
    Ok(Arc::new(loop_agent))
}
```

[create_agent_for_stage()](crates/cowork-core/src/config_definition/agent_factory.rs#L470-L488) 是统一的入口函数，根据 stage type 分发：

```rust
pub fn create_agent_for_stage(stage_id, model, iteration_id) -> Result<Arc<dyn Agent>> {
    let stage = registry.get_stage(stage_id)?;
    match &stage.stage_type {
        StageType::Simple => create_agent_from_config(...),          // 单个 agent
        StageType::ActorCritic => create_loop_agent_from_config(...), // Actor+Critic 循环
    }
}
```

---

## 四、Actor-Critic 循环机制：PRD / Design / Plan / Coding 四阶段的质量保障

### 4.1 底层实现：adk-rust 的 LoopAgent

Actor-Critic 并非项目自己实现的循环逻辑，而是利用 **adk-rust** 框架的 `LoopAgent`：

```
LoopAgent("prd_loop", [prd_actor, prd_critic], max_iterations=1)
   ↓
   Actor 执行 → 生成内容 → Critic 审查 → 通过则结束，不通过则 Actor 重新生成
```

`max_iterations=1` 是设计决策：Actor 生成一次，Critic 审查一次即结束，避免无限循环导致的过度优化和 token 浪费。

### 4.2 四个阶段的 Actor-Critic 配对

| 阶段 | Actor（温度 0.7，创造） | Critic（温度 0.3，审查） | 核心产出物 |
|------|-----------------------|------------------------|-----------|
| **PRD** | prd_actor：全面生成需求文档 | prd_critic：检查覆盖度、合理性 | prd.md, requirements.json |
| **Design** | design_actor：创建设计架构 | design_critic：审查技术选型合理性 | design.md, design_spec.json |
| **Plan** | plan_actor：任务拆解和排期 | plan_critic：检查依赖完整性 | plan.md, implementation_plan.json |
| **Coding** | coding_actor：编写代码并执行 | coding_critic：检查编译、测试和 lint | 源代码文件 |

### 4.3 StageExecutor：Agent 与流水线的桥梁

[stage_executor.rs](crates/cowork-core/src/pipeline/stage_executor.rs#L83-L158) 中的 `execute_stage_with_instruction()` 是实际驱动 Agent 运行的函数：

```rust
pub async fn execute_stage_with_instruction(ctx, interaction, stage_name, instruction, feedback) {
    // 1. 创建 LLM 客户端
    let model = create_llm_client(&llm_config.llm)?;

    // 2. 通过配置系统创建 agent（可能是 Actor-Critic LoopAgent）
    let agent = create_agent_for_stage(stage_name, model, ctx.iteration.id)?;

    // 3. 构建 prompt（注入前序阶段的 artifact、迭代目标等上下文）
    let prompt = build_prompt(ctx, stage_name, feedback);

    // 4. 执行 agent，获取流式输出
    let stream = agent.run(invocation_ctx).await?;

    // 5. 处理流式输出 → 实时展示给用户
    while let Some(result) = stream.next().await {
        // 提取文本/工具调用
    }

    // 6. 如果 agent 没有调用 save 工具，则发送后续消息触发保存
}
```

关键设计：Agent 的输出不是简单的文本响应，而是通过**工具调用**（如 `save_prd_doc`、`save_design_doc`）来保存产出物。如果 Agent 忘记调用 save 工具，StageExecutor 会发送后续消息提醒保存。

### 4.4 内置指令系统

每个 Agent 的行为由位于 [instructions/](crates/cowork-core/src/instructions/) 目录下的 Prompt 指令定义：

| 指令文件 | 对应 Agent | 行数 |
|----------|-----------|:----:|
| [idea.rs](crates/cowork-core/src/instructions/idea.rs) | Idea Agent | ~100 |
| [prd.rs](crates/cowork-core/src/instructions/prd.rs) | PRD Actor / Critic | ~200+ |
| [design.rs](crates/cowork-core/src/instructions/design.rs) | Design Actor / Critic | ~200+ |
| [plan.rs](crates/cowork-core/src/instructions/plan.rs) | Plan Actor / Critic | ~200+ |
| [coding.rs](crates/cowork-core/src/instructions/coding.rs) | Coding Actor / Critic | ~400+ |
| [check.rs](crates/cowork-core/src/instructions/check.rs) | Check Agent | ~150 |
| [delivery.rs](crates/cowork-core/src/instructions/delivery.rs) | Delivery Agent | ~100 |
| [knowledge_gen.rs](crates/cowork-core/src/instructions/knowledge_gen.rs) | Knowledge Gen Agent | ~300 |
| [project_manager.rs](crates/cowork-core/src/instructions/project_manager.rs) | PM Agent | ~200 |
| [legacy_project_analyzer.rs](crates/cowork-core/src/instructions/legacy_project_analyzer.rs) | Legacy Analyzer | ~200 |

---

## 五、IterationExecutor：迭代生命周期管理器

[executor/mod.rs](crates/cowork-core/src/pipeline/executor/mod.rs#L20-L250) 是整个流程的总控制器。

### 5.1 执行流程

```
IterationExecutor::execute() {
    // 1. 准备 workspace（迭代工作目录）
    workspace::prepare_workspace();

    // 2. 确定起始阶段
    //    - 新迭代（Genesis）从 idea 开始
    //    - 恢复的迭代从 current_stage 开始
    //    - 演进迭代（Evolution）从继承模式决定
    let stages = get_stages_from_flow(&start_stage);

    // 3. 对 evolution 迭代，注入项目知识
    if iteration.base_iteration_id.is_some() {
        knowledge::inject_project_knowledge();
        // 加载历史决策/模式/问题到记忆
    }

    // 4. 逐个阶段执行
    for stage in stages {
        execute_stage_with_retry(stage, max_retries=3) {

            // 支持 feedback 循环（最多 5 次）
            loop (max_feedback=5) {
                let result = stage.execute(ctx);

                match result {
                    Success → if is_critical_stage {
                        // 关键阶段需要人工确认
                        request_confirmation(Pass/Edit/Feedback/Cancel)
                    }
                    GotoStage → 跳转到指定阶段重新执行
                    Failed → 重试或终止（由 stop_on_failure 控制）
                }
            }
        }
    }

    // 5. 迭代后处理
    generate_document_summaries();    // 生成文档摘要
    generate_iteration_knowledge();   // 提取项目知识
    promote_insights_to_decisions();  // 将洞察提升为决策
}
```

### 5.2 关键控制参数

| 参数 | 值 | 说明 |
|------|:---:|------|
| `MAX_STAGE_RETRIES` | 3 | 阶段失败后最多重试 3 次 |
| `RETRY_DELAY_MS` | 5000 | 重试间隔 5 秒 |
| `MAX_FEEDBACK_LOOPS` | 5 | 同一阶段用户反馈最多 5 轮 |
| `stop_on_failure` | true | 阶段失败是否终止整个迭代 |

### 5.3 HITL 确认点

`is_critical_stage()` 决定哪些阶段需要人工确认：

```rust
pub fn is_critical_stage(stage_name: &str) -> bool {
    matches!(stage_name, "idea" | "prd" | "design" | "plan" | "coding")
}
```

确认操作选项：

| 操作 | 行为 |
|------|------|
| **Continue (Pass)** | 批准当前输出，进入下一阶段 |
| **ViewArtifact** | 重新查看 artifact（不消耗 feedback 次数） |
| **ProvideFeedback** | 提供修改意见，Agent 重新生成 |
| **Cancel** | 暂停迭代 |

### 5.4 Artifact 预注入优化

在 [build_prompt](crates/cowork-core/src/pipeline/stage_executor.rs#L509-L650) 中，每个阶段的 prompt 会**预注入**前序阶段的 artifact，减少 Agent 的 tool call 开销：

| 当前阶段 | 预注入的 Artifact |
|---------|-------------------|
| prd | idea.md |
| design | prd.md |
| plan | design.md |
| coding | plan.md + design.md（精简版） |
| check / delivery | 全部 4 个文档（各 2000 字以内） |

对于 Evolution 迭代，还会注入**迭代目标**和**项目上下文记忆**，确保 Agent 理解这是增量修改而非从头开始。

---

## 六、各类 Agent 的详细实现

### 6.1 Idea Agent — 捕获并构建用户需求

| 属性 | 值 |
|------|-----|
| 类型 | `Simple`，单个 Agent |
| 配置 | [idea.json](crates/cowork-core/src/config_definition/default_configs/stages/idea.json) |
| 工具 | `save_idea`（保存 idea.md） |
| 确认 | 需要 |
| 产出 | `artifacts/idea.md` |

实现方式：使用内置指令 `IDEA_AGENT_INSTRUCTION`，通过 `LlmAgentBuilder` 创建单个 Agent，执行阶段时读取用户输入的迭代目标，生成结构化 idea 文档。

### 6.2 PRD Loop Agent — 产品需求文档生成

| 属性 | 值 |
|------|-----|
| 类型 | `ActorCritic` |
| 配置 | [prd.json](crates/cowork-core/src/config_definition/default_configs/stages/prd.json) |
| Actor | prd_actor（`save_prd_doc`, `create_requirement`, `add_feature`） |
| Critic | prd_critic（`check_feature_coverage`, `provide_feedback`） |
| 确认 | 需要 |
| 产出 | `artifacts/prd.md`, `data/requirements.json`, `data/feature_list.json` |

工作流程：
1. Actor 读取前序的 idea.md（已预注入到 prompt）
2. Actor 生成结构化需求：创建 requirement 条目和 feature 列表
3. Critic 审查覆盖度，检查是否有缺失的功能或模糊的需求
4. 如果 Critic 发现问题→通过 `provide_feedback` 让 Actor 修正
5. 最终保存 prd.md 文档

### 6.3 Design Loop Agent — 技术架构设计

| 属性 | 值 |
|------|-----|
| 类型 | `ActorCritic` |
| 配置 | [design.json](crates/cowork-core/src/config_definition/default_configs/stages/design.json) |
| Actor | design_actor（`create_design_component`, `save_design_doc`） |
| Critic | design_critic（`check_data_format`, `provide_feedback`） |
| 确认 | 需要 |
| 产出 | `artifacts/design.md`, `data/design_spec.json` |

工作流程：
1. Actor 读取前序的 prd.md（已预注入）
2. Actor 设计技术架构：模块划分、组件设计、数据流
3. Critic 审查架构合理性、数据格式正确性
4. 如果发现问题→反馈给 Actor 修正
5. 最终保存 design.md 文档

### 6.4 Plan Loop Agent — 实施计划拆分

| 属性 | 值 |
|------|-----|
| 类型 | `ActorCritic` |
| 配置 | [plan.json](crates/cowork-core/src/config_definition/default_configs/stages/plan.json) |
| Actor | plan_actor（`create_task`, `get_design`, `save_plan_doc`） |
| Critic | plan_critic（`check_task_dependencies`, `provide_feedback`） |
| 确认 | 需要 |
| 产出 | `artifacts/plan.md`, `data/implementation_plan.json` |

工作流程：
1. Actor 读取 design.md（已预注入）
2. Actor 将设计拆解为具体任务，标注依赖和优先级
3. Critic 审查任务之间的依赖关系是否完整
4. 输出包含里程碑和任务列表的 plan.md

### 6.5 Coding Loop Agent — 代码实现

| 属性 | 值 |
|------|-----|
| 类型 | `ActorCritic` |
| 配置 | [coding.json](crates/cowork-core/src/config_definition/default_configs/stages/coding.json) |
| Actor | coding_actor（`read_file`, `write_file`, `run_command`, `list_files`） |
| Critic | coding_critic（`check_tests`, `check_lint`, `provide_feedback`） |
| 确认 | 需要 |
| 产出 | `workspace/` 目录下的源代码文件 |

核心特点：
- Actor 拥有完整的文件读写和命令执行权限
- 执行过程中自动更新 task 状态（`update_task_status`）
- Critic 运行测试和 lint 来验证代码质量
- 支持增量修改（Evolution 迭代会注入"不要重写"的上下文）

### 6.6 Check Agent — 代码质量验证

| 属性 | 值 |
|------|-----|
| 类型 | `Simple` |
| 配置 | [check.json](crates/cowork-core/src/config_definition/default_configs/stages/check.json) |
| 工具 | `run_command`, `check_tests`, `check_lint`, `check_data_format`, `goto_stage` |
| 确认 | 不需要（自动） |
| 产出 | `artifacts/check_report.md` |

关键能力：当发现严重问题时，通过 **`goto_stage`** 工具**跳回之前的阶段**重新执行。

[goto_stage_tool.rs](crates/cowork-core/src/tools/goto_stage_tool.rs#L82-L98) 通过抛出特殊错误 `GOTO_STAGE:target:reason` 来触发阶段跳转，在 [stage_executor.rs](crates/cowork-core/src/pipeline/stage_executor.rs#L175-L192) 中被捕获处理：

```rust
// 工具执行时抛出：
Err(adk_core::AdkError::tool(format!("GOTO_STAGE:{}:{}", stage_str, reason)))

// 执行器捕获并处理：
if err_msg.starts_with("GOTO_STAGE:") {
    let parts = err_msg.strip_prefix("GOTO_STAGE:").unwrap().splitn(2, ':');
    return StageResult::GotoStage(target_stage, reason);
}
```

跳转目标限制：`prd, design, plan, coding`（不能跳转到 idea 或 check/delivery）。

### 6.7 Delivery Agent — 生成交付报告

| 属性 | 值 |
|------|-----|
| 类型 | `Simple` |
| 配置 | [delivery.json](crates/cowork-core/src/config_definition/default_configs/stages/delivery.json) |
| Agent 配置 | [delivery_agent.json](crates/cowork-core/src/config_definition/default_configs/agents/built-in/delivery_agent.json) |
| 工具 | `copy_workspace_to_project`, `read_file`, `list_files`, `save_delivery_report`, `query_memory` |
| 确认 | 不需要 |
| 产出 | `artifacts/delivery_report.md` |

工作流程：
1. 读取所有阶段产生的 artifact（预注入 idea/prd/design/plan）
2. 将 workspace 中的代码复制到项目目录
3. 生成综合交付报告，包含项目概览、功能列表、技术栈和部署说明

### 6.8 Knowledge Generation Agent — 知识提取与总结

| 属性 | 值 |
|------|-----|
| 类型 | `Simple` |
| 配置 | [knowledge_gen_agent.json](crates/cowork-core/src/config_definition/default_configs/agents/built-in/knowledge_gen_agent.json) |
| 温度 | 0.5 |
| 工具 | `read_file`, `list_files`, `save_insight`, `promote_to_decision`, `promote_to_pattern` |
| 执行时机 | 迭代完成后自动调用 |

指令参考：[knowledge_gen.rs](crates/cowork-core/src/instructions/knowledge_gen.rs#L1-L80)，其工作方式是：

1. **读取**已完成迭代的所有 artifact（idea/prd/design/plan）
2. **分析**代码结构（通过 `list_files` 和 `read_file`）
3. **提取**：
   - 技术栈信息
   - 关键架构决策
   - 设计模式
   - 已知问题或限制
4. **存储**：通过 `save_insight` / `promote_to_decision` / `promote_to_pattern` 存入项目记忆

执行入口在 [knowledge.rs](crates/cowork-core/src/pipeline/executor/knowledge.rs#L1-L100) 中，迭代完成后由 `generate_document_summaries()` 和 `generate_iteration_knowledge()` 驱动。

### 6.9 PM Agent — 交付后项目管理

PM Agent **不是流水线阶段**，而是在**迭代完成后**持续活跃的对话 Agent。

| 属性 | 值 |
|------|-----|
| 创建函数 | [create_project_manager_agent()](crates/cowork-core/src/agents/mod.rs#L548-L573) |
| 配置 | [pm_agent.json](crates/cowork-core/src/config_definition/default_configs/agents/built-in/pm_agent.json) |
| 专有工具 | [pm_tools.rs](crates/cowork-core/src/tools/pm_tools.rs) |

**可用工具：**

| 工具 | 功能 |
|------|------|
| `pm_goto_stage` | 跳转到之前的任意阶段（idea/prd/design/plan/coding） |
| `pm_create_iteration` | 创建新的演进迭代（支持 none/full/partial 继承） |
| `pm_respond` | 回复用户的一般性问题 |
| `pm_save_decision` | 保存项目决策到记忆 |
| `query_memory` | 查询项目记忆获取上下文 |

**意图识别逻辑**（来自 [project_manager.rs](crates/cowork-core/src/instructions/project_manager.rs#L1-L80)）：

| 意图 | 触发词 | 操作 |
|------|--------|------|
| `bug_fix` | bug, 错误, 异常, 崩溃, 不工作 | → 跳转到 coding |
| `requirement_change` | 修改, 调整, 改成, 换成 | → 跳转到 design 或 prd |
| `new_feature` | 添加, 新增, 新功能, 再加上 | → 创建新迭代 |
| `consultation` | 怎么, 如何, 为什么, 帮我看看 | → 直接回复 |
| `ambiguous` | 意图不明确 | → 询问澄清 |

**执行示例：**

```
迭代完成 → PM Agent 启用
  ↓
用户: "修复登录 bug"
  → PM Agent 识别为 bug_fix
  → 调用 pm_goto_stage("coding", "修复登录功能bug")
  → 流水线从 coding 阶段重启

用户: "添加支付功能"
  → PM Agent 识别为 new_feature
  → 调用 pm_create_iteration("添加支付功能", ...)
  → 创建新迭代，保留现有代码（partial 继承）
```

### 6.10 Legacy Project Analyzer — 逆向工程分析

用于将**任意现有项目**导入 Cowork Forge 工作流。

| 属性 | 值 |
|------|-----|
| 实现 | [agents/legacy_project_analyzer.rs](crates/cowork-core/src/agents/legacy_project_analyzer.rs) |
| 工具 | `ScanProjectTool`, `DetectTechStackTool`, `ReadProjectFileTool`, `ListProjectDirectoryTool`, `SaveArtifactTool` |
| 产出 | idea.md, prd.md, design.md, plan.md |

提供三种构造方式：
- `create_legacy_project_analyzer()` — 基础版本
- `create_legacy_project_analyzer_with_id()` — 带迭代 ID 上下文
- `create_legacy_project_analyzer_with_context()` — 带项目路径和选项的完整版本

工作流程：
1. 扫描项目目录结构
2. 检测技术栈（Cargo.toml, package.json, requirements.txt 等）
3. 读取 README 和文档
4. AI 综合生成 4 份文档

### 6.11 External Coding Agent — 外部编码 Agent 适配器

通过 ACP（Agent Client Protocol）支持接入外部编码工具。

| 属性 | 值 |
|------|-----|
| 实现 | [agents/external_coding_agent.rs](crates/cowork-core/src/agents/external_coding_agent.rs) |
| ACP 客户端 | [acp/client.rs](crates/cowork-core/src/acp/client.rs) |
| 支持协议 | stdio（子进程）或 WebSocket 连接 |

支持的 Agent 类型：OpenCode、Claude Code、Gemini CLI、Codex 等实现了 ACP 协议的工具。

消息传递：通过 `mpsc::unbounded_channel` 实时流式传输到 GUI。在非 `Send` 的 Future 环境下，使用独立线程 + `LocalSet` 运行。

### 6.12 Change Triage Agent 和 Code Patch Agent

这两个 Agent 在 README 中被提及，但在当前源码中**尚未实现为独立的 Agent 类或 JSON 配置**。它们更像是**概念上的能力描述**：

- **Change Triage（变更分流）**：通过 PM Agent 的意图识别逻辑（`bug_fix` / `requirement_change` / `new_feature`）和 `goto_stage` 工具间接实现
- **Code Patch（代码补丁）**：通过 PM Agent 创建新迭代 + Partial 继承模式 + Coding Actor 增量修改来实现精确修补，而非从头重写

---

## 七、工具权限最小化原则

每个 Agent 只分配到完成其职责所需的**最小工具集**。这是项目的核心安全设计：

| Agent | 文件读取 | 文件写入 | 命令执行 | 记忆访问 | 阶段跳转 | MCP 扩展 |
|-------|:-------:|:-------:|:-------:|:-------:|:-------:|:-------:|
| idea_agent | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| prd_actor | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| prd_critic | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| design_actor | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| design_critic | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| plan_actor | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| plan_critic | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| coding_actor | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| coding_critic | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ |
| check_agent | ✅ | ❌ | ✅ | ❌ | ✅ | ✅ |
| delivery_agent | ✅ | ❌ | ❌ | ✅ | ❌ | ✅ |
| knowledge_gen_agent | ✅ | ❌ | ❌ | ✅ | ❌ | ✅ |
| pm_agent | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ |

这种设计确保了安全性：**只有 coding_actor 拥有文件写入和执行命令的全部权限**，其他 Agent 只能读取不能修改。

---

## 八、完整的数据流与协作图

```
用户输入
    │
    ▼
┌────────────────────────────────────────────────────────────────┐
│ IDEA AGENT (Simple)                                            │
│  读取迭代目标 → 生成 idea.md → 用户确认                         │
└──────────┬─────────────────────────────────────────────────────┘
           │ idea.md (预注入到 PRD prompt)
           ▼
┌────────────────────────────────────────────────────────────────┐
│ PRD LOOP (Actor → Critic)                                     │
│  【Actor】prd_actor: 创建需求条目和功能列表 → save_prd_doc     │
│  【Critic】prd_critic: 检查覆盖度 → provide_feedback           │
│  【HITL】用户确认 prd.md                                       │
└──────────┬─────────────────────────────────────────────────────┘
           │ prd.md (预注入到 Design prompt)
           ▼
┌────────────────────────────────────────────────────────────────┐
│ DESIGN LOOP (Actor → Critic)                                  │
│  【Actor】design_actor: 设计技术架构 → save_design_doc         │
│  【Critic】design_critic: 审查数据格式 → provide_feedback       │
│  【HITL】用户确认 design.md                                    │
└──────────┬─────────────────────────────────────────────────────┘
           │ design.md (预注入到 Plan prompt)
           ▼
┌────────────────────────────────────────────────────────────────┐
│ PLAN LOOP (Actor → Critic)                                    │
│  【Actor】plan_actor: 拆解任务清单 → save_plan_doc             │
│  【Critic】plan_critic: 检查依赖完整性 → provide_feedback       │
│  【HITL】用户确认 plan.md                                      │
└──────────┬─────────────────────────────────────────────────────┘
           │ plan.md + design.md (预注入到 Coding prompt)
           ▼
┌────────────────────────────────────────────────────────────────┐
│ CODING LOOP (Actor → Critic)                                  │
│  【Actor】coding_actor: 写文件、执行命令 → 实现功能             │
│  【Critic】coding_critic: 运行测试、检查 lint → 反馈           │
│  【HITL】用户确认代码                                         │
└──────────┬─────────────────────────────────────────────────────┘
           │ 源代码文件
           ▼
┌────────────────────────────────────────────────────────────────┐
│ CHECK AGENT (Simple)                                          │
│  运行构建、测试、lint → 验证完整性                              │
│  发现问题 → goto_stage(prd/design/plan/coding) ← 回跳          │
└──────────┬─────────────────────────────────────────────────────┘
           │ check_report.md
           ▼
┌────────────────────────────────────────────────────────────────┐
│ DELIVERY AGENT (Simple)                                       │
│  复制代码 → 生成交付报告 → 保存记忆                             │
└──────────┬─────────────────────────────────────────────────────┘
           │ delivery_report.md
           ▼
┌────────────────────────────────────────────────────────────────┐
│ KNOWLEDGE GENERATION AGENT (Simple)                           │
│  读取所有文档和代码 → 提取洞察/决策/模式 → 存储到项目记忆       │
└──────────┬─────────────────────────────────────────────────────┘
           │ 记忆 (insights + decisions + patterns)
           ▼
┌────────────────────────────────────────────────────────────────┐
│ PM AGENT (持续对话)                                            │
│  ← → 用户对话                                                 │
│  goto_stage: 跳回编码修复 bug                                   │
│  create_iteration: 创建新功能迭代                               │
│  respond: 直接回答架构/部署问题                                 │
└────────────────────────────────────────────────────────────────┘
```

---

## 九、关键设计亮点总结

1. **配置驱动而非硬编码**：所有 Agent、Stage、Flow 都通过 JSON 定义，用户可扩展自定义 Agent 和流程，无需修改 Rust 代码
2. **Actor-Critic 保持质量底线**：四个核心阶段都经过 Critic 审查，`max_iterations=1` 防止过度优化和 token 浪费
3. **HITL 把关关键决策**：5 个关键阶段（idea/prd/design/plan/coding）都需要人工确认，确保方向正确
4. **Artifact 传递链**：前序输出自动作为后序上下文注入，减少 tool call 开销，降低 token 消耗
5. **权限最小化**：只有 coding_actor 能写文件和执行命令，其他 Agent 只能读取，确保系统安全
6. **记忆系统**：通过 `save_insight` / `promote_to_decision` / `promote_to_pattern` 在迭代间传递知识，支持 Evolution 迭代的增量演进
7. **ACP 扩展性**：通过 Agent Client Protocol 可接入外部编码工具（Claude Code、Gemini CLI 等）替换内置 Agent
8. **演进迭代的智能上下文**：Evolution 迭代会注入"不要重写"的严格指令和项目上下文，确保增量修改而非从头生成
9. **GotoStage 回跳机制**：Check Agent 发现质量问题时可以自动跳回之前的阶段，PM Agent 也能手动触发回跳
10. **技能系统（Skills）**：通过 `.agents/skills/` 目录支持 agentskills.io 标准的技能注入，Agent 在创建时根据标签匹配技能

---

## 附录：关键源码文件索引

| 模块 | 文件 | 说明 |
|------|------|------|
| 核心入口 | [lib.rs](crates/cowork-core/src/lib.rs) | 模块组织与重新导出 |
| 流程编排 | [pipeline/mod.rs](crates/cowork-core/src/pipeline/mod.rs) | Stage trait, StageResult, 阶段工厂 |
| 阶段执行器 | [pipeline/stage_executor.rs](crates/cowork-core/src/pipeline/stage_executor.rs) | Agent 创建、执行、artifact 保存 |
| 迭代执行器 | [pipeline/executor/mod.rs](crates/cowork-core/src/pipeline/executor/mod.rs) | 迭代生命周期管理 |
| 知识生成 | [pipeline/executor/knowledge.rs](crates/cowork-core/src/pipeline/executor/knowledge.rs) | 文档摘要和知识提取 |
| Agent 工厂 | [config_definition/agent_factory.rs](crates/cowork-core/src/config_definition/agent_factory.rs) | 配置驱动的 Agent 创建 |
| Agent 定义 | [config_definition/agent_definition.rs](crates/cowork-core/src/config_definition/agent_definition.rs) | AgentDefinition 数据结构 |
| Stage 定义 | [config_definition/stage_definition.rs](crates/cowork-core/src/config_definition/stage_definition.rs) | StageDefinition 数据结构 |
| Flow 定义 | [config_definition/flow_definition.rs](crates/cowork-core/src/config_definition/flow_definition.rs) | 流程定义 |
| 内置配置 | [config_definition/builtin.rs](crates/cowork-core/src/config_definition/builtin.rs) | 嵌入式默认配置加载 |
| 配置注册表 | [config_definition/registry.rs](crates/cowork-core/src/config_definition/registry.rs) | 全局配置注册中心 |
| PM Agent 创建 | [agents/mod.rs](crates/cowork-core/src/agents/mod.rs#L548) | create_project_manager_agent |
| 遗留项目分析 | [agents/legacy_project_analyzer.rs](crates/cowork-core/src/agents/legacy_project_analyzer.rs) | 逆向工程分析 Agent |
| 外部编码 Agent | [agents/external_coding_agent.rs](crates/cowork-core/src/agents/external_coding_agent.rs) | ACP 编码 Agent 适配器 |
| ACP 客户端 | [acp/client.rs](crates/cowork-core/src/acp/client.rs) | Agent Client Protocol |
| PM 工具 | [tools/pm_tools.rs](crates/cowork-core/src/tools/pm_tools.rs) | pm_goto_stage, pm_create_iteration 等 |
| GotoStage 工具 | [tools/goto_stage_tool.rs](crates/cowork-core/src/tools/goto_stage_tool.rs) | 阶段跳转 |
| 指令库 | [instructions/](crates/cowork-core/src/instructions/) | 所有 Agent 的 Prompt 指令 |
| 工具库 | [tools/](crates/cowork-core/src/tools/) | 40+ 工具实现 |
| 记忆持久化 | [persistence/memory_store.rs](crates/cowork-core/src/persistence/memory_store.rs) | 项目记忆存储 |
| 交互抽象 | [interaction/](crates/cowork-core/src/interaction/) | CLI / Tauri 适配器 |
| 技能系统 | [skills/](crates/cowork-core/src/skills/) | agentskills.io 标准 |
| 默认 Flow | [default_configs/flows/default.json](crates/cowork-core/src/config_definition/default_configs/flows/default.json) | 7 阶段流程定义 |
| 默认 Agent 配置 | [default_configs/agents/built-in/](crates/cowork-core/src/config_definition/default_configs/agents/built-in/) | 13 个内置 Agent 配置 |
| 默认 Stage 配置 | [default_configs/stages/](crates/cowork-core/src/config_definition/default_configs/stages/) | 7 个阶段配置 |
