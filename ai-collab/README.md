# `ai-collab/` — AgentHub v2 的 AI 协作规范沉淀

这个目录是 **课题评分中 30% 权重** 的核心交付物：把"如何与 AI 一起开发 AgentHub v2"这件事，沉淀为可以复用、可以验收、可以转交的工程资产。

## 目录约定

```
ai-collab/
├── README.md         # 本文：使用指南
├── SPEC.md           # 产品规格（EARS / Given-When-Then）—— 描述"做什么"
├── skills/           # 可复用 SOP —— 描述"怎么做某一类任务"
│   ├── new-adapter.md
│   ├── new-message-type.md
│   └── debug-ws-flow.md
├── rules/            # 硬约束 —— 描述"不能怎么做"
│   ├── backend.mdc
│   ├── frontend.mdc
│   └── adapter.mdc
└── records/          # 真实开发对话存档 —— 描述"实际怎么做的"
    └── 20260521-W1.md
```

## 阅读顺序建议

1. **第一次理解项目** → 先看 `SPEC.md`，对齐"已交付能力 + 验收标准"
2. **接手新功能** → 在 `skills/` 找匹配的 SOP，按步骤走
3. **改代码前** → 读对应 `rules/*.mdc`，避免反复返工
4. **回顾决策** → 翻 `records/` 里对应日期的复盘

## 与外部资产的关系

| 资产 | 落点 | 作用 |
|---|---|---|
| 架构设计 | `docs/ARCHITECTURE.md` | 长寿命的技术决策 |
| 课题方案 | `COURSE_PROPOSAL.md` | 4 周路线图与评分映射 |
| Cursor Rules | `.cursor/rules/*.mdc` ⇆ `ai-collab/rules/*.mdc` | 同源文件，前者是 Cursor 自动加载，后者是审稿可见 |
| 真实 Prompt 截图 | `records/*.md` 的"现场片段" | 评委关心的"真实痕迹" |

## 维护节奏

- **每天**：在 `records/YYYYMMDD-话题.md` 里记 1-2 段真实开发对话与决策点。
- **每周**：W1/W2/W3/W4 结束时各产出一份 `records/YYYYMMDD-Wx.md` 复盘。
- **每个新功能**：先更新 `SPEC.md`，再写代码。
- **每个 Adapter / 消息类型**：先按 `skills/new-*.md` 走，写完回填脚注。
