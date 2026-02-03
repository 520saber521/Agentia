"""
智能任务调度模块

提供任务复杂度判断、任务分解、智能调度和结果聚合功能。

新增：契约优先设计 (Contract-First Design)
- 在分解任务前先定义接口契约
- 确保各 Agent 的工作能够对接
"""

from .complexity import ComplexityJudge, judge_complexity
from .decomposer import TaskDecomposer, SubTask
from .agents import (
    SPECIALIZED_AGENTS,
    match_agent_for_task,
    match_agents_for_domains,
    format_agent_assignment_summary,
    AgentProfile,
)
from .scheduler import TaskScheduler
from .aggregator import ResultAggregator, FinalResult

# 契约相关
from .contracts import (
    InterfaceContract,
    ContractBuilder,
    ModelSpec,
    EndpointSpec,
    ComponentSpec,
    NamingConvention,
    generate_contract_document,
)
from .enhanced_decomposer import (
    EnhancedTaskDecomposer,
    EnhancedSubTask,
    EnhancedDecomposeResult,
)
from .design import (
    DesignGenerator,
    DesignDocument,
    DesignStatus,
    ProjectType,
    Requirement,
    analyze_and_design,
    print_design_for_review,
)
from .analyzer import (
    ProjectAnalyzer,
    ImpactAnalyzer,
    ProjectStructure,
    ImpactAnalysis,
    RiskLevel,
    analyze_project,
    analyze_impact,
    format_project_analysis,
    format_impact_analysis,
)
from .collaboration import (
    CollaborationHub,
    StatusBroadcaster,
    ProgressBoard,
    FileLockManager,
    DependencyTracker,
    CodeReviewManager,
    IntegrationChecker,
    create_collaboration_hub,
)

__all__ = [
    # 复杂度判断
    "ComplexityJudge",
    "judge_complexity",
    # 任务分解
    "TaskDecomposer",
    "SubTask",
    # 增强版分解（带契约）
    "EnhancedTaskDecomposer",
    "EnhancedSubTask",
    "EnhancedDecomposeResult",
    # Agent 配置
    "SPECIALIZED_AGENTS",
    "match_agent_for_task",
    # 调度器
    "TaskScheduler",
    # 聚合器
    "ResultAggregator",
    "FinalResult",
    # 契约
    "InterfaceContract",
    "ContractBuilder",
    "ModelSpec",
    "EndpointSpec",
    "ComponentSpec",
    "NamingConvention",
    "generate_contract_document",
]
