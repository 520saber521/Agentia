"""
7-Stage Pipeline Executor

Inspired by Cowork Forge's multi-agent architecture, this module implements
a complete development pipeline: Idea → PRD → Design → Plan → Coding → Check → Delivery.

Key design patterns borrowed:
- Actor-Critic loop: Each creative stage has an Actor (generator) and Critic (reviewer)
- Artifact pre-injection: Previous stage outputs are injected into prompts to reduce tool calls
- HITL confirmation: Critical stages pause for human approval
- Goto stage: Check agent can jump back to earlier stages
- Feedback loops: Users can provide feedback to improve outputs
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

from .stage_agents import (
    FlowDefinition,
    StageDefinition,
    StageType,
    StageAgentProfile,
    AgentRole,
    DEFAULT_FLOW,
    QUICK_FLOW,
    get_stage_definition,
    get_agent_profile,
    get_actor_critic_pair,
    is_critical_stage,
)

logger = logging.getLogger(__name__)


# ============================================================
# Data Models
# ============================================================

class StageStatus(Enum):
    """Status of a stage execution"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    WAITING_CONFIRMATION = "waiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    GOTO = "goto"  # Redirect to another stage


class ConfirmationAction(Enum):
    """Possible user actions on confirmation"""
    PASS = "pass"           # Approve and continue
    FEEDBACK = "feedback"   # Provide feedback for re-generation
    SKIP = "skip"           # Skip to next stage
    CANCEL = "cancel"       # Cancel the pipeline
    VIEW_ARTIFACT = "view"  # View artifact without consuming feedback cycle


@dataclass
class StageResult:
    """Result of a single stage execution"""
    stage_id: str
    status: StageStatus
    actor_output: str = ""          # Actor's text/tool output
    critic_feedback: Optional[Dict] = None  # Critic's review
    artifacts: List[str] = field(default_factory=list)  # Created file paths
    artifacts_content: Dict[str, str] = field(default_factory=dict)  # path → content
    tool_calls: List[Dict] = field(default_factory=list)
    iteration: int = 0              # How many iterations (Actor-Critic loops)
    feedback_rounds: int = 0        # How many user feedback rounds
    error: Optional[str] = None
    duration_ms: int = 0
    goto_target: Optional[str] = None  # If status == GOTO, target stage
    goto_reason: Optional[str] = None


@dataclass
class PipelineResult:
    """Result of the entire pipeline execution"""
    flow_id: str
    status: str  # "success", "partial", "failed", "cancelled"
    stages: Dict[str, StageResult] = field(default_factory=dict)
    execution_order: List[str] = field(default_factory=list)
    current_stage: str = ""
    all_artifacts: Dict[str, str] = field(default_factory=dict)
    total_duration_ms: int = 0
    summary: str = ""
    error: Optional[str] = None


# ============================================================
# Artifact Injection Maps
# ============================================================

# Maps each stage → list of previous stage artifacts to pre-inject into the prompt
ARTIFACT_INJECTION_MAP = {
    "prd": ["idea.md"],
    "design": ["prd.md"],
    "plan": ["design.md"],
    "coding": ["plan.md", "design.md"],
    "check": ["prd.md", "design.md", "plan.md"],
    "delivery": ["idea.md", "prd.md", "design.md", "plan.md", "check_report.md"],
}


def build_artifact_preview(artifacts: Dict[str, str], stage_id: str, max_chars: int = 2000) -> str:
    """
    Build a preview of previous stage artifacts to inject into the prompt.
    
    This reduces the number of tool calls the agent needs to make by providing
    relevant context directly in the prompt.
    """
    artifact_names = ARTIFACT_INJECTION_MAP.get(stage_id, [])
    if not artifact_names or not artifacts:
        return ""

    parts = ["\n\n--- PREVIOUS STAGE ARTIFACTS ---\n"]

    for name in artifact_names:
        # Find matching artifact
        for path, content in artifacts.items():
            if name in path or path.endswith(name):
                # Truncate long content
                truncated = content[:max_chars]
                if len(content) > max_chars:
                    truncated += f"\n... (truncated, {len(content) - max_chars} more chars)"
                
                parts.append(f"\n## {path}\n```markdown\n{truncated}\n```\n")
                break

    parts.append("--- END ARTIFACTS ---\n")
    return "\n".join(parts)


