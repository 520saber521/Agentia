"""
任务分解器

将复杂任务分解为可并行执行的子任务，每个子任务分配给专用Agent。
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .complexity import TaskInput, DOMAIN_KEYWORDS


@dataclass
class SubTask:
    """子任务"""
    id: str
    domain: str  # frontend, backend, database, test, docs, devops
    description: str
    files: List[str] = field(default_factory=list)
    success_criteria: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    priority: int = 0  # 0=normal, 1=high, -1=low
    estimated_effort: str = "medium"  # low, medium, high
    hints: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DecomposeResult:
    """分解结果"""
    parent_task_id: str
    subtasks: List[SubTask]
    dependency_graph: Dict[str, List[str]]  # subtask_id -> [dependency_ids]
    execution_order: List[List[str]]  # 可并行执行的分组
    summary: str


# 领域对应的文件模式
DOMAIN_FILE_PATTERNS = {
    "frontend": [
        "src/ui/**",
        "src/components/**",
        "src/pages/**",
        "src/views/**",
        "*.tsx",
        "*.jsx",
        "*.css",
        "*.scss",
        "*.html",
    ],
    "backend": [
        "src/api/**",
        "src/router/**",
        "src/services/**",
        "src/handlers/**",
        "src/controllers/**",
        "*.py",
    ],
    "database": [
        "src/models/**",
        "src/storage/**",
        "src/repository/**",
        "migrations/**",
        "*.sql",
    ],
    "test": [
        "tests/**",
        "test/**",
        "*_test.py",
        "test_*.py",
        "*.test.ts",
        "*.spec.ts",
    ],
    "docs": [
        "docs/**",
        "*.md",
        "README*",
    ],
    "devops": [
        "Dockerfile",
        "docker-compose*.yml",
        ".github/**",
        "*.yaml",
        "*.yml",
        "scripts/**",
    ],
}

# 领域间的典型依赖关系
DOMAIN_DEPENDENCIES = {
    "frontend": ["backend"],  # 前端通常依赖后端API
    "backend": ["database"],  # 后端通常依赖数据库模型
    "test": ["frontend", "backend", "database"],  # 测试依赖其他实现
    "docs": ["frontend", "backend", "database"],  # 文档依赖实现完成
    "database": [],  # 数据库通常是基础，无依赖
    "devops": ["backend"],  # DevOps 依赖后端配置
}


class TaskDecomposer:
    """任务分解器"""

    def __init__(self):
        self._task_counter = 0

    def decompose(
        self,
        task: TaskInput,
        domains: Set[str],
        parent_task_id: Optional[str] = None,
    ) -> DecomposeResult:
        """
        分解任务为子任务

        Args:
            task: 任务输入
            domains: 任务涉及的领域
            parent_task_id: 父任务ID

        Returns:
            DecomposeResult: 分解结果
        """
        if not parent_task_id:
            parent_task_id = self._generate_task_id("TASK")

        subtasks = []
        dependency_graph = {}

        # 1. 为每个领域生成子任务
        for domain in domains:
            subtask = self._create_subtask_for_domain(
                task=task,
                domain=domain,
                parent_task_id=parent_task_id,
                all_domains=domains,
            )
            subtasks.append(subtask)

        # 2. 构建依赖图
        for subtask in subtasks:
            deps = self._resolve_dependencies(subtask, subtasks)
            dependency_graph[subtask.id] = deps
            subtask.dependencies = deps

        # 3. 计算执行顺序（拓扑排序 + 并行分组）
        execution_order = self._compute_execution_order(subtasks, dependency_graph)

        # 4. 生成摘要
        summary = self._generate_summary(task, subtasks, execution_order)

        return DecomposeResult(
            parent_task_id=parent_task_id,
            subtasks=subtasks,
            dependency_graph=dependency_graph,
            execution_order=execution_order,
            summary=summary,
        )

    def _create_subtask_for_domain(
        self,
        task: TaskInput,
        domain: str,
        parent_task_id: str,
        all_domains: Set[str],
    ) -> SubTask:
        """为特定领域创建子任务"""
        subtask_id = f"{parent_task_id}-{domain.upper()}"

        # 提取该领域相关的描述
        description = self._extract_domain_description(task.description, domain)

        # 推断文件模式
        files = self._infer_files_for_domain(task, domain)

        # 生成成功标准
        success_criteria = self._generate_success_criteria(domain, description)

        # 估算工作量
        effort = self._estimate_effort(domain, all_domains, description)

        # 计算优先级（数据库和后端通常优先）
        priority = self._compute_priority(domain)

        return SubTask(
            id=subtask_id,
            domain=domain,
            description=description,
            files=files,
            success_criteria=success_criteria,
            priority=priority,
            estimated_effort=effort,
            hints={"parent_description": task.description},
        )

    def _extract_domain_description(self, full_description: str, domain: str) -> str:
        """提取特定领域的描述"""
        domain_names = {
            "frontend": "前端",
            "backend": "后端",
            "database": "数据库",
            "test": "测试",
            "docs": "文档",
            "devops": "部署",
        }

        domain_name = domain_names.get(domain, domain)

        # 尝试从描述中提取该领域的部分
        keywords = DOMAIN_KEYWORDS.get(domain, [])
        relevant_parts = []

        sentences = re.split(r'[，。；、,;]', full_description)
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            for keyword in keywords:
                if keyword.lower() in sentence.lower():
                    relevant_parts.append(sentence)
                    break

        if relevant_parts:
            extracted = "；".join(relevant_parts)
            return f"[{domain_name}] {extracted}"

        # 如果没有找到特定内容，生成通用描述
        return f"[{domain_name}] 实现 {full_description} 中的{domain_name}部分"

    def _infer_files_for_domain(self, task: TaskInput, domain: str) -> List[str]:
        """推断领域相关的文件"""
        # 如果任务指定了文件，过滤出该领域的
        if task.files:
            domain_files = []
            for file_path in task.files:
                if self._file_belongs_to_domain(file_path, domain):
                    domain_files.append(file_path)
            if domain_files:
                return domain_files

        # 返回领域的默认文件模式
        return DOMAIN_FILE_PATTERNS.get(domain, [])[:3]

    def _file_belongs_to_domain(self, file_path: str, domain: str) -> bool:
        """判断文件是否属于某领域"""
        file_lower = file_path.lower()
        keywords = DOMAIN_KEYWORDS.get(domain, [])
        for keyword in keywords:
            if keyword.lower() in file_lower:
                return True
        return False

    def _generate_success_criteria(self, domain: str, description: str) -> List[str]:
        """生成成功标准"""
        base_criteria = {
            "frontend": [
                "UI组件正确渲染",
                "样式符合设计规范",
                "交互逻辑正常工作",
                "无控制台错误",
            ],
            "backend": [
                "API接口正常响应",
                "业务逻辑正确实现",
                "错误处理完善",
                "日志记录完整",
            ],
            "database": [
                "数据模型定义正确",
                "数据迁移脚本可执行",
                "查询性能可接受",
                "数据完整性约束到位",
            ],
            "test": [
                "测试覆盖关键路径",
                "所有测试用例通过",
                "边界条件已覆盖",
            ],
            "docs": [
                "文档清晰易懂",
                "示例代码可运行",
                "API文档完整",
            ],
            "devops": [
                "构建脚本可执行",
                "配置文件正确",
                "部署流程可复现",
            ],
        }

        criteria = base_criteria.get(domain, ["任务完成"])
        return criteria[:3]  # 返回前3个

    def _estimate_effort(
        self, domain: str, all_domains: Set[str], description: str
    ) -> str:
        """估算工作量"""
        # 简单启发式：根据领域数量和描述长度
        if len(all_domains) >= 4:
            return "high"
        elif len(all_domains) >= 2:
            return "medium"
        else:
            return "low"

    def _compute_priority(self, domain: str) -> int:
        """计算优先级"""
        # 数据库和后端通常需要先完成
        priority_map = {
            "database": 2,
            "backend": 1,
            "frontend": 0,
            "test": -1,
            "docs": -1,
            "devops": 0,
        }
        return priority_map.get(domain, 0)

    def _resolve_dependencies(
        self, subtask: SubTask, all_subtasks: List[SubTask]
    ) -> List[str]:
        """解析子任务依赖"""
        deps = []
        domain_deps = DOMAIN_DEPENDENCIES.get(subtask.domain, [])

        for dep_domain in domain_deps:
            for other in all_subtasks:
                if other.domain == dep_domain and other.id != subtask.id:
                    deps.append(other.id)

        return deps

    def _compute_execution_order(
        self,
        subtasks: List[SubTask],
        dependency_graph: Dict[str, List[str]],
    ) -> List[List[str]]:
        """计算执行顺序（拓扑排序 + 并行分组）"""
        # 使用 Kahn's algorithm 进行拓扑排序
        in_degree = {st.id: 0 for st in subtasks}
        # 计算每个节点的入度（依赖数量）
        for subtask_id, deps in dependency_graph.items():
            in_degree[subtask_id] = len(deps)

        # 分层：同一层的可以并行执行
        layers = []
        remaining = set(in_degree.keys())

        while remaining:
            # 找到当前层（入度为0的节点）
            current_layer = [
                st_id for st_id in remaining
                if in_degree[st_id] == 0
            ]

            if not current_layer:
                # 有循环依赖，取剩余的
                current_layer = list(remaining)

            layers.append(current_layer)

            # 更新入度
            for st_id in current_layer:
                remaining.remove(st_id)
                # 减少依赖此节点的入度
                for other_id, deps in dependency_graph.items():
                    if st_id in deps and other_id in remaining:
                        in_degree[other_id] -= 1

        return layers

    def _generate_summary(
        self,
        task: TaskInput,
        subtasks: List[SubTask],
        execution_order: List[List[str]],
    ) -> str:
        """生成分解摘要"""
        lines = [
            f"任务分解完成，共 {len(subtasks)} 个子任务：",
        ]

        for i, layer in enumerate(execution_order):
            layer_desc = ", ".join(layer)
            if len(layer) > 1:
                lines.append(f"  阶段 {i+1}（并行）: {layer_desc}")
            else:
                lines.append(f"  阶段 {i+1}: {layer_desc}")

        return "\n".join(lines)

    def _generate_task_id(self, prefix: str) -> str:
        """生成任务ID"""
        import time
        self._task_counter += 1
        ts = time.strftime("%Y%m%d-%H%M%S")
        return f"{prefix}-{ts}-{self._task_counter:03d}"
