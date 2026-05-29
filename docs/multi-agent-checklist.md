# 多代理系统完整检查清单

## 1. 启动流程检查 ✅

```bash
# 启动完整团队
team start --workspace /path/to/project

# 验证：
# ✅ Router 服务启动
# ✅ MAIN + A/B/C/D 窗口打开
# ✅ 各 Agent 注册 presence
```

## 2. 需求到实现完整流程

### 阶段 1: 需求分析 ✅
```bash
# 已有项目加功能 - 先分析
team analyze --path . --feature "添加用户评论功能"

# 输出：
# - 项目结构
# - 影响范围
# - 风险评估
```

### 阶段 2: 设计 ✅
```bash
# 生成设计文档
team design --requirement "用户评论功能" --existing

# 输出：
# - 需求列表
# - 架构设计
# - 数据模型
# - API 接口
# - UI 页面
# - 待确认问题
```

### 阶段 3: 用户确认 ⚠️
**人工检查**：审阅设计文档，确认需求对齐

### 阶段 4: 任务调度 ✅
```bash
# 智能调度（自动生成契约）
team run --task "用户评论功能" --design-approved --dry-run

# 输出：
# - 复杂度判断
# - 任务分解
# - Agent 分配
# - 接口契约
# - 执行顺序
```

### 阶段 5: 协作执行 ✅
```bash
# 开始执行
team run --task "用户评论功能" --design-approved --wait

# 协作机制：
# - 进度广播
# - 文件锁定
# - 依赖追踪
# - 变更通知
```

## 3. 协作命令检查 ✅

### 进度看板
```bash
team board --task TASK-001

# 输出：
# ┌─────────────────────────────────────────────────────┐
# │                    进度看板                          │
# ├─────────┬──────────┬──────────┬─────────────────────┤
# │  Agent  │   状态   │   进度   │      当前步骤        │
# ├─────────┼──────────┼──────────┼─────────────────────┤
# │    A    │    🔄    │████████░░│ 登录表单组件         │
# │    B    │    🔄    │██████░░░░│ 登录 API            │
# └─────────┴──────────┴──────────┴─────────────────────┘
```

### 报告进度
```bash
team progress --task TASK-001 --percent 50 --status in_progress --step "实现登录表单"
```

### 文件锁定
```bash
# 锁定文件
team lock --files "src/api/auth.py,src/models/user.py" --task TASK-001 --reason "实现登录"

# 解锁文件
team lock --files "src/api/auth.py" --task TASK-001 --unlock
```

### 变更通知
```bash
# 通知接口变更（关键！）
team notify --task TASK-001 --interface "POST /api/login" --change-type modify \
    --old-value '{"username": "string"}' \
    --new-value '{"username": "string", "remember_me": "boolean"}' \
    --reason "新增记住密码功能"
```

## 4. 通信检查 ✅

### 消息类型
- `ask` - 提问/分配任务
- `report` - 报告反馈
- `send` - 发送回复
- `done` - 完成通知
- `fail` - 失败通知

### ACK 机制
- `delivered` - 消息已送达 inbox
- `accepted` - Agent 已读取消息

### 重试机制
- 超时自动重试
- 最大重试次数限制
- 指数退避

## 5. 防风险机制检查

| 机制 | 命令/功能 | 状态 |
|------|----------|------|
| 设计确认 | `team design` → 用户审阅 | ✅ |
| 接口契约 | `EnhancedTaskDecomposer` | ✅ |
| 进度看板 | `team board` | ✅ |
| 文件锁定 | `team lock` | ✅ |
| 变更通知 | `team notify` | ✅ |
| 依赖追踪 | `DependencyTracker` | ✅ |
| 代码审查 | `CodeReviewManager` | ✅ |
| 集成检查 | `IntegrationChecker` | ✅ |

## 6. 常见问题检查

### 问题 1: Agent 之间接口对不上
**预防措施**:
1. 使用 `team design` 生成设计文档
2. 使用契约优先分解 (`EnhancedTaskDecomposer`)
3. 使用 `team notify` 通知接口变更

### 问题 2: 代码冲突
**预防措施**:
1. 使用 `team lock` 锁定正在编辑的文件
2. 任务分解时自动锁定相关文件

### 问题 3: 进度不透明
**解决方案**:
1. 使用 `team progress` 报告进度
2. 使用 `team board` 查看看板

### 问题 4: 依赖阻塞
**解决方案**:
1. 分解时建立依赖关系
2. 依赖完成自动通知
3. 阻塞情况在看板显示

## 7. 完整流程示意图

```
用户需求
    │
    ▼
team analyze ──────────────────┐
    │                          │
    ▼                          │
team design                    │ 分析阶段
    │                          │
    ▼                          │
用户确认 ◀─────────────────────┘
    │
    ▼
team run --design-approved ────┐
    │                          │
    ├── 生成契约               │
    ├── 分解任务               │ 准备阶段
    ├── 分配 Agent             │
    └── 锁定文件               │
                               │
    ▼ ◀────────────────────────┘
各 Agent 并行执行 ─────────────┐
    │                          │
    ├── team progress 报告     │
    ├── team notify 通知变更   │ 执行阶段
    ├── team board 查看进度    │
    └── clarify/answer 沟通    │
                               │
    ▼ ◀────────────────────────┘
结果聚合 ─────────────────────┐
    │                          │
    ├── 冲突检测               │ 收尾阶段
    ├── 集成检查               │
    └── 汇总报告               │
                               │
    ▼ ◀────────────────────────┘
完成
```

## 8. 快速启动命令

```bash
# 1. 启动团队
team start --workspace .

# 2. 分析项目（可选，已有项目时）
team analyze --feature "新功能描述"

# 3. 生成设计
team design --requirement "新功能描述"

# 4. 确认后执行
team run --task "新功能描述" --design-approved --wait

# 5. 监控进度
team board
```
