"""
团队协作增强模块

解决现实团队中常见的协作问题：
1. 信息不同步 - 实时状态广播
2. 接口变更不通知 - 变更通知机制
3. 进度不透明 - 进度看板
4. 依赖阻塞 - 依赖追踪和提醒
5. 代码冲突 - 文件锁定机制
6. 质量问题 - 代码审查流程
7. 集成问题 - 集成检查点
"""

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set
from enum import Enum


# ============================================================
# 1. 实时状态广播 - 解决"信息不同步"
# ============================================================

class BroadcastType(Enum):
    """广播类型"""
    PROGRESS = "progress"           # 进度更新
    INTERFACE_CHANGE = "interface"  # 接口变更
    FILE_LOCK = "file_lock"         # 文件锁定
    BLOCKED = "blocked"             # 被阻塞
    COMPLETED = "completed"         # 完成通知
    NEED_HELP = "need_help"         # 需要帮助


@dataclass
class Broadcast:
    """广播消息"""
    type: BroadcastType
    from_agent: str
    task_id: str
    content: Dict[str, Any]
    timestamp: int = 0
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = int(time.time() * 1000)


class StatusBroadcaster:
    """
    状态广播器
    
    当一个 Agent 有重要变更时，自动通知其他相关 Agent
    """
    
    def __init__(self, send_fn: Optional[Callable] = None):
        self.send_fn = send_fn
        self.broadcasts: List[Broadcast] = []
        self.subscribers: Dict[str, Set[str]] = {}  # task_id -> agents
    
    def subscribe(self, task_id: str, agent: str) -> None:
        """订阅任务的广播"""
        if task_id not in self.subscribers:
            self.subscribers[task_id] = set()
        self.subscribers[task_id].add(agent)
    
    def broadcast(self, broadcast: Broadcast) -> List[str]:
        """
        广播消息给相关 Agent
        
        Returns:
            List[str]: 接收到广播的 Agent 列表
        """
        self.broadcasts.append(broadcast)
        
        # 找到所有订阅者
        subscribers = self.subscribers.get(broadcast.task_id, set())
        # 排除发送者自己
        recipients = [a for a in subscribers if a != broadcast.from_agent]
        
        # 发送广播
        if self.send_fn and recipients:
            for agent in recipients:
                self._send_broadcast(broadcast, agent)
        
        return recipients
    
    def _send_broadcast(self, broadcast: Broadcast, to_agent: str) -> None:
        """发送广播消息"""
        message = {
            "type": "send",
            "action": "broadcast",
            "from": broadcast.from_agent,
            "to": [to_agent],
            "task_id": broadcast.task_id,
            "body": json.dumps({
                "broadcast_type": broadcast.type.value,
                "content": broadcast.content,
            }, ensure_ascii=False),
        }
        if self.send_fn:
            self.send_fn(message)
    
    def broadcast_progress(
        self,
        from_agent: str,
        task_id: str,
        progress: int,
        status: str,
        details: str = "",
    ) -> List[str]:
        """广播进度更新"""
        return self.broadcast(Broadcast(
            type=BroadcastType.PROGRESS,
            from_agent=from_agent,
            task_id=task_id,
            content={
                "progress": progress,
                "status": status,
                "details": details,
            },
        ))
    
    def broadcast_interface_change(
        self,
        from_agent: str,
        task_id: str,
        change_type: str,  # add, modify, remove
        interface_name: str,
        old_value: Optional[str] = None,
        new_value: Optional[str] = None,
        reason: str = "",
    ) -> List[str]:
        """
        广播接口变更
        
        关键！当 A 改了接口，B/C/D 必须知道！
        """
        return self.broadcast(Broadcast(
            type=BroadcastType.INTERFACE_CHANGE,
            from_agent=from_agent,
            task_id=task_id,
            content={
                "change_type": change_type,
                "interface_name": interface_name,
                "old_value": old_value,
                "new_value": new_value,
                "reason": reason,
            },
        ))


