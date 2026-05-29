"""
智能任务调度器

负责任务的完整调度流程：复杂度判断 -> 任务分解 -> Agent分配 -> 并行执行 -> 结果聚合
"""

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from .complexity import ComplexityJudge, ComplexityResult, TaskInput
from .decomposer import DecomposeResult, SubTask, TaskDecomposer
from .enhanced_decomposer import EnhancedTaskDecomposer, EnhancedDecomposeResult
from .collaboration import CollaborationHub, create_collaboration_hub
from .agents import (
    SPECIALIZED_AGENTS,
    match_agent_for_task,
    match_agents_for_domains,
    format_agent_assignment_summary,
)


@dataclass
class Assignment:
    """任务分配"""
    agent: str  # A, B, C, D
    subtask: SubTask
    task_id: str = ""
    status: str = "pending"  # pending, sent, done, failed


@dataclass
class ScheduleResult:
    """调度结果"""
    mode: str  # "single" | "parallel"
    task_id: str
    complexity: ComplexityResult
    assignments: List[Assignment] = field(default_factory=list)
    decompose_result: Optional[DecomposeResult] = None
    summary: str = ""


class TaskScheduler:
    """智能任务调度器"""

    def __init__(
        self,
        router_client: Optional[Any] = None,
        complexity_judge: Optional[ComplexityJudge] = None,
        decomposer: Optional[TaskDecomposer] = None,
        use_contracts: bool = True,
        collaboration_hub: Optional[CollaborationHub] = None,
    ):
        """
        初始化调度器

        Args:
            router_client: Router客户端（用于发送消息）
            complexity_judge: 复杂度判断器
            decomposer: 任务分解器
            use_contracts: 是否使用契约优先设计（推荐开启）
            collaboration_hub: 协作中心（进度、锁、广播等）
        """
        self.client = router_client
        self.complexity_judge = complexity_judge or ComplexityJudge()
        self.use_contracts = use_contracts
        
        # 使用增强版分解器（带契约）
        if use_contracts:
            self.decomposer = decomposer or EnhancedTaskDecomposer()
            self.enhanced_decomposer = self.decomposer
        else:
            self.decomposer = decomposer or TaskDecomposer()
            self.enhanced_decomposer = None
        
        # 协作中心
        send_fn = router_client.send_message if router_client else None
        self.collaboration = collaboration_hub or create_collaboration_hub(send_fn)
        
        self._task_counter = 0

    def schedule(self, task: TaskInput) -> ScheduleResult:
        """
        调度任务

        完整流程：
        1. 判断任务复杂度
        2. 简单任务 -> 单Agent模式
        3. 复杂任务 -> 分解 + 多Agent并行

        Args:
            task: 任务输入

        Returns:
            ScheduleResult: 调度结果
        """
        # 1. 判断复杂度
        complexity = self.complexity_judge.judge(task)

        # 生成主任务ID
        task_id = self._generate_task_id("SCHED")

        # 2. 根据复杂度选择执行模式
        if complexity.level == "simple":
            return self._schedule_single(task, task_id, complexity)
        else:
            return self._schedule_parallel(task, task_id, complexity)

    def _schedule_single(
        self,
        task: TaskInput,
        task_id: str,
        complexity: ComplexityResult,
    ) -> ScheduleResult:
        """单Agent模式调度"""
        # 选择一个Agent处理
        domain = list(complexity.domains)[0] if complexity.domains else "backend"
        agent = self._select_agent_for_domain(domain)

        # 创建单一任务分配
        subtask = SubTask(
            id=f"{task_id}-SINGLE",
            domain=domain,
            description=task.description,
            files=task.files,
            success_criteria=["任务完成"],
        )

        assignment = Assignment(
            agent=agent,
            subtask=subtask,
            task_id=f"{task_id}-{agent}",
        )

        summary = self._format_single_summary(task, assignment, complexity)

        return ScheduleResult(
            mode="single",
            task_id=task_id,
            complexity=complexity,
            assignments=[assignment],
            summary=summary,
        )

    def _schedule_parallel(
        self,
        task: TaskInput,
        task_id: str,
        complexity: ComplexityResult,
    ) -> ScheduleResult:
        """多Agent并行调度"""
        # 1. 分解任务（使用契约版或普通版）
        if self.use_contracts and self.enhanced_decomposer:
            # 使用契约优先的分解器
            decompose_result = self.enhanced_decomposer.decompose_with_contract(
                task=task,
                domains=complexity.domains,
                parent_task_id=task_id,
            )
        else:
            decompose_result = self.decomposer.decompose(
                task=task,
                domains=complexity.domains,
                parent_task_id=task_id,
            )

        # 2. 为每个子任务分配Agent
        domain_assignments = match_agents_for_domains(complexity.domains)
        assignments = []
        participants = []
        files_to_lock = {}

        for subtask in decompose_result.subtasks:
            agent = domain_assignments.get(subtask.domain)
            if not agent:
                agent = match_agent_for_task(subtask)

            assignment = Assignment(
                agent=agent,
                subtask=subtask,
                task_id=subtask.id,
            )
            assignments.append(assignment)
            participants.append(agent)
            
            # 收集需要锁定的文件
            if subtask.files:
                if agent not in files_to_lock:
                    files_to_lock[agent] = []
                files_to_lock[agent].extend(subtask.files)

        # 3. 设置协作环境（订阅广播、建立依赖、锁定文件）
        dependencies = []
        for subtask in decompose_result.subtasks:
            for dep_id in subtask.dependencies:
                # 找到依赖的子任务
                for other in decompose_result.subtasks:
                    if other.id == dep_id:
                        from_agent = domain_assignments.get(subtask.domain, "B")
                        to_agent = domain_assignments.get(other.domain, "B")
                        dependencies.append({
                            "from_task": subtask.id,
                            "to_task": other.id,
                            "from_agent": from_agent,
                            "to_agent": to_agent,
                            "type": "data",
                            "description": f"{subtask.domain} depends on {other.domain}",
                        })
        
        collab_setup = self.collaboration.setup_task(
            task_id=task_id,
            participants=list(set(participants)),
            dependencies=dependencies,
            files_to_lock=files_to_lock,
        )

        # 4. 生成摘要
        summary = self._format_parallel_summary(
            task, assignments, decompose_result, complexity
        )
        
        # 添加协作信息到摘要
        if collab_setup.get("conflicts"):
            summary += "\n\n⚠️ 文件冲突警告:\n"
            for conflict in collab_setup["conflicts"]:
                summary += f"  - {conflict['file']}: {conflict['error']}\n"

        return ScheduleResult(
            mode="parallel",
            task_id=task_id,
            complexity=complexity,
            assignments=assignments,
            decompose_result=decompose_result,
            summary=summary,
        )

    def execute(
        self,
        schedule_result: ScheduleResult,
        send_message: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """
        执行调度结果

        Args:
            schedule_result: 调度结果
            send_message: 发送消息的函数

        Returns:
            Dict: 执行结果
        """
        if not send_message and self.client:
            send_message = self.client.send_message

        if not send_message:
            return {
                "status": "dry_run",
                "message": "No message sender configured",
                "schedule": self._schedule_to_dict(schedule_result),
            }

        sent_tasks = []
        errors = []

        for assignment in schedule_result.assignments:
            try:
                # 构建分配消息
                message = self._build_assign_message(assignment, schedule_result)
                result = send_message(message)
                assignment.status = "sent"
                sent_tasks.append({
                    "task_id": assignment.task_id,
                    "agent": assignment.agent,
                    "message_id": result.get("id"),
                })
            except Exception as e:
                assignment.status = "failed"
                errors.append({
                    "task_id": assignment.task_id,
                    "agent": assignment.agent,
                    "error": str(e),
                })

        return {
            "status": "executed" if not errors else "partial",
            "mode": schedule_result.mode,
            "task_id": schedule_result.task_id,
            "sent_count": len(sent_tasks),
            "error_count": len(errors),
            "sent_tasks": sent_tasks,
            "errors": errors,
        }

    def _build_assign_message(
        self,
        assignment: Assignment,
        schedule_result: ScheduleResult,
    ) -> Dict[str, Any]:
        """构建分配消息"""
        subtask = assignment.subtask

        # 构建消息体
        body = {
            "task_type": subtask.domain,
            "files": subtask.files,
            "success_criteria": subtask.success_criteria,
            "dependencies": subtask.dependencies,
            "description": subtask.description,
        }
        
        # 如果是增强版子任务，注入契约信息（关键！）
        if hasattr(subtask, 'contract_section') and subtask.contract_section:
            body["contract_section"] = subtask.contract_section
        if hasattr(subtask, 'shared_models') and subtask.shared_models:
            body["shared_models"] = subtask.shared_models
        if hasattr(subtask, 'provided_interfaces') and subtask.provided_interfaces:
            body["provided_interfaces"] = subtask.provided_interfaces
        if hasattr(subtask, 'required_interfaces') and subtask.required_interfaces:
            body["required_interfaces"] = subtask.required_interfaces
        
        # 注入完整契约文档
        if schedule_result.decompose_result:
            if hasattr(schedule_result.decompose_result, 'contract_document'):
                body["contract_document"] = schedule_result.decompose_result.contract_document

        # 设置deadline（默认1小时）
        deadline = int(time.time() * 1000) + 3600 * 1000

        return {
            "type": "ask",
            "action": "assign",
            "to": [assignment.agent],
            "task_id": assignment.task_id,
            "owner": "MAIN",
            "deadline": deadline,
            "body": json.dumps(body, ensure_ascii=False),
            "body_encoding": "json",
        }

    def _select_agent_for_domain(self, domain: str) -> str:
        """为领域选择Agent"""
        domain_map = {
            "frontend": "A",
            "backend": "B",
            "database": "C",
            "test": "D",
            "docs": "D",
            "devops": "D",
        }
        return domain_map.get(domain, "B")

    def _generate_task_id(self, prefix: str) -> str:
        """生成任务ID"""
        self._task_counter += 1
        ts = time.strftime("%Y%m%d-%H%M%S")
        return f"{prefix}-{ts}-{self._task_counter:03d}"

    def _format_single_summary(
        self,
        task: TaskInput,
        assignment: Assignment,
        complexity: ComplexityResult,
    ) -> str:
        """格式化单Agent模式摘要"""
        profile = SPECIALIZED_AGENTS.get(assignment.agent)
        agent_name = profile.name if profile else assignment.agent

        lines = [
            "=== 任务调度结果 ===",
            f"模式: 单Agent模式（简单任务）",
            f"任务ID: {assignment.task_id}",
            f"复杂度: {complexity.level} (分数: {complexity.score:.2f})",
            f"判断理由: {', '.join(complexity.reasons[:3])}",
            "",
            f"分配给: {agent_name}",
            f"任务描述: {task.description[:100]}...",
        ]
        return "\n".join(lines)

    def _format_parallel_summary(
        self,
        task: TaskInput,
        assignments: List[Assignment],
        decompose_result: DecomposeResult,
        complexity: ComplexityResult,
    ) -> str:
        """格式化多Agent并行模式摘要"""
        lines = [
            "=== 任务调度结果 ===",
            f"模式: 多Agent并行模式（复杂任务）",
            f"主任务ID: {decompose_result.parent_task_id}",
            f"复杂度: {complexity.level} (分数: {complexity.score:.2f})",
            f"判断理由: {', '.join(complexity.reasons[:3])}",
            f"涉及领域: {', '.join(complexity.domains)}",
            "",
            f"分解为 {len(assignments)} 个子任务:",
        ]

        for assignment in assignments:
            profile = SPECIALIZED_AGENTS.get(assignment.agent)
            agent_name = profile.name if profile else assignment.agent
            lines.append(
                f"  - {assignment.subtask.id}: "
                f"{assignment.subtask.domain} -> {agent_name}"
            )

        lines.append("")
        lines.append("执行顺序:")
        for i, layer in enumerate(decompose_result.execution_order):
            if len(layer) > 1:
                lines.append(f"  阶段{i+1}（并行）: {', '.join(layer)}")
            else:
                lines.append(f"  阶段{i+1}: {', '.join(layer)}")

        return "\n".join(lines)

    def _schedule_to_dict(self, result: ScheduleResult) -> Dict[str, Any]:
        """将调度结果转换为字典"""
        return {
            "mode": result.mode,
            "task_id": result.task_id,
            "complexity": {
                "level": result.complexity.level,
                "score": result.complexity.score,
                "reasons": result.complexity.reasons,
                "domains": list(result.complexity.domains),
            },
            "assignments": [
                {
                    "agent": a.agent,
                    "task_id": a.task_id,
                    "domain": a.subtask.domain,
                    "description": a.subtask.description,
                    "files": a.subtask.files,
                    "status": a.status,
                }
                for a in result.assignments
            ],
        }


def create_scheduler(router_client: Optional[Any] = None) -> TaskScheduler:
    """
    创建调度器实例

    Args:
        router_client: Router客户端

    Returns:
        TaskScheduler: 调度器实例
    """
    return TaskScheduler(router_client=router_client)


def schedule_task(
    description: str,
    files: Optional[List[str]] = None,
    context: Optional[str] = None,
    router_client: Optional[Any] = None,
) -> ScheduleResult:
    """
    快捷函数：调度任务

    Args:
        description: 任务描述
        files: 涉及的文件
        context: 上下文

    Returns:
        ScheduleResult: 调度结果

    Example:
        >>> result = schedule_task("修复登录按钮样式")
        >>> print(result.mode)  # "single"

        >>> result = schedule_task(
        ...     "实现用户登录功能，包括前端表单、后端API、数据库模型"
        ... )
        >>> print(result.mode)  # "parallel"
    """
    task = TaskInput(
        description=description,
        files=files or [],
        context=context,
    )
    scheduler = TaskScheduler(router_client=router_client)
    return scheduler.schedule(task)
