"""
Pipeline Agent Profile Definitions

Inspired by the Cowork Forge multi-agent architecture, this module defines
agent profiles for the 7-stage development pipeline:
  Idea → PRD → Design → Plan → Coding → Check → Delivery

Each stage uses an Actor-Critic pattern where applicable.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum


class StageType(Enum):
    """Stage execution type"""
    SIMPLE = "simple"           # Single agent, one execution
    ACTOR_CRITIC = "actor_critic"  # Actor generates, Critic reviews


class AgentRole(Enum):
    """Agent role in a stage"""
    ACTOR = "actor"     # Creator/generator (temperature 0.7)
    CRITIC = "critic"   # Reviewer/validator (temperature 0.3)
    SIMPLE = "simple"   # Standalone agent


@dataclass
class StageAgentProfile:
    """Profile for a pipeline stage agent"""
    agent_id: str
    name: str
    role: AgentRole
    stage: str
    prompt_template: str
    temperature: float = 0.7
    description: str = ""

    # Domain mapping (for coding stages)
    domain: Optional[str] = None


@dataclass
class StageDefinition:
    """Definition of a pipeline stage"""
    stage_id: str
    name: str
    stage_type: StageType
    order: int
    description: str

    # For Simple stages: single agent
    agent: Optional[str] = None

    # For Actor-Critic stages
    actor: Optional[str] = None
    critic: Optional[str] = None
    max_iterations: int = 1

    # HITL (Human In The Loop) confirmation
    needs_confirmation: bool = True

    # Successor stage
    on_success: Optional[str] = None
    on_failure: Optional[str] = None

    # Stage-specific instructions (overrides for prompt)
    instruction_hint: str = ""


@dataclass
class FlowDefinition:
    """A complete 7-stage pipeline flow"""
    flow_id: str
    name: str
    stages: List[StageDefinition]
    start_stage: str = "idea"

    # Configuration
    stop_on_failure: bool = True
    max_feedback_loops: int = 5
    max_stage_retries: int = 3
    retry_delay_ms: int = 5000


# ============================================================
# Agent Profiles for Pipeline Stages
# ============================================================

PIPELINE_AGENTS: Dict[str, StageAgentProfile] = {
    # ========== Idea Stage ==========
    "idea_agent": StageAgentProfile(
        agent_id="idea_agent",
        name="Idea Agent",
        role=AgentRole.SIMPLE,
        stage="idea",
        prompt_template="prompts/agent_idea.txt",
        temperature=0.7,
        description="捕获用户需求，生成结构化项目构想文档",
    ),

    # ========== PRD Stage ==========
    "prd_actor": StageAgentProfile(
        agent_id="prd_actor",
        name="PRD Actor",
        role=AgentRole.ACTOR,
        stage="prd",
        prompt_template="prompts/agent_prd_actor.txt",
        temperature=0.7,
        description="生成完整产品需求文档和功能列表",
    ),
    "prd_critic": StageAgentProfile(
        agent_id="prd_critic",
        name="PRD Critic",
        role=AgentRole.CRITIC,
        stage="prd",
        prompt_template="prompts/agent_prd_critic.txt",
        temperature=0.3,
        description="审查需求文档的覆盖度、一致性和可执行性",
    ),

    # ========== Design Stage ==========
    "design_actor": StageAgentProfile(
        agent_id="design_actor",
        name="Design Actor",
        role=AgentRole.ACTOR,
        stage="design",
        prompt_template="prompts/agent_design_actor.txt",
        temperature=0.7,
        description="设计系统技术架构、数据流和接口规范",
    ),
    "design_critic": StageAgentProfile(
        agent_id="design_critic",
        name="Design Critic",
        role=AgentRole.CRITIC,
        stage="design",
        prompt_template="prompts/agent_design_critic.txt",
        temperature=0.3,
        description="审查技术架构的合理性、安全性和可维护性",
    ),

    # ========== Plan Stage ==========
    "plan_actor": StageAgentProfile(
        agent_id="plan_actor",
        name="Plan Actor",
        role=AgentRole.ACTOR,
        stage="plan",
        prompt_template="prompts/agent_plan_actor.txt",
        temperature=0.7,
        description="将设计拆解为可执行的任务列表和里程碑",
    ),
    "plan_critic": StageAgentProfile(
        agent_id="plan_critic",
        name="Plan Critic",
        role=AgentRole.CRITIC,
        stage="plan",
        prompt_template="prompts/agent_plan_critic.txt",
        temperature=0.3,
        description="审查任务依赖关系、粒度和工作量估算",
    ),

    # ========== Coding Stage ==========
    "coding_actor": StageAgentProfile(
        agent_id="coding_actor",
        name="Coding Actor",
        role=AgentRole.ACTOR,
        stage="coding",
        prompt_template="prompts/agent_coding_actor.txt",
        temperature=0.7,
        description="按计划实现高质量的生产代码",
    ),
    "coding_critic": StageAgentProfile(
        agent_id="coding_critic",
        name="Coding Critic",
        role=AgentRole.CRITIC,
        stage="coding",
        prompt_template="prompts/agent_coding_critic.txt",
        temperature=0.3,
        description="运行测试和lint，审查代码质量和安全性",
    ),

    # ========== Check Stage ==========
    "check_agent": StageAgentProfile(
        agent_id="check_agent",
        name="Check Agent",
        role=AgentRole.SIMPLE,
        stage="check",
        prompt_template="prompts/agent_check.txt",
        temperature=0.3,
        description="全面质量验证，必要时跳回之前阶段",
    ),

    # ========== Delivery Stage ==========
    "delivery_agent": StageAgentProfile(
        agent_id="delivery_agent",
        name="Delivery Agent",
        role=AgentRole.SIMPLE,
        stage="delivery",
        prompt_template="prompts/agent_delivery.txt",
        temperature=0.5,
        description="打包代码、生成交付报告和启动文档",
    ),
}


# ============================================================
# Default Pipeline Flow (7 stages)
# ============================================================

DEFAULT_FLOW = FlowDefinition(
    flow_id="default",
    name="Standard 7-Stage Pipeline",
    start_stage="idea",
    stop_on_failure=True,
    max_feedback_loops=5,
    max_stage_retries=3,
    retry_delay_ms=5000,
    stages=[
        StageDefinition(
            stage_id="idea",
            name="Idea - 需求捕获",
            stage_type=StageType.SIMPLE,
            order=1,
            description="捕获并结构化用户需求，生成项目构想",
            agent="idea_agent",
            on_success="prd",
            needs_confirmation=True,
        ),
        StageDefinition(
            stage_id="prd",
            name="PRD - 需求文档",
            stage_type=StageType.ACTOR_CRITIC,
            order=2,
            description="生成产品需求文档并进行审查",
            actor="prd_actor",
            critic="prd_critic",
            max_iterations=1,
            on_success="design",
            needs_confirmation=True,
        ),
        StageDefinition(
            stage_id="design",
            name="Design - 技术设计",
            stage_type=StageType.ACTOR_CRITIC,
            order=3,
            description="设计系统架构并进行审查",
            actor="design_actor",
            critic="design_critic",
            max_iterations=1,
            on_success="plan",
            needs_confirmation=True,
        ),
        StageDefinition(
            stage_id="plan",
            name="Plan - 实施计划",
            stage_type=StageType.ACTOR_CRITIC,
            order=4,
            description="拆解任务并制定实施计划",
            actor="plan_actor",
            critic="plan_critic",
            max_iterations=1,
            on_success="coding",
            needs_confirmation=True,
        ),
        StageDefinition(
            stage_id="coding",
            name="Coding - 代码实现",
            stage_type=StageType.ACTOR_CRITIC,
            order=5,
            description="编写代码并进行审查",
            actor="coding_actor",
            critic="coding_critic",
            max_iterations=2,  # Allow more iterations for coding
            on_success="check",
            needs_confirmation=True,
        ),
        StageDefinition(
            stage_id="check",
            name="Check - 质量验证",
            stage_type=StageType.SIMPLE,
            order=6,
            description="全面质量验证，可跳回之前阶段",
            agent="check_agent",
            on_success="delivery",
            needs_confirmation=False,  # Auto-run
        ),
        StageDefinition(
            stage_id="delivery",
            name="Delivery - 项目交付",
            stage_type=StageType.SIMPLE,
            order=7,
            description="打包代码、生成交付报告",
            agent="delivery_agent",
            on_success=None,  # End of pipeline
            needs_confirmation=False,  # Auto-run
        ),
    ],
)


# ============================================================
# Quick Start Flow (4 stages, for smaller projects)
# ============================================================

QUICK_FLOW = FlowDefinition(
    flow_id="quick",
    name="Quick 4-Stage Pipeline",
    start_stage="design",
    stop_on_failure=True,
    max_feedback_loops=3,
    max_stage_retries=2,
    stages=[
        StageDefinition(
            stage_id="design",
            name="Design - 技术设计",
            stage_type=StageType.ACTOR_CRITIC,
            order=1,
            description="快速设计系统架构",
            actor="design_actor",
            critic="design_critic",
            max_iterations=1,
            on_success="coding",
            needs_confirmation=True,
        ),
        StageDefinition(
            stage_id="coding",
            name="Coding - 代码实现",
            stage_type=StageType.ACTOR_CRITIC,
            order=2,
            description="编写代码",
            actor="coding_actor",
            critic="coding_critic",
            max_iterations=2,
            on_success="check",
            needs_confirmation=True,
        ),
        StageDefinition(
            stage_id="check",
            name="Check - 质量验证",
            stage_type=StageType.SIMPLE,
            order=3,
            description="质量验证",
            agent="check_agent",
            on_success="delivery",
            needs_confirmation=False,
        ),
        StageDefinition(
            stage_id="delivery",
            name="Delivery - 交付",
            stage_type=StageType.SIMPLE,
            order=4,
            description="打包交付",
            agent="delivery_agent",
            on_success=None,
            needs_confirmation=False,
        ),
    ],
)


# Critical stages that require human confirmation
CRITICAL_STAGES = {"idea", "prd", "design", "plan", "coding"}


def is_critical_stage(stage_name: str) -> bool:
    """Check if a stage requires human confirmation"""
    return stage_name in CRITICAL_STAGES


def get_stage_definition(flow: FlowDefinition, stage_id: str) -> Optional[StageDefinition]:
    """Get stage definition by ID"""
    for stage in flow.stages:
        if stage.stage_id == stage_id:
            return stage
    return None


def get_agent_profile(agent_id: str) -> Optional[StageAgentProfile]:
    """Get agent profile by ID"""
    return PIPELINE_AGENTS.get(agent_id)


def get_actor_critic_pair(stage: StageDefinition) -> tuple:
    """Get (actor_profile, critic_profile) for an Actor-Critic stage"""
    if stage.stage_type != StageType.ACTOR_CRITIC:
        return (None, None)
    return (
        get_agent_profile(stage.actor) if stage.actor else None,
        get_agent_profile(stage.critic) if stage.critic else None,
    )
