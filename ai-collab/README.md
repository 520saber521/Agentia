# ai-collab：AgentHub AI 协作规范中心

本目录沉淀 AgentHub 项目中"人与 AI 如何高效协作"的可复用资产。它不是普通说明文档，而是**需求 → 规则 → 技能 → 记录**四层协作体系的统一入口。所有内容使用中文维护，除代码标识符、命令、路径、API 字段名外，不使用英文叙述。

## 快速导航（按角色）

| 我想做什么 | 从哪里开始 |
| --- | --- |
| 了解项目整体能力和验收标准 | → [SPEC.md](SPEC.md) §3 验收矩阵 |
| 接手一个具体开发任务 | → [skills/](skills/) 找对应技能，按清单执行 |
| 改代码前确认不可违反的边界 | → [rules/](rules/) 找匹配模块的规则文件 |
| 理解"为什么有这个规则" | → [records/](records/) 找对应日期的复盘记录 |
| 新增一个 Adapter | → [skills/new-adapter.md](skills/new-adapter.md) |
| 新增一种消息类型 | → [skills/new-message-type.md](skills/new-message-type.md) |
| 调试 WebSocket 消息流问题 | → [skills/ws-flow-debug.md](skills/ws-flow-debug.md) |
| 端到端交付一个新功能 | → [skills/new-feature.md](skills/new-feature.md) |
| 写一份协作复盘记录 | → [records/README.md](records/README.md) 按模板写 |
| 评审 AI 协作过程是否规范 | → 本页 §协作成熟度检查 |

## 四层协作体系

```text
SPEC.md          ← 做什么、怎样算完成（产品规格 + 验收标准）
    ↓ 驱动
rules/*.mdc      ← 哪些做法禁止出现（硬约束，从踩坑中提炼）
    ↓ 约束
skills/*.md      ← 某类任务怎么做（可复用 SOP，含步骤和自检清单）
    ↓ 执行后产出
records/*.md     ← 真实协作痕迹（决策、踩坑、复盘，保留原貌）
    ↓ 反哺
rules/*.mdc      ← 从记录中提炼长期规则，循环更新
```

## 目录结构

```text
ai-collab/
├── README.md                      # 本文：协作资产入口与维护规则
├── SPEC.md                        # 产品与协作规格：做什么、如何验收
├── rules/                         # 硬约束：AI 与开发者不能破坏的工程规则
│   ├── backend.mdc                #   后端 BFF/Gateway 规则
│   ├── frontend.mdc               #   前端 React/TS/WebSocket 规则
│   ├── adapter.mdc                #   Agent Adapter 实现规则
│   └── collaboration.mdc          #   AI 协作运行规则
├── skills/                        # 可复用 SOP：某类任务如何做
│   ├── new-feature.md             #   端到端新功能开发（元技能）
│   ├── new-adapter.md             #   新增 Agent Adapter
│   ├── new-message-type.md        #   新增消息内容类型
│   └── ws-flow-debug.md           #   调试 WebSocket 消息流
└── records/                       # 真实协作记录与复盘
    ├── README.md                  #   记录命名规范与写作模板
    ├── 20260521-W1.md             #   W1 骨架打通复盘
    ├── 20260521-D0-archive-v1.md  #   v1 终端形态归档
    ├── 20260521-W2-D1.md          #   F-W2-5 多 Agent 新建会话
    └── 20260522-W4-Diff.md        #   F-W4-5 Diff 视图与一键应用
```

## Feature → Skill → Rule 追溯

| SPEC Feature | 关键 Skill | 约束规则 |
| --- | --- | --- |
| F-1 会话与历史 | — | backend R-B-2, R-B-3; frontend R-F-3, R-F-5 |
| F-2 WebSocket 消息流 | ws-flow-debug | backend R-B-4, R-B-5; frontend R-F-1, R-F-4 |
| F-3 多 Agent Adapter | new-adapter | adapter (全部); backend R-B-9 |
| F-4 群聊 fan-out | — | backend R-B-5, R-B-9; frontend R-F-7 |
| F-5 Orchestrator 协调 | — | backend R-B-9 |
| F-6 富媒体消息 | new-message-type | backend R-B-7, R-B-8; frontend R-F-6 |
| F-7 自定义 Agent | — | backend R-B-3; frontend R-F-3 |
| F-8 Trace 执行记录 | — | backend R-B-5; collaboration R-C-5 |

## 协作成熟度检查

一次有效的 AI 协作交付至少满足：

- [ ] 需求映射到 `SPEC.md` 中的 Feature 或明确新增 Feature。
- [ ] 修改遵守相关 `rules/*.mdc` 硬约束。
- [ ] 使用或更新至少一份相关 Skill。
- [ ] 有可运行的测试或明确说明未运行原因。
- [ ] 关键决策或踩坑沉淀到 `records/` 或对应规则中。

## 文档资产职责

| 资产 | 关注点 | 更新时机 |
| --- | --- | --- |
| `SPEC.md` | 产品能力、状态、验收标准、交付边界 | 功能范围、验收口径、优先级变化时 |
| `skills/*.md` | 可执行步骤、测试口径、PR 自检 | 某类任务重复出现或踩坑后 |
| `rules/*.mdc` | 硬约束、禁用模式、代码边界 | 出现工程回归、AI 常犯错误或架构边界变化后 |
| `records/*.md` | 真实协作记录、决策、复盘 | 每个 Sprint 或关键问题结束后 |

## 维护原则

- 先更新规格，再实现功能；实现偏离规格时，优先修正文档并写明原因。
- 新增复杂能力时，必须同时补齐：`SPEC.md` 验收项、对应 Skill、必要规则、测试口径。
- 历史 `records/` 不做"美化式改写"；如需修正结论，追加新记录说明。
- 所有文档必须给出可执行动作，避免只写愿景、口号或模糊描述。
- 状态枚举统一使用：`Done`、`In Progress`、`Planned`、`Deferred`、`Dropped`。
- 同类问题第二次出现时，必须把解决步骤沉淀为 Skill 或 Rule。

## 协作反模式（AI 常见错误）

这些错误在 `records/` 中多次出现，已被对应规则禁止：

| 反模式 | 禁止规则 | 来源记录 |
| --- | --- | --- |
| Adapter 中直接读环境变量 | adapter R-A-6 | W1 复盘 |
| 用异常表达用户取消 | adapter R-A-3 | W1 复盘 |
| 在组件中直接 `fetch()` | frontend R-F-3 | W1 复盘 |
| reducer 中执行副作用 | frontend R-F-1 | W1 复盘 |
| 多协程直接抢写 WebSocket | backend R-B-4 | W1 决策 3 |
| service 层直接抛 HTTPException | backend R-B-2 | W2-D1 决策 1 |
| 为"周到"而擅自加 UI 功能 | collaboration R-C-1, R-C-2 | W2-D1 片段 3.2 |
| 把 `In Progress` 描述成已完成 | collaboration R-C-6 | — |

## 与项目其他文档的关系

| 文档 | 关系 |
| --- | --- |
| `../README.md` | 面向使用者的项目入口，描述如何启动和演示 |
| `../docs/ARCHITECTURE.md` | 技术架构与模块边界，`SPEC.md` 不重复实现细节 |
| `../server/README.md` | 后端 API、WS 事件、数据库和测试入口 |
| `../web/src/types.ts` | 前端消息、Agent、Artifact 类型的实际约束来源之一 |