# ============================================================
# Pipeline Executor
# ============================================================

class PipelineExecutor:
    """
    7-stage pipeline executor with Actor-Critic loops.
    
    Usage:
        executor = PipelineExecutor()
        result = await executor.execute(flow=DEFAULT_FLOW, user_input="Build a todo app")
    """

    def __init__(
        self,
        send_message: Optional[Callable] = None,
        on_confirmation: Optional[Callable] = None,
    ):
        """
        Args:
            send_message: Function to send messages to agents
            on_confirmation: Async callback for HITL confirmation
                Signature: async (stage_id, artifact_preview) -> ConfirmationAction
        """
        self.send_message = send_message
        self.on_confirmation = on_confirmation
        self.artifacts: Dict[str, str] = {}  # Global artifact storage
    
    async def execute(
        self,
        flow: FlowDefinition = None,
        user_input: str = "",
        start_stage: Optional[str] = None,
        previous_artifacts: Optional[Dict[str, str]] = None,
        on_stage_start: Optional[Callable] = None,
        on_stage_end: Optional[Callable] = None,
    ) -> PipelineResult:
        """
        Execute the full pipeline.
        
        Args:
            flow: Flow definition (defaults to DEFAULT_FLOW)
            user_input: Initial user requirement/description
            start_stage: Override start stage
            previous_artifacts: Artifacts from a previous run (for evolution mode)
            on_stage_start: Callback when a stage starts
            on_stage_end: Callback when a stage ends
        """
        flow = flow or DEFAULT_FLOW
        self.artifacts = previous_artifacts or {}

        result = PipelineResult(
            flow_id=flow.flow_id,
            current_stage=start_stage or flow.start_stage,
        )

        start_time = time.time()

        # Build stage execution order
        stage_order = self._build_execution_order(flow, result.current_stage)
        result.execution_order = stage_order

        for stage_id in stage_order:
            stage_def = get_stage_definition(flow, stage_id)
            if not stage_def:
                logger.warning(f"Stage {stage_id} not found in flow {flow.flow_id}")
                continue

            result.current_stage = stage_id

            # Notify stage start
            if on_stage_start:
                await self._safe_call(on_stage_start, stage_id, stage_def)

            logger.info(f"Starting stage: {stage_id} ({stage_def.name})")

            # Execute stage with retry
            stage_result = await self._execute_stage_with_retry(
                flow=flow,
                stage_def=stage_def,
                user_input=user_input,
                max_retries=flow.max_stage_retries,
            )

            result.stages[stage_id] = stage_result

            # Handle goto (redirect to another stage)
            if stage_result.status == StageStatus.GOTO and stage_result.goto_target:
                logger.info(
                    f"Stage {stage_id} requested goto → {stage_result.goto_target}: "
                    f"{stage_result.goto_reason}"
                )
                # Re-insert the target stage and related stages into execution order
                # Find the target stage index and re-execute from there
                redirect_stages = self._get_stages_from(flow, stage_result.goto_target)
                # Add redirect stages to execution (avoid duplicates)
                existing = set(stage_order)
                for s in redirect_stages:
                    if s not in existing:
                        stage_order.append(s)
                    else:
                        # Stage already executed, we need to re-execute it
                        # Mark as pending for re-execution
                        pass

                # For now, add a note and continue with the current flow
                # In production, you'd want to re-execute the target stage
                logger.warning(
                    f"Goto from {stage_id} to {stage_result.goto_target} - "
                    f"would re-execute in production"
                )

            # Handle failure
            if stage_result.status == StageStatus.FAILED:
                if flow.stop_on_failure:
                    logger.error(f"Pipeline stopped due to failure at stage: {stage_id}")
                    result.status = "failed"
                    result.error = stage_result.error
                    result.total_duration_ms = int((time.time() - start_time) * 1000)
                    return result

            # Notify stage end
            if on_stage_end:
                await self._safe_call(on_stage_end, stage_id, stage_result)

            # Collect artifacts
            for path, content in stage_result.artifacts_content.items():
                self.artifacts[path] = content
            result.all_artifacts = dict(self.artifacts)

        # All stages completed
        result.status = "success"
        result.total_duration_ms = int((time.time() - start_time) * 1000)
        result.summary = self._generate_summary(result)

        return result

    def _build_execution_order(self, flow: FlowDefinition, start_stage: str) -> List[str]:
        """Build ordered list of stages to execute, following on_success links"""
        order = []
        current = start_stage

        visited = set()
        while current and current not in visited:
            visited.add(current)
            order.append(current)
            stage_def = get_stage_definition(flow, current)
            if stage_def:
                current = stage_def.on_success or ""
            else:
                break

        return order

    def _get_stages_from(self, flow: FlowDefinition, start_stage: str) -> List[str]:
        """Get all stages from start_stage to end"""
        return self._build_execution_order(flow, start_stage)

    async def _execute_stage_with_retry(
        self,
        flow: FlowDefinition,
        stage_def: StageDefinition,
        user_input: str,
        max_retries: int,
    ) -> StageResult:
        """Execute a stage with retry logic"""
        last_error = None

        for attempt in range(max_retries):
            try:
                result = await self._execute_stage(
                    flow=flow,
                    stage_def=stage_def,
                    user_input=user_input,
                )

                if result.status == StageStatus.FAILED:
                    last_error = result.error
                    logger.warning(
                        f"Stage {stage_def.stage_id} attempt {attempt + 1}/{max_retries} failed: "
                        f"{last_error}"
                    )
                    await asyncio.sleep(flow.retry_delay_ms / 1000)
                    continue

                return result

            except Exception as e:
                last_error = str(e)
                logger.error(
                    f"Stage {stage_def.stage_id} attempt {attempt + 1}/{max_retries} error: {e}"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(flow.retry_delay_ms / 1000)

        # All retries exhausted
        return StageResult(
            stage_id=stage_def.stage_id,
            status=StageStatus.FAILED,
            error=f"Failed after {max_retries} attempts: {last_error}",
        )

    async def _execute_stage(
        self,
        flow: FlowDefinition,
        stage_def: StageDefinition,
        user_input: str,
    ) -> StageResult:
        """Execute a single stage"""
        stage_start = time.time()

        if stage_def.stage_type == StageType.SIMPLE:
            result = await self._execute_simple_stage(stage_def, user_input)
        elif stage_def.stage_type == StageType.ACTOR_CRITIC:
            result = await self._execute_actor_critic_stage(stage_def, user_input, flow)
        else:
            result = StageResult(
                stage_id=stage_def.stage_id,
                status=StageStatus.FAILED,
                error=f"Unknown stage type: {stage_def.stage_type}",
            )

        result.duration_ms = int((time.time() - stage_start) * 1000)

        # HITL confirmation for critical stages
        if result.status == StageStatus.COMPLETED and stage_def.needs_confirmation:
            result = await self._request_confirmation(stage_def, result, flow)

        return result

    async def _execute_simple_stage(
        self,
        stage_def: StageDefinition,
        user_input: str,
    ) -> StageResult:
        """Execute a simple (single-agent) stage"""
        agent = get_agent_profile(stage_def.agent) if stage_def.agent else None
        if not agent:
            return StageResult(
                stage_id=stage_def.stage_id,
                status=StageStatus.FAILED,
                error=f"No agent configured for stage: {stage_def.stage_id}",
            )

        # Build prompt with artifact injection
        prompt = self._build_agent_prompt(
            agent=agent,
            stage_def=stage_def,
            user_input=user_input,
        )

        # Execute agent (placeholder - actual execution depends on your adapter)
        actor_output, artifacts = await self._run_agent(
            agent_id=agent.agent_id,
            prompt=prompt,
            temperature=agent.temperature,
        )

        return StageResult(
            stage_id=stage_def.stage_id,
            status=StageStatus.COMPLETED,
            actor_output=actor_output,
            artifacts=artifacts.get("files", []),
            artifacts_content=artifacts.get("content", {}),
            tool_calls=artifacts.get("tool_calls", []),
        )

    async def _execute_actor_critic_stage(
        self,
        stage_def: StageDefinition,
        user_input: str,
        flow: FlowDefinition,
    ) -> StageResult:
        """
        Execute an Actor-Critic stage with the loop pattern:
        
        Loop:
          1. Actor generates content
          2. Critic reviews content
          3. If Critic passes → done
          4. If Critic suggests revisions → Actor regenerates
          5. Repeat up to max_iterations
        """
        actor, critic = get_actor_critic_pair(stage_def)
        if not actor or not critic:
            return StageResult(
                stage_id=stage_def.stage_id,
                status=StageStatus.FAILED,
                error="Missing actor or critic configuration",
            )

        max_iterations = stage_def.max_iterations
        last_actor_output = ""
        last_artifacts = {}
        
        for iteration in range(max_iterations):
            logger.info(
                f"Stage {stage_def.stage_id} Actor-Critic iteration {iteration + 1}/{max_iterations}"
            )

            # === ACTOR PHASE ===
            actor_prompt = self._build_agent_prompt(
                agent=actor,
                stage_def=stage_def,
                user_input=user_input,
                previous_feedback=last_artifacts.get("critic_feedback"),
            )

            actor_output, artifacts = await self._run_agent(
                agent_id=actor.agent_id,
                prompt=actor_prompt,
                temperature=actor.temperature,
            )

            last_actor_output = actor_output
            last_artifacts = artifacts

            # === CRITIC PHASE ===
            critic_prompt = self._build_critic_prompt(
                critic=critic,
                stage_def=stage_def,
                actor_output=actor_output,
                artifacts=artifacts,
            )

            critic_output, critic_artifacts = await self._run_agent(
                agent_id=critic.agent_id,
                prompt=critic_prompt,
                temperature=critic.temperature,
            )

            # Parse critic verdict
            verdict = self._parse_critic_verdict(critic_output)

            if verdict == "PASS":
                # Critic approves, merge artifacts
                for path, content in critic_artifacts.get("content", {}).items():
                    artifacts["content"][path] = content

                return StageResult(
                    stage_id=stage_def.stage_id,
                    status=StageStatus.COMPLETED,
                    actor_output=actor_output,
                    critic_feedback={"verdict": "PASS", "output": critic_output},
                    artifacts=artifacts.get("files", []),
                    artifacts_content=artifacts.get("content", {}),
                    tool_calls=artifacts.get("tool_calls", []),
                    iteration=iteration + 1,
                )

            elif verdict == "REDO":
                # Critic requires major rework
                logger.warning(
                    f"Stage {stage_def.stage_id} iteration {iteration + 1}: "
                    f"Critic requested REDO"
                )
                last_artifacts["critic_feedback"] = critic_output
                continue

            else:  # REVISION_NEEDED or unknown
                # Critic suggests revisions
                logger.info(
                    f"Stage {stage_def.stage_id} iteration {iteration + 1}: "
                    f"Critic suggests REVISION_NEEDED"
                )
                last_artifacts["critic_feedback"] = critic_output
                continue

        # Max iterations reached
        return StageResult(
            stage_id=stage_def.stage_id,
            status=StageStatus.COMPLETED,
            actor_output=last_actor_output,
            critic_feedback={"verdict": "MAX_ITERATIONS", "message": "Max iterations reached"},
            artifacts=last_artifacts.get("files", []),
            artifacts_content=last_artifacts.get("content", {}),
            tool_calls=last_artifacts.get("tool_calls", []),
            iteration=max_iterations,
        )

    async def _request_confirmation(
        self,
        stage_def: StageDefinition,
        result: StageResult,
        flow: FlowDefinition,
    ) -> StageResult:
        """
        Request human confirmation for critical stages.
        
        Supports feedback loops: user can provide feedback and re-generate up to
        max_feedback_loops times.
        """
        for feedback_round in range(flow.max_feedback_loops):
            # Build artifact preview for user
            artifact_preview = result.actor_output[:2000]
            if len(result.actor_output) > 2000:
                artifact_preview += f"\n... (truncated)"

            # Request confirmation
            if self.on_confirmation:
                action = await self._safe_call(
                    self.on_confirmation, stage_def.stage_id, artifact_preview
                )
            else:
                # Default: auto-pass if no confirmation callback
                action = ConfirmationAction.PASS

            if action == ConfirmationAction.PASS:
                return result

            elif action == ConfirmationAction.FEEDBACK:
                # User provided feedback - re-execute the stage
                result.feedback_rounds = feedback_round + 1

                # Re-generate with user feedback
                new_result = await self._execute_stage(
                    flow=flow,
                    stage_def=stage_def,
                    user_input=f"PREVIOUS FEEDBACK: {artifact_preview}\n\n"
                              f"USER FEEDBACK: The user provided the following suggestions "
                              f"for improvement. Please revise accordingly.",
                )
                new_result.feedback_rounds = feedback_round + 1

                if new_result.status == StageStatus.COMPLETED:
                    result = new_result
                    continue
                else:
                    return new_result

            elif action == ConfirmationAction.SKIP:
                result.status = StageStatus.SKIPPED
                return result

            elif action == ConfirmationAction.CANCEL:
                result.status = StageStatus.FAILED
                result.error = "Cancelled by user"
                return result

        # Max feedback rounds reached
        logger.warning(
            f"Stage {stage_def.stage_id} reached max feedback rounds ({flow.max_feedback_loops})"
        )
        return result

    # ============================================================
    # Prompt Building
    # ============================================================

    def _build_agent_prompt(
        self,
        agent: StageAgentProfile,
        stage_def: StageDefinition,
        user_input: str,
        previous_feedback: Optional[str] = None,
    ) -> str:
        """Build the full prompt for an agent execution"""
        parts = []

        # Load prompt template
        try:
            with open(agent.prompt_template, "r", encoding="utf-8") as f:
                template = f.read()
        except FileNotFoundError:
            template = f"You are {agent.name}. {agent.description}"

        # Replace template variables
        template = template.replace("{{ROLE}}", agent.agent_id.split("_")[0].upper())
        template = template.replace("{{MESSAGE}}", "")

        parts.append(template)

        # Inject previous stage artifacts
        artifact_preview = build_artifact_preview(
            self.artifacts, stage_def.stage_id
        )
        if artifact_preview:
            parts.append(artifact_preview)

        # Inject user input / task context
        parts.append("\n\n--- TASK CONTEXT ---\n")
        parts.append(f"User Requirement: {user_input}")

        # Inject stage-specific instruction
        if stage_def.instruction_hint:
            parts.append(f"\nStage Hint: {stage_def.instruction_hint}")

        # Inject previous feedback (for re-generation)
        if previous_feedback:
            parts.append(f"\n\n--- PREVIOUS REVIEW FEEDBACK ---\n{previous_feedback}")
            parts.append("\nPlease address the feedback above in your response.")

        parts.append("\n\n--- YOUR TASK ---\n")
        parts.append(f"Execute the {stage_def.name} phase. ")
        parts.append("Use your tools to save artifacts when done.")

        return "\n".join(parts)

    def _build_critic_prompt(
        self,
        critic: StageAgentProfile,
        stage_def: StageDefinition,
        actor_output: str,
        artifacts: Dict[str, Any],
    ) -> str:
        """Build the prompt for a critic agent"""
        parts = []

        # Load prompt template
        try:
            with open(critic.prompt_template, "r", encoding="utf-8") as f:
                template = f.read()
        except FileNotFoundError:
            template = f"You are {critic.name}. {critic.description}"

        template = template.replace("{{ROLE}}", critic.agent_id.split("_")[0].upper())
        template = template.replace("{{MESSAGE}}", "")

        parts.append(template)

        # Inject the actor's output for review
        parts.append("\n\n--- ACTOR OUTPUT TO REVIEW ---\n")
        parts.append(actor_output[:4000])

        if len(actor_output) > 4000:
            parts.append(f"\n... (truncated, {len(actor_output) - 4000} more chars)")

        parts.append("\n\n--- YOUR REVIEW TASK ---\n")
        parts.append(f"Review the {stage_def.name} output above for quality and completeness.")
        parts.append("Use provide_feedback with your verdict (PASS, REVISION_NEEDED, or REDO).")

        return "\n".join(parts)

    def _parse_critic_verdict(self, output: str) -> str:
        """Parse the critic's verdict from their output"""
        output_lower = output.lower()

        # Look for explicit verdict
        if '"verdict": "pass"' in output_lower or "'verdict': 'pass'" in output_lower:
            return "PASS"
        if "verdict: pass" in output_lower:
            return "PASS"
        if '"verdict": "redo"' in output_lower or "'verdict': 'redo'" in output_lower:
            return "REDO"
        if "verdict: redo" in output_lower:
            return "REDO"
        if "revision_needed" in output_lower:
            return "REVISION_NEEDED"

        # Text-based detection
        if "no issues found" in output_lower or "all checks passed" in output_lower:
            return "PASS"
        if "critical" in output_lower or "must redo" in output_lower:
            return "REDO"

        # Default: assume revisions needed
        return "REVISION_NEEDED"

    # ============================================================
    # Agent Execution (Adapter Integration)
    # ============================================================

    async def _run_agent(
        self,
        agent_id: str,
        prompt: str,
        temperature: float = 0.7,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Run an agent with the given prompt.
        
        This is the integration point with your existing agent adapter system.
        Override this method or provide a custom executor.
        
        Returns:
            Tuple of (text_output, artifacts_dict)
            artifacts_dict = {
                "files": ["path1", "path2"],
                "content": {"path1": "content1", ...},
                "tool_calls": [...],
                "critic_feedback": "...",  # Optional
            }
        """
        if self.send_message:
            # Integration with existing messaging system
            message = {
                "type": "assign",
                "agent_id": agent_id,
                "prompt": prompt,
                "temperature": temperature,
            }
            try:
                response = await self._safe_call(self.send_message, message)
                return str(response), {"files": [], "content": {}}
            except Exception as e:
                logger.error(f"Agent {agent_id} execution error: {e}")
                return f"Error: {e}", {"files": [], "content": {}}
        else:
            # Placeholder - actual execution depends on your LLM adapter
            logger.warning(
                f"No send_message configured. Agent {agent_id} would execute with prompt of "
                f"{len(prompt)} chars"
            )
            return (
                f"[PLACEHOLDER] Agent {agent_id} would execute here with temperature {temperature}.",
                {"files": [], "content": {}, "tool_calls": []},
            )

    async def _safe_call(self, fn: Callable, *args, **kwargs):
        """Safely call a sync or async function"""
        try:
            result = fn(*args, **kwargs)
            if asyncio.iscoroutine(result):
                return await result
            return result
        except Exception as e:
            logger.error(f"Error calling {fn}: {e}")
            raise

    # ============================================================
    # Summary Generation
    # ============================================================

    def _generate_summary(self, result: PipelineResult) -> str:
        """Generate a human-readable pipeline summary"""
        lines = [
            "=" * 60,
            f"  Pipeline: {result.flow_id}",
            f"  Status: {result.status}",
            f"  Duration: {result.total_duration_ms / 1000:.1f}s",
            "=" * 60,
            "",
            "Stage Results:",
            "-" * 40,
        ]

        for stage_id in result.execution_order:
            stage_result = result.stages.get(stage_id)
            if not stage_result:
                continue

            status_icon = {
                StageStatus.COMPLETED: "✅",
                StageStatus.FAILED: "❌",
                StageStatus.SKIPPED: "⏭️",
                StageStatus.GOTO: "🔄",
            }.get(stage_result.status, "⏳")

            lines.append(
                f"  {status_icon} {stage_id}: {stage_result.status.value} "
                f"({stage_result.iteration} iters, "
                f"{stage_result.duration_ms / 1000:.1f}s)"
            )

            if stage_result.error:
                lines.append(f"     Error: {stage_result.error}")

            if stage_result.artifacts:
                lines.append(f"     Artifacts: {', '.join(stage_result.artifacts)}")

        lines.append("")
        lines.append(f"Total artifacts: {len(result.all_artifacts)}")

        return "\n".join(lines)


# ============================================================
# Convenience Functions
# ============================================================

def create_standard_pipeline(
    send_message: Optional[Callable] = None,
    on_confirmation: Optional[Callable] = None,
) -> PipelineExecutor:
    """Create a pipeline executor with the default 7-stage flow"""
    return PipelineExecutor(
        send_message=send_message,
        on_confirmation=on_confirmation,
    )


def create_quick_pipeline(
    send_message: Optional[Callable] = None,
    on_confirmation: Optional[Callable] = None,
) -> PipelineExecutor:
    """Create a pipeline executor with the quick 4-stage flow"""
    return PipelineExecutor(
        send_message=send_message,
        on_confirmation=on_confirmation,
    )
