"""
专用Agent角色配置

定义每个Agent的专长领域、技能和适用场景。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from fnmatch import fnmatch

from .decomposer import SubTask


@dataclass
class AgentProfile:
    """Agent配置文件"""
    role: str  # A, B, C, D
    name: str  # 显示名称
    specialty: str  # 专长领域
    domains: List[str]  # 擅长的领域
    focus_patterns: List[str]  # 关注的文件模式
    skills: List[str]  # 技能列表
    is_helper: bool = False  # 是否是辅助Agent
    priority_domains: List[str] = field(default_factory=list)  # 优先处理的领域
    description: str = ""  # 角色描述


# 专用Agent配置
SPECIALIZED_AGENTS: Dict[str, AgentProfile] = {
    "A": AgentProfile(
        role="A",
        name="专用Agent 1 - 前端专家",
        specialty="frontend",
        domains=["frontend"],
        focus_patterns=[
            "*.tsx",
            "*.jsx",
            "*.css",
            "*.scss",
            "*.html",
            "*.vue",
            "src/ui/*",
            "src/components/*",
            "src/pages/*",
            "src/views/*",
            "public/*",
            "assets/*",
        ],
        skills=["React", "Vue", "CSS", "HTML", "UI/UX", "响应式设计", "组件开发"],
        priority_domains=["frontend"],
        description="负责所有前端相关工作，包括UI组件开发、样式设计、页面布局、用户交互等。",
    ),
    "B": AgentProfile(
        role="B",
        name="专用Agent 2 - 后端专家",
        specialty="backend",
        domains=["backend", "devops"],
        focus_patterns=[
            "*.py",
            "src/api/*",
            "src/router/*",
            "src/services/*",
            "src/handlers/*",
            "src/controllers/*",
            "src/cli/*",
            "src/protocol/*",
        ],
        skills=["Python", "API设计", "业务逻辑", "路由", "中间件", "错误处理"],
        priority_domains=["backend"],
        description="负责所有后端相关工作，包括API开发、业务逻辑实现、路由配置、服务集成等。",
    ),
    "C": AgentProfile(
        role="C",
        name="专用Agent 3 - 数据专家",
        specialty="database",
        domains=["database"],
        focus_patterns=[
            "*.sql",
            "src/models/*",
            "src/storage/*",
            "src/state/*",
            "src/repository/*",
            "migrations/*",
            "schemas/*",
        ],
        skills=["SQL", "数据模型", "ORM", "数据迁移", "性能优化", "数据完整性"],
        priority_domains=["database"],
        description="负责所有数据相关工作，包括数据模型设计、存储层实现、数据迁移、查询优化等。",
    ),
    "D": AgentProfile(
        role="D",
        name="辅助Agent - 支援专家",
        specialty="support",
        domains=["test", "docs", "devops"],
        focus_patterns=[
            "tests/*",
            "test/*",
            "*_test.py",
            "test_*.py",
            "*.test.ts",
            "*.spec.ts",
            "docs/*",
            "*.md",
            "README*",
            "Dockerfile",
            "docker-compose*.yml",
            ".github/*",
            "scripts/*",
        ],
        skills=["测试", "文档", "CI/CD", "代码审查", "质量保证", "部署"],
        is_helper=True,
        priority_domains=["test", "docs"],
        description="辅助Agent，负责测试、文档、部署等支援工作。在其他Agent忙碌时可协助处理任务。",
    ),
}

# 领域到Agent的默认映射
DOMAIN_TO_AGENT: Dict[str, str] = {
    "frontend": "A",
    "backend": "B",
    "database": "C",
    "test": "D",
    "docs": "D",
    "devops": "D",
}


def get_agent_profile(role: str) -> Optional[AgentProfile]:
    """获取Agent配置"""
    return SPECIALIZED_AGENTS.get(role)


def get_all_agents() -> Dict[str, AgentProfile]:
    """获取所有Agent配置"""
    return SPECIALIZED_AGENTS.copy()


def match_agent_for_task(subtask: SubTask) -> str:
    """
    根据子任务匹配最合适的Agent

    Args:
        subtask: 子任务

    Returns:
        str: Agent角色 (A, B, C, D)
    """
    domain = subtask.domain

    # 1. 直接使用领域映射
    if domain in DOMAIN_TO_AGENT:
        return DOMAIN_TO_AGENT[domain]

    # 2. 根据文件模式匹配
    if subtask.files:
        scores: Dict[str, int] = {role: 0 for role in SPECIALIZED_AGENTS}

        for file_path in subtask.files:
            for role, profile in SPECIALIZED_AGENTS.items():
                for pattern in profile.focus_patterns:
                    if _match_file_pattern(file_path, pattern):
                        scores[role] += 1
                        break

        # 选择得分最高的Agent
        best_agent = max(scores.keys(), key=lambda r: scores[r])
        if scores[best_agent] > 0:
            return best_agent

    # 3. 默认返回后端Agent
    return "B"


def match_agents_for_domains(domains: Set[str]) -> Dict[str, str]:
    """
    为多个领域匹配Agent

    Args:
        domains: 领域集合

    Returns:
        Dict[str, str]: {domain: agent_role}
    """
    assignments = {}
    used_agents = set()

    # 按优先级分配
    sorted_domains = sorted(
        domains,
        key=lambda d: _domain_priority(d),
        reverse=True,
    )

    for domain in sorted_domains:
        # 获取默认Agent
        default_agent = DOMAIN_TO_AGENT.get(domain, "B")

        if default_agent not in used_agents:
            assignments[domain] = default_agent
            used_agents.add(default_agent)
        else:
            # 找一个空闲的Agent
            for role in ["A", "B", "C", "D"]:
                if role not in used_agents:
                    assignments[domain] = role
                    used_agents.add(role)
                    break
            else:
                # 所有Agent都被使用，复用辅助Agent
                assignments[domain] = "D"

    return assignments


def _match_file_pattern(file_path: str, pattern: str) -> bool:
    """匹配文件模式"""
    # 支持简单的通配符匹配
    if "*" in pattern:
        return fnmatch(file_path.lower(), pattern.lower())
    return pattern.lower() in file_path.lower()


def _domain_priority(domain: str) -> int:
    """领域优先级"""
    priorities = {
        "database": 3,
        "backend": 2,
        "frontend": 1,
        "test": 0,
        "docs": 0,
        "devops": 1,
    }
    return priorities.get(domain, 0)


def get_agent_for_file(file_path: str) -> str:
    """
    根据文件路径获取最合适的Agent

    Args:
        file_path: 文件路径

    Returns:
        str: Agent角色
    """
    for role, profile in SPECIALIZED_AGENTS.items():
        for pattern in profile.focus_patterns:
            if _match_file_pattern(file_path, pattern):
                return role
    return "B"  # 默认后端


def get_agent_prompt_context(role: str) -> Dict[str, Any]:
    """
    获取Agent的提示词上下文

    Args:
        role: Agent角色

    Returns:
        Dict: 提示词上下文
    """
    profile = SPECIALIZED_AGENTS.get(role)
    if not profile:
        return {}

    return {
        "role": role,
        "name": profile.name,
        "specialty": profile.specialty,
        "domains": profile.domains,
        "skills": profile.skills,
        "is_helper": profile.is_helper,
        "description": profile.description,
        "focus_patterns": profile.focus_patterns,
    }


def format_agent_assignment_summary(
    assignments: Dict[str, str],
    subtasks: Optional[List[SubTask]] = None,
) -> str:
    """
    格式化Agent分配摘要

    Args:
        assignments: {domain: agent_role}
        subtasks: 子任务列表

    Returns:
        str: 格式化的摘要
    """
    lines = ["Agent 分配方案："]

    for domain, role in sorted(assignments.items()):
        profile = SPECIALIZED_AGENTS.get(role)
        name = profile.name if profile else role
        lines.append(f"  - {domain}: {name} ({role})")

    if subtasks:
        lines.append("")
        lines.append("子任务分配：")
        for st in subtasks:
            agent = assignments.get(st.domain, "B")
            profile = SPECIALIZED_AGENTS.get(agent)
            name = profile.name if profile else agent
            lines.append(f"  - {st.id}: {name}")

    return "\n".join(lines)