# ============================================================
# 2. 进度看板 - 解决"不知道别人进度"
# ============================================================

@dataclass
class AgentProgress:
    """Agent 进度"""
    agent: str
    task_id: str
    subtask_id: str
    status: str  # pending, in_progress, blocked, completed, failed
    progress: int  # 0-100
    current_step: str
    started_at: int
    updated_at: int
    blocked_by: Optional[str] = None
    blocked_reason: Optional[str] = None


class ProgressBoard:
    """
    进度看板
    
    让每个 Agent 都能看到其他人的进度
    """
    
    def __init__(self):
        self.progress: Dict[str, AgentProgress] = {}  # agent -> progress
        self.history: List[Dict[str, Any]] = []
    
    def update(
        self,
        agent: str,
        task_id: str,
        subtask_id: str,
        status: str,
        progress: int,
        current_step: str,
        blocked_by: Optional[str] = None,
        blocked_reason: Optional[str] = None,
    ) -> AgentProgress:
        """更新进度"""
        now = int(time.time() * 1000)
        
        existing = self.progress.get(agent)
        if existing and existing.task_id == task_id:
            started_at = existing.started_at
        else:
            started_at = now
        
        agent_progress = AgentProgress(
            agent=agent,
            task_id=task_id,
            subtask_id=subtask_id,
            status=status,
            progress=progress,
            current_step=current_step,
            started_at=started_at,
            updated_at=now,
            blocked_by=blocked_by,
            blocked_reason=blocked_reason,
        )
        
        self.progress[agent] = agent_progress
        self.history.append({
            "agent": agent,
            "task_id": task_id,
            "status": status,
            "progress": progress,
            "timestamp": now,
        })
        
        return agent_progress
    
    def get_board(self, task_id: Optional[str] = None) -> Dict[str, AgentProgress]:
        """获取进度看板"""
        if task_id:
            return {
                a: p for a, p in self.progress.items()
                if p.task_id == task_id
            }
        return dict(self.progress)
    
    def get_blocked_agents(self) -> List[AgentProgress]:
        """获取被阻塞的 Agent"""
        return [p for p in self.progress.values() if p.status == "blocked"]
    
    def format_board(self, task_id: Optional[str] = None) -> str:
        """格式化进度看板为可读文本"""
        board = self.get_board(task_id)
        if not board:
            return "暂无进度数据"
        
        lines = [
            "┌─────────────────────────────────────────────────────┐",
            "│                    进度看板                          │",
            "├─────────┬──────────┬──────────┬─────────────────────┤",
            "│  Agent  │   状态   │   进度   │      当前步骤        │",
            "├─────────┼──────────┼──────────┼─────────────────────┤",
        ]
        
        status_icons = {
            "pending": "⏳",
            "in_progress": "🔄",
            "blocked": "🚫",
            "completed": "✅",
            "failed": "❌",
        }
        
        for agent, p in sorted(board.items()):
            icon = status_icons.get(p.status, "❓")
            progress_bar = "█" * (p.progress // 10) + "░" * (10 - p.progress // 10)
            step = p.current_step[:18] if len(p.current_step) > 18 else p.current_step.ljust(18)
            lines.append(f"│ {agent:^7} │ {icon:^8} │{progress_bar}│ {step} │")
            
            if p.blocked_by:
                lines.append(f"│         │ 阻塞于: {p.blocked_by}, {p.blocked_reason or ''} │")
        
        lines.append("└─────────┴──────────┴──────────┴─────────────────────┘")
        return "\n".join(lines)


# ============================================================
# 3. 文件锁定 - 解决"代码冲突"
# ============================================================

@dataclass
class FileLock:
    """文件锁"""
    file_path: str
    locked_by: str
    task_id: str
    locked_at: int
    reason: str
    expires_at: Optional[int] = None


class FileLockManager:
    """
    文件锁管理器
    
    防止多个 Agent 同时修改同一文件
    """
    
    def __init__(self, default_lock_duration_ms: int = 3600000):  # 默认 1 小时
        self.locks: Dict[str, FileLock] = {}  # file_path -> lock
        self.default_duration = default_lock_duration_ms
    
    def try_lock(
        self,
        file_path: str,
        agent: str,
        task_id: str,
        reason: str = "",
        duration_ms: Optional[int] = None,
    ) -> tuple:
        """
        尝试锁定文件
        
        Returns:
            (success: bool, lock_or_error: FileLock | str)
        """
        now = int(time.time() * 1000)
        
        # 检查是否已被锁定
        existing = self.locks.get(file_path)
        if existing:
            # 检查是否过期
            if existing.expires_at and now > existing.expires_at:
                # 锁已过期，可以重新锁定
                del self.locks[file_path]
            elif existing.locked_by != agent:
                # 被其他人锁定
                return False, f"文件被 {existing.locked_by} 锁定，原因: {existing.reason}"
        
        # 创建新锁
        duration = duration_ms or self.default_duration
        lock = FileLock(
            file_path=file_path,
            locked_by=agent,
            task_id=task_id,
            locked_at=now,
            reason=reason,
            expires_at=now + duration,
        )
        self.locks[file_path] = lock
        return True, lock
    
    def unlock(self, file_path: str, agent: str) -> bool:
        """解锁文件"""
        lock = self.locks.get(file_path)
        if not lock:
            return True
        if lock.locked_by != agent:
            return False
        del self.locks[file_path]
        return True
    
    def check_conflicts(self, files: List[str], agent: str) -> List[Dict[str, Any]]:
        """
        检查文件冲突
        
        在开始任务前检查，避免后期冲突
        """
        conflicts = []
        for file_path in files:
            lock = self.locks.get(file_path)
            if lock and lock.locked_by != agent:
                # 检查是否过期
                now = int(time.time() * 1000)
                if not lock.expires_at or now <= lock.expires_at:
                    conflicts.append({
                        "file": file_path,
                        "locked_by": lock.locked_by,
                        "reason": lock.reason,
                        "locked_at": lock.locked_at,
                    })
        return conflicts
    
    def get_agent_locks(self, agent: str) -> List[FileLock]:
        """获取某个 Agent 的所有锁"""
        return [l for l in self.locks.values() if l.locked_by == agent]


# ============================================================
# 4. 依赖追踪 - 解决"依赖阻塞"
# ============================================================

@dataclass
class Dependency:
    """依赖关系"""
    from_task: str
    to_task: str
    from_agent: str
    to_agent: str
    type: str  # data, api, component
    status: str  # waiting, ready, failed
    description: str


class DependencyTracker:
    """
    依赖追踪器
    
    追踪任务间的依赖关系，及时提醒
    """
    
    def __init__(self):
        self.dependencies: List[Dependency] = []
        self.completed_tasks: Set[str] = set()
    
    def add_dependency(
        self,
        from_task: str,
        to_task: str,
        from_agent: str,
        to_agent: str,
        dep_type: str,
        description: str,
    ) -> Dependency:
        """添加依赖"""
        dep = Dependency(
            from_task=from_task,
            to_task=to_task,
            from_agent=from_agent,
            to_agent=to_agent,
            type=dep_type,
            status="waiting",
            description=description,
        )
        self.dependencies.append(dep)
        return dep
    
    def mark_completed(self, task_id: str) -> List[Dependency]:
        """
        标记任务完成，返回解除阻塞的依赖
        """
        self.completed_tasks.add(task_id)
        
        unblocked = []
        for dep in self.dependencies:
            if dep.to_task == task_id and dep.status == "waiting":
                dep.status = "ready"
                unblocked.append(dep)
        
        return unblocked
    
    def get_blocked_tasks(self, agent: str) -> List[Dependency]:
        """获取某 Agent 被阻塞的任务"""
        return [
            d for d in self.dependencies
            if d.from_agent == agent and d.status == "waiting"
        ]
    
    def get_blocking_tasks(self, agent: str) -> List[Dependency]:
        """获取某 Agent 阻塞其他人的任务"""
        return [
            d for d in self.dependencies
            if d.to_agent == agent and d.status == "waiting"
        ]
    
    def format_dependencies(self) -> str:
        """格式化依赖关系图"""
        if not self.dependencies:
            return "暂无依赖关系"
        
        lines = ["依赖关系:"]
        for dep in self.dependencies:
            status_icon = {"waiting": "⏳", "ready": "✅", "failed": "❌"}.get(dep.status, "❓")
            lines.append(
                f"  {dep.from_task}({dep.from_agent}) "
                f"--[{dep.type}]--> "
                f"{dep.to_task}({dep.to_agent}) {status_icon}"
            )
        return "\n".join(lines)


# ============================================================
# 5. 代码审查 - 解决"质量问题"
# ============================================================

@dataclass
class ReviewRequest:
    """审查请求"""
    id: str
    task_id: str
    from_agent: str
    reviewer: str
    files: List[str]
    changes_summary: str
    created_at: int
    status: str  # pending, approved, rejected, needs_changes
    comments: List[Dict[str, Any]] = field(default_factory=list)


class CodeReviewManager:
    """
    代码审查管理器
    
    确保代码质量，在合并前进行审查
    """
    
    def __init__(self):
        self.reviews: Dict[str, ReviewRequest] = {}
        self._review_counter = 0
    
    def request_review(
        self,
        task_id: str,
        from_agent: str,
        reviewer: str,
        files: List[str],
        changes_summary: str,
    ) -> ReviewRequest:
        """请求代码审查"""
        self._review_counter += 1
        review_id = f"REVIEW-{self._review_counter:04d}"
        
        review = ReviewRequest(
            id=review_id,
            task_id=task_id,
            from_agent=from_agent,
            reviewer=reviewer,
            files=files,
            changes_summary=changes_summary,
            created_at=int(time.time() * 1000),
            status="pending",
        )
        self.reviews[review_id] = review
        return review
    
    def approve(self, review_id: str, comment: str = "") -> bool:
        """批准审查"""
        review = self.reviews.get(review_id)
        if not review:
            return False
        review.status = "approved"
        if comment:
            review.comments.append({
                "type": "approve",
                "comment": comment,
                "timestamp": int(time.time() * 1000),
            })
        return True
    
    def reject(self, review_id: str, reason: str, suggestions: List[str] = None) -> bool:
        """拒绝审查"""
        review = self.reviews.get(review_id)
        if not review:
            return False
        review.status = "needs_changes"
        review.comments.append({
            "type": "reject",
            "reason": reason,
            "suggestions": suggestions or [],
            "timestamp": int(time.time() * 1000),
        })
        return True
    
    def get_pending_reviews(self, reviewer: str = None) -> List[ReviewRequest]:
        """获取待审查的请求"""
        pending = [r for r in self.reviews.values() if r.status == "pending"]
        if reviewer:
            pending = [r for r in pending if r.reviewer == reviewer]
        return pending


# ============================================================
# 6. 集成检查点 - 解决"集成问题"
# ============================================================

@dataclass
class IntegrationCheckpoint:
    """集成检查点"""
    id: str
    task_id: str
    name: str
    description: str
    participants: List[str]  # 参与的 Agent
    checks: List[Dict[str, Any]]  # 检查项
    status: str  # pending, passed, failed
    results: Dict[str, Any] = field(default_factory=dict)


class IntegrationChecker:
    """
    集成检查器
    
    在关键节点进行集成检查，确保各部分能对接
    """
    
    def __init__(self):
        self.checkpoints: Dict[str, IntegrationCheckpoint] = {}
        self._checkpoint_counter = 0
    
    def create_checkpoint(
        self,
        task_id: str,
        name: str,
        description: str,
        participants: List[str],
        checks: List[Dict[str, Any]],
    ) -> IntegrationCheckpoint:
        """创建集成检查点"""
        self._checkpoint_counter += 1
        cp_id = f"CP-{self._checkpoint_counter:04d}"
        
        checkpoint = IntegrationCheckpoint(
            id=cp_id,
            task_id=task_id,
            name=name,
            description=description,
            participants=participants,
            checks=checks,
            status="pending",
        )
        self.checkpoints[cp_id] = checkpoint
        return checkpoint
    
    def run_checks(self, checkpoint_id: str) -> Dict[str, Any]:
        """
        运行集成检查
        
        检查项示例：
        - API 接口是否匹配
        - 数据模型字段是否一致
        - 组件 props 是否正确
        """
        checkpoint = self.checkpoints.get(checkpoint_id)
        if not checkpoint:
            return {"error": "Checkpoint not found"}
        
        results = {
            "checkpoint_id": checkpoint_id,
            "checks": [],
            "passed": 0,
            "failed": 0,
        }
        
        for check in checkpoint.checks:
            # 这里应该实际执行检查，现在只是模拟
            check_result = {
                "name": check.get("name"),
                "type": check.get("type"),
                "status": "passed",  # 实际应该执行检查
                "message": "",
            }
            results["checks"].append(check_result)
            if check_result["status"] == "passed":
                results["passed"] += 1
            else:
                results["failed"] += 1
        
        checkpoint.status = "passed" if results["failed"] == 0 else "failed"
        checkpoint.results = results
        
        return results
    
    def generate_integration_checks(
        self,
        contract: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        根据契约生成集成检查项
        """
        checks = []
        
        # API 检查
        for endpoint in contract.get("endpoints", []):
            checks.append({
                "name": f"API: {endpoint.get('method')} {endpoint.get('path')}",
                "type": "api",
                "check": "response_schema_match",
                "expected": endpoint.get("response"),
            })
        
        # 数据模型检查
        for model in contract.get("models", []):
            checks.append({
                "name": f"Model: {model.get('name')}",
                "type": "model",
                "check": "fields_match",
                "expected_fields": [f.get("name") for f in model.get("fields", [])],
            })
        
        # 组件检查
        for component in contract.get("components", []):
            checks.append({
                "name": f"Component: {component.get('name')}",
                "type": "component",
                "check": "props_match",
                "expected_props": component.get("props", []),
            })
        
        return checks


# ============================================================
# 7. 协作中心 - 整合所有协作功能
# ============================================================

class CollaborationHub:
    """
    协作中心
    
    整合所有协作功能，提供统一入口
    """
    
    def __init__(self, send_fn: Optional[Callable] = None):
        self.broadcaster = StatusBroadcaster(send_fn)
        self.progress_board = ProgressBoard()
        self.file_lock_manager = FileLockManager()
        self.dependency_tracker = DependencyTracker()
        self.code_review_manager = CodeReviewManager()
        self.integration_checker = IntegrationChecker()
    
    def setup_task(
        self,
        task_id: str,
        participants: List[str],
        dependencies: List[Dict[str, Any]] = None,
        files_to_lock: Dict[str, List[str]] = None,
    ) -> Dict[str, Any]:
        """
        设置任务的协作环境
        
        在任务开始前调用，确保：
        1. 所有参与者订阅广播
        2. 依赖关系已建立
        3. 文件已锁定
        """
        result = {
            "task_id": task_id,
            "subscribed": [],
            "dependencies": [],
            "file_locks": [],
            "conflicts": [],
        }
        
        # 1. 订阅广播
        for agent in participants:
            self.broadcaster.subscribe(task_id, agent)
            result["subscribed"].append(agent)
        
        # 2. 建立依赖关系
        if dependencies:
            for dep in dependencies:
                d = self.dependency_tracker.add_dependency(
                    from_task=dep["from_task"],
                    to_task=dep["to_task"],
                    from_agent=dep["from_agent"],
                    to_agent=dep["to_agent"],
                    dep_type=dep.get("type", "data"),
                    description=dep.get("description", ""),
                )
                result["dependencies"].append({
                    "from": d.from_task,
                    "to": d.to_task,
                    "status": d.status,
                })
        
        # 3. 锁定文件
        if files_to_lock:
            for agent, files in files_to_lock.items():
                for file_path in files:
                    success, lock_or_error = self.file_lock_manager.try_lock(
                        file_path=file_path,
                        agent=agent,
                        task_id=task_id,
                        reason=f"Task {task_id}",
                    )
                    if success:
                        result["file_locks"].append({
                            "file": file_path,
                            "locked_by": agent,
                        })
                    else:
                        result["conflicts"].append({
                            "file": file_path,
                            "agent": agent,
                            "error": lock_or_error,
                        })
        
        return result
    
    def report_progress(
        self,
        agent: str,
        task_id: str,
        subtask_id: str,
        progress: int,
        status: str,
        current_step: str,
    ) -> None:
        """报告进度（会自动广播）"""
        # 更新进度看板
        self.progress_board.update(
            agent=agent,
            task_id=task_id,
            subtask_id=subtask_id,
            status=status,
            progress=progress,
            current_step=current_step,
        )
        
        # 广播进度
        self.broadcaster.broadcast_progress(
            from_agent=agent,
            task_id=task_id,
            progress=progress,
            status=status,
            details=current_step,
        )
    
    def notify_interface_change(
        self,
        agent: str,
        task_id: str,
        change_type: str,
        interface_name: str,
        old_value: str = None,
        new_value: str = None,
        reason: str = "",
    ) -> None:
        """
        通知接口变更
        
        关键！A 改了接口必须通知 B/C/D
        """
        self.broadcaster.broadcast_interface_change(
            from_agent=agent,
            task_id=task_id,
            change_type=change_type,
            interface_name=interface_name,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
        )
    
    def complete_task(self, agent: str, task_id: str) -> Dict[str, Any]:
        """
        完成任务
        
        1. 解锁文件
        2. 更新依赖状态
        3. 广播完成
        """
        result = {"task_id": task_id, "agent": agent}
        
        # 解锁该 Agent 的所有文件
        locks = self.file_lock_manager.get_agent_locks(agent)
        for lock in locks:
            if lock.task_id == task_id:
                self.file_lock_manager.unlock(lock.file_path, agent)
        
        # 更新依赖
        unblocked = self.dependency_tracker.mark_completed(task_id)
        result["unblocked_dependencies"] = [
            {"from": d.from_task, "from_agent": d.from_agent}
            for d in unblocked
        ]
        
        # 更新进度
        self.progress_board.update(
            agent=agent,
            task_id=task_id,
            subtask_id=task_id,
            status="completed",
            progress=100,
            current_step="已完成",
        )
        
        # 广播完成
        self.broadcaster.broadcast(Broadcast(
            type=BroadcastType.COMPLETED,
            from_agent=agent,
            task_id=task_id,
            content={"status": "completed"},
        ))
        
        return result
    
    def get_status_report(self, task_id: str) -> str:
        """获取任务状态报告"""
        lines = [
            f"# 任务状态报告: {task_id}",
            "",
            "## 进度看板",
            self.progress_board.format_board(task_id),
            "",
            "## 依赖关系",
            self.dependency_tracker.format_dependencies(),
            "",
        ]
        
        # 阻塞情况
        blocked = self.progress_board.get_blocked_agents()
        if blocked:
            lines.append("## ⚠️ 阻塞情况")
            for b in blocked:
                lines.append(f"- {b.agent} 被阻塞: {b.blocked_reason}")
            lines.append("")
        
        # 待审查
        pending_reviews = self.code_review_manager.get_pending_reviews()
        if pending_reviews:
            lines.append("## 📝 待审查")
            for r in pending_reviews:
                lines.append(f"- {r.id}: {r.from_agent} 请求 {r.reviewer} 审查")
            lines.append("")
        
        return "\n".join(lines)


# ============================================================
# 快捷函数
# ============================================================

def create_collaboration_hub(send_fn: Optional[Callable] = None) -> CollaborationHub:
    """创建协作中心"""
    return CollaborationHub(send_fn)
