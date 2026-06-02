"""
Pipeline Agent 优化验证测试

覆盖三个优化组件:
1. Pipeline Tool Registry — 工具注册与分类
2. PipelineExecutor — 主循环、goto_stage、事件流、指标
3. CollaborationHub — 协作与信息交换

不干扰 Orchestrator 的现有功能。
"""

import asyncio
import json
import os
import sys
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from scheduler.pipeline import (
    ARTIFACT_INJECTION_MAP,
    ConfirmationAction,
    GotoStageError,
    PipelineExecutor,
    PipelineResult,
    StageEvent,
    StageStatus,
    build_artifact_preview,
    create_standard_pipeline,
)
from scheduler.pipeline_tools import (
    CriticVerdict,
    FeedbackEntry,
    PipelineToolCategory,
    PipelineToolMeta,
    PipelineToolRegistry,
    get_pipeline_tool_registry,
)
from scheduler.stage_agents import (
    DEFAULT_FLOW,
    QUICK_FLOW,
    PIPELINE_AGENTS,
    AgentRole,
    FlowDefinition,
    StageDefinition,
    StageType,
    get_actor_critic_pair,
    get_agent_profile,
    get_stage_definition,
    is_critical_stage,
)
from scheduler.collaboration import (
    CollaborationHub,
    ProgressBoard,
    StatusBroadcaster,
    DependencyTracker,
    BroadcastType,
)


# ============================================================================
# 1. Pipeline Tool Registry 测试
# ============================================================================

class TestPipelineToolRegistry(unittest.TestCase):

    def setUp(self):
        self.registry = get_pipeline_tool_registry()

    def test_registry_initializes_all_default_tools(self):
        self.assertGreater(self.registry.tool_count, 0)
        self.assertIn("goto_stage", self.registry._tools)
        self.assertIn("provide_feedback", self.registry._tools)
        self.assertIn("save_idea", self.registry._tools)
        self.assertIn("save_prd_doc", self.registry._tools)
        self.assertIn("save_design_doc", self.registry._tools)
        self.assertIn("save_plan_doc", self.registry._tools)
        self.assertIn("save_check_report", self.registry._tools)
        self.assertIn("save_delivery_report", self.registry._tools)
        self.assertIn("check_tests", self.registry._tools)
        self.assertIn("check_lint", self.registry._tools)
        self.assertIn("check_data_format", self.registry._tools)
        self.assertIn("run_command", self.registry._tools)

    def test_list_by_category(self):
        save_tools = self.registry.list_by_category(PipelineToolCategory.SAVE)
        self.assertGreater(len(save_tools), 0)
        saved_names = {t.name for t in save_tools}
        self.assertIn("save_idea", saved_names)
        self.assertIn("save_prd_doc", saved_names)

    def test_list_for_stage_idea(self):
        tools = self.registry.list_for_stage("idea")
        names = {t.name for t in tools}
        self.assertIn("save_idea", names)
        self.assertIn("provide_feedback", names)

    def test_list_for_stage_check(self):
        tools = self.registry.list_for_stage("check")
        names = {t.name for t in tools}
        self.assertIn("goto_stage", names)
        self.assertIn("check_tests", names)
        self.assertIn("check_data_format", names)

    def test_list_for_stage_coding(self):
        tools = self.registry.list_for_stage("coding")
        names = {t.name for t in tools}
        self.assertIn("run_command", names)
        self.assertIn("provide_feedback", names)

    def test_list_for_stage_prd(self):
        tools = self.registry.list_for_stage("prd")
        names = {t.name for t in tools}
        self.assertIn("save_prd_doc", names)
        self.assertIn("provide_feedback", names)

    def test_get_openai_schemas_for_stage(self):
        schemas = self.registry.get_openai_schemas_for_stage("check")
        self.assertIsInstance(schemas, list)
        schema_names = {s["function"]["name"] for s in schemas}
        self.assertIn("goto_stage", schema_names)
        self.assertIn("check_tests", schema_names)
        for s in schemas:
            self.assertEqual(s["type"], "function")

    def test_to_prompt_text(self):
        prompt = self.registry.to_prompt_text("idea")
        self.assertIn("Pipeline Tools", prompt)
        self.assertIn("save_idea", prompt)

    def test_register_custom_tool(self):
        registry = PipelineToolRegistry()
        meta = PipelineToolMeta(
            name="custom_check",
            description="Custom check tool",
            category=PipelineToolCategory.CHECK,
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: "ok",
            stage_scope="check",
        )
        registry.register(meta)
        self.assertEqual(registry.tool_count, 1)
        self.assertEqual(registry.get("custom_check").name, "custom_check")

    def test_register_batch(self):
        registry = PipelineToolRegistry()
        metas = [
            PipelineToolMeta(
                name="tool_a",
                description="A",
                category=PipelineToolCategory.SAVE,
                parameters={"type": "object", "properties": {}},
                handler=lambda **kw: "a",
                stage_scope="any",
            ),
            PipelineToolMeta(
                name="tool_b",
                description="B",
                category=PipelineToolCategory.CHECK,
                parameters={"type": "object", "properties": {}},
                handler=lambda **kw: "b",
                stage_scope="check",
            ),
        ]
        registry.register_batch(metas)
        self.assertEqual(registry.tool_count, 2)
        self.assertEqual(len(registry.list_by_category(PipelineToolCategory.SAVE)), 1)
        self.assertEqual(len(registry.list_by_category(PipelineToolCategory.CHECK)), 1)

    def test_initialize_defaults_idempotent(self):
        registry = PipelineToolRegistry()
        registry.initialize_defaults()
        count1 = registry.tool_count
        registry.initialize_defaults()
        count2 = registry.tool_count
        self.assertEqual(count1, count2)

    def test_goto_stage_raises_goto_stage_error(self):
        registry = PipelineToolRegistry()
        registry.initialize_defaults()
        with self.assertRaises(GotoStageError) as ctx:
            asyncio.run(registry.execute("goto_stage", {
                "target_stage": "coding",
                "reason": "Tests failed",
            }))
        self.assertEqual(ctx.exception.target_stage, "coding")
        self.assertIn("Tests failed", ctx.exception.reason)

    def test_provide_feedback_records_entry(self):
        registry = PipelineToolRegistry()
        registry.initialize_defaults()
        from scheduler.pipeline_tools import get_feedback_buffer, _clear_feedback_buffer
        asyncio.run(_clear_feedback_buffer())

        result = asyncio.run(registry.execute("provide_feedback", {
            "verdict": "PASS",
            "summary": "All good",
            "issues": "None",
            "suggestions": "Keep up the good work",
        }))
        data = json.loads(result)
        self.assertEqual(data["verdict"], "PASS")

        buffer = get_feedback_buffer()
        self.assertEqual(len(buffer), 1)
        self.assertEqual(buffer[0].verdict, CriticVerdict.PASS)

        asyncio.run(_clear_feedback_buffer())
        self.assertEqual(len(get_feedback_buffer()), 0)

    def test_save_idea_artifact(self):
        registry = PipelineToolRegistry()
        registry.initialize_defaults()
        result = asyncio.run(registry.execute("save_idea", {
            "content": "# My Idea\nThis is a test idea.",
        }))
        data = json.loads(result)
        self.assertEqual(data["saved"], "idea.md")
        self.assertGreater(data["bytes"], 0)

    def test_double_init_does_not_re_register(self):
        registry = get_pipeline_tool_registry()
        count = registry.tool_count
        registry2 = PipelineToolRegistry()
        registry2.initialize_defaults()
        self.assertEqual(registry2.tool_count, count)


# ============================================================================
# 2. PipelineExecutor 主循环测试
# ============================================================================

class TestPipelineExecutor(unittest.TestCase):

    def setUp(self):
        self.events_received = []

    def _event_handler(self, event: StageEvent):
        self.events_received.append(event)

    def _mock_send(self, message):
        return f"[MOCK] Agent {message.get('agent_id')} response for stage {message.get('stage_id')}"

    def _mock_confirm(self, stage_id, preview):
        return ConfirmationAction.PASS

    def test_create_standard_pipeline(self):
        executor = create_standard_pipeline()
        self.assertIsInstance(executor, PipelineExecutor)
        self.assertFalse(executor.cancel_token.is_set())

    def test_prompt_caching(self):
        executor = PipelineExecutor()
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("You are {{ROLE}} - test agent.")
            f.flush()
            tmp_path = f.name
        try:
            result1 = executor._load_prompt_template(tmp_path)
            result2 = executor._load_prompt_template(tmp_path)
            self.assertEqual(result1, result2)
            self.assertIn(tmp_path, executor._prompt_cache)
        finally:
            os.unlink(tmp_path)

    def test_stage_event_emission(self):
        executor = PipelineExecutor(
            send_message=self._mock_send,
            on_stage_event=self._event_handler,
        )
        executor._emit_event("test", "idea", {"key": "value"})
        self.assertEqual(len(self.events_received), 1)
        evt = self.events_received[0]
        self.assertEqual(evt.event_type, "test")
        self.assertEqual(evt.stage_id, "idea")
        self.assertEqual(evt.data["key"], "value")

    def test_build_execution_order(self):
        executor = PipelineExecutor()
        order = executor._build_execution_order(DEFAULT_FLOW, "idea")
        self.assertEqual(order, ["idea", "prd", "design", "plan", "coding", "check", "delivery"])

    def test_build_execution_order_mid_start(self):
        executor = PipelineExecutor()
        order = executor._build_execution_order(DEFAULT_FLOW, "coding")
        self.assertEqual(order, ["coding", "check", "delivery"])

    def test_build_execution_order_quick_flow(self):
        executor = PipelineExecutor()
        order = executor._build_execution_order(QUICK_FLOW, "design")
        self.assertEqual(order, ["design", "coding", "check", "delivery"])

    def test_parse_critic_verdict_pass(self):
        executor = PipelineExecutor()
        self.assertEqual(executor._parse_critic_verdict('{"verdict": "PASS"}'), "PASS")
        self.assertEqual(executor._parse_critic_verdict("no issues found in review"), "PASS")
        self.assertEqual(executor._parse_critic_verdict("All checks passed."), "PASS")

    def test_parse_critic_verdict_redo(self):
        executor = PipelineExecutor()
        self.assertEqual(executor._parse_critic_verdict('{"verdict": "REDO"}'), "REDO")
        self.assertEqual(executor._parse_critic_verdict("critical bug found, must redo"), "REDO")

    def test_parse_critic_verdict_revision(self):
        executor = PipelineExecutor()
        self.assertEqual(executor._parse_critic_verdict("revision_needed"), "REVISION_NEEDED")
        self.assertEqual(executor._parse_critic_verdict("some changes required"), "REVISION_NEEDED")

    def test_goto_stage_error_creation(self):
        err = GotoStageError("coding", "Test failure")
        self.assertEqual(err.target_stage, "coding")
        self.assertEqual(err.reason, "Test failure")
        self.assertIn("coding", str(err))

    def test_execute_simple_stage_placeholder(self):
        executor = PipelineExecutor(send_message=self._mock_send)
        stage_def = get_stage_definition(DEFAULT_FLOW, "idea")

        async def _run():
            return await executor._execute_simple_stage(stage_def, "Test input")

        result = asyncio.run(_run())
        self.assertEqual(result.status, StageStatus.COMPLETED)
        self.assertIn("[MOCK]", result.actor_output)

    def test_execute_simple_stage_no_agent(self):
        executor = PipelineExecutor()
        stage_def = StageDefinition(
            stage_id="unknown",
            name="Unknown",
            stage_type=StageType.SIMPLE,
            order=99,
            description="",
            agent="nonexistent",
            needs_confirmation=False,
        )
        async def _run():
            return await executor._execute_simple_stage(stage_def, "Test")
        result = asyncio.run(_run())
        self.assertEqual(result.status, StageStatus.FAILED)

    def test_execute_with_cancellation(self):
        executor = PipelineExecutor(
            send_message=self._mock_send,
            on_confirmation=self._mock_confirm,
            cancel_token=asyncio.Event(),
        )
        executor.cancel_token.set()

        async def _run():
            return await executor.execute(
                flow=DEFAULT_FLOW,
                user_input="Test cancel",
            )

        result = asyncio.run(_run())
        self.assertEqual(result.status, "cancelled")

    def test_execute_goto_stage_rerouting(self):
        executor = PipelineExecutor(
            send_message=self._mock_send,
            on_stage_event=self._event_handler,
        )

        class GotoTriggeringSend:
            def __init__(self):
                self.check_count = 0

            def __call__(self, message):
                stage_id = message.get("stage_id", "")
                if stage_id == "check":
                    self.check_count += 1
                    if self.check_count <= 1:
                        raise GotoStageError("coding", "Quality check failed")
                return f"[MOCK] response for {stage_id}"

        executor.send_message = GotoTriggeringSend()

        flow = FlowDefinition(
            flow_id="goto_test",
            name="Goto Test",
            start_stage="coding",
            stages=[
                StageDefinition(
                    stage_id="coding",
                    name="Coding",
                    stage_type=StageType.SIMPLE,
                    order=1,
                    description="Code",
                    agent="coding_actor",
                    on_success="check",
                    needs_confirmation=False,
                ),
                StageDefinition(
                    stage_id="check",
                    name="Check",
                    stage_type=StageType.SIMPLE,
                    order=2,
                    description="Check",
                    agent="check_agent",
                    on_success="delivery",
                    needs_confirmation=False,
                ),
                StageDefinition(
                    stage_id="delivery",
                    name="Delivery",
                    stage_type=StageType.SIMPLE,
                    order=3,
                    description="Deliver",
                    agent="delivery_agent",
                    needs_confirmation=False,
                ),
            ],
        )

        async def _run():
            return await executor.execute(flow=flow, user_input="Test goto")

        result = asyncio.run(_run())
        goto_events = [e for e in self.events_received if e.event_type == "goto"]
        self.assertGreater(len(goto_events), 0, "Expected at least one goto event")
        self.assertEqual(goto_events[0].data["to_stage"], "coding")

    def test_execute_full_flow_with_mock(self):
        executor = PipelineExecutor(
            send_message=self._mock_send,
            on_confirmation=self._mock_confirm,
            on_stage_event=self._event_handler,
        )

        async def _run():
            return await executor.execute(
                flow=DEFAULT_FLOW,
                user_input="Build a simple todo app",
            )

        result = asyncio.run(_run())
        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.stages), 7)
        self.assertGreater(result.total_duration_ms, 0)
        self.assertIn("metrics", result.__dict__)
        self.assertIsNotNone(result.summary)

    def test_stage_metrics_collected(self):
        executor = PipelineExecutor(
            send_message=self._mock_send,
            on_confirmation=self._mock_confirm,
        )

        async def _run():
            return await executor.execute(flow=DEFAULT_FLOW, user_input="Test metrics")

        result = asyncio.run(_run())
        self.assertIn("idea", result.metrics)
        self.assertIn("duration_ms", result.metrics["idea"])
        self.assertIn("status", result.metrics["idea"])
        self.assertEqual(result.metrics["idea"]["status"], "completed")

    def test_artifact_injection_map_coverage(self):
        self.assertIn("prd", ARTIFACT_INJECTION_MAP)
        self.assertIn("design", ARTIFACT_INJECTION_MAP)
        self.assertIn("plan", ARTIFACT_INJECTION_MAP)
        self.assertIn("coding", ARTIFACT_INJECTION_MAP)
        self.assertIn("check", ARTIFACT_INJECTION_MAP)
        self.assertIn("delivery", ARTIFACT_INJECTION_MAP)
        self.assertIn("idea.md", ARTIFACT_INJECTION_MAP["prd"])
        self.assertIn("plan.md", ARTIFACT_INJECTION_MAP["coding"])

    def test_build_artifact_preview_empty(self):
        result = build_artifact_preview({}, "prd")
        self.assertEqual(result, "")

    def test_build_artifact_preview_with_content(self):
        artifacts = {"idea.md": "# Test Idea\nContent here"}
        result = build_artifact_preview(artifacts, "prd")
        self.assertIn("PREVIOUS STAGE ARTIFACTS", result)
        self.assertIn("idea.md", result)
        self.assertIn("Test Idea", result)

    def test_stage_agent_profiles_exist(self):
        for stage_id in ["idea", "prd", "design", "plan", "coding", "check", "delivery"]:
            stage_def = get_stage_definition(DEFAULT_FLOW, stage_id)
            self.assertIsNotNone(stage_def, f"Stage {stage_id} should exist")
            if stage_def.stage_type == StageType.SIMPLE:
                agent = get_agent_profile(stage_def.agent)
                self.assertIsNotNone(agent, f"Agent for {stage_id} should exist")
            elif stage_def.stage_type == StageType.ACTOR_CRITIC:
                actor, critic = get_actor_critic_pair(stage_def)
                self.assertIsNotNone(actor, f"Actor for {stage_id} should exist")
                self.assertIsNotNone(critic, f"Critic for {stage_id} should exist")

    def test_is_critical_stage(self):
        self.assertTrue(is_critical_stage("idea"))
        self.assertTrue(is_critical_stage("prd"))
        self.assertTrue(is_critical_stage("design"))
        self.assertTrue(is_critical_stage("plan"))
        self.assertTrue(is_critical_stage("coding"))
        self.assertFalse(is_critical_stage("check"))
        self.assertFalse(is_critical_stage("delivery"))
        self.assertFalse(is_critical_stage("nonexistent"))


# ============================================================================
# 3. CollaborationHub + Pipeline 集成测试
# ============================================================================

class TestCollaborationHubPipelineIntegration(unittest.TestCase):

    def setUp(self):
        self.sent_messages = []
        self.status_log = []

        def _capture_send(msg):
            self.sent_messages.append(msg)

        def _mock_send_agent(msg):
            agent_id = msg.get("agent_id", "")
            stage_id = msg.get("stage_id", "")
            return f"[MOCK] {agent_id} completed {stage_id}"

        self.hub = CollaborationHub(send_fn=_capture_send)
        self.mock_send = _mock_send_agent

    def test_collaboration_hub_initialized_properly(self):
        self.assertIsNotNone(self.hub.broadcaster)
        self.assertIsNotNone(self.hub.progress_board)
        self.assertIsNotNone(self.hub.file_lock_manager)
        self.assertIsNotNone(self.hub.dependency_tracker)
        self.assertIsNotNone(self.hub.code_review_manager)
        self.assertIsNotNone(self.hub.integration_checker)

    def test_setup_task_subscribes_participants(self):
        result = self.hub.setup_task(
            task_id="task-001",
            participants=["agent_a", "agent_b", "agent_c"],
        )
        self.assertEqual(len(result["subscribed"]), 3)
        self.assertIn("agent_a", self.hub.broadcaster.subscribers["task-001"])

    def test_setup_task_with_dependencies(self):
        result = self.hub.setup_task(
            task_id="task-002",
            participants=["frontend_agent", "backend_agent"],
            dependencies=[
                {
                    "from_task": "task-002-frontend",
                    "to_task": "task-002-backend",
                    "from_agent": "frontend_agent",
                    "to_agent": "backend_agent",
                    "type": "api",
                    "description": "Backend API needed first",
                },
            ],
        )
        self.assertEqual(len(result["dependencies"]), 1)

    def test_report_progress_updates_board_and_broadcasts(self):
        self.hub.setup_task(task_id="task-003", participants=["agent_x"])
        self.hub.report_progress(
            agent="agent_x",
            task_id="task-003",
            subtask_id="sub-1",
            progress=50,
            status="in_progress",
            current_step="Building UI",
        )
        board = self.hub.progress_board.get_board("task-003")
        self.assertIn("agent_x", board)
        self.assertEqual(board["agent_x"].progress, 50)

    def test_complete_task_unlocks_and_notifies(self):
        self.hub.setup_task(
            task_id="task-004",
            participants=["agent_z"],
            files_to_lock={"agent_z": ["src/main.py"]},
        )
        result = self.hub.complete_task("agent_z", "task-004")
        self.assertEqual(result["task_id"], "task-004")
        locks = self.hub.file_lock_manager.get_agent_locks("agent_z")
        self.assertEqual(len(locks), 0)

    def test_notify_interface_change_broadcasts(self):
        self.hub.setup_task(task_id="task-005", participants=["agent_a", "agent_b"])
        self.hub.notify_interface_change(
            agent="agent_a",
            task_id="task-005",
            change_type="modify",
            interface_name="UserAPI.login",
            old_value="v1/login",
            new_value="v2/auth/login",
            reason="Auth refactor",
        )
        broadcasts = self.hub.broadcaster.broadcasts
        interface_broadcasts = [
            b for b in broadcasts
            if b.type == BroadcastType.INTERFACE_CHANGE
        ]
        self.assertGreater(len(interface_broadcasts), 0)

    def test_pipeline_executor_with_collaboration_hub(self):
        executor = create_standard_pipeline(
            send_message=self.mock_send,
            collaboration_hub=self.hub,
            on_confirmation=lambda sid, preview: ConfirmationAction.PASS,
        )

        self.hub.setup_task(
            task_id="default",
            participants=["idea_agent", "prd_actor", "prd_critic", "coding_actor"],
        )

        async def _run():
            return await executor.execute(
                flow=DEFAULT_FLOW,
                user_input="Build a login page",
            )

        result = asyncio.run(_run())
        self.assertEqual(result.status, "success")
        board = self.hub.progress_board.get_board("default")
        self.assertIn("pipeline", board)

    def test_pipeline_with_tools_registry(self):
        tool_registry = get_pipeline_tool_registry()

        executor = create_standard_pipeline(
            send_message=self.mock_send,
            pipeline_tools=tool_registry,
            on_confirmation=lambda sid, preview: ConfirmationAction.PASS,
        )

        async def _run():
            return await executor.execute(
                flow=DEFAULT_FLOW,
                user_input="Build a todo app with database",
            )

        result = asyncio.run(_run())
        self.assertEqual(result.status, "success")
        self.assertIsNotNone(result.summary)

    def test_full_integration_hub_tools_executor(self):
        tool_registry = get_pipeline_tool_registry()

        executor = create_standard_pipeline(
            send_message=self.mock_send,
            collaboration_hub=self.hub,
            pipeline_tools=tool_registry,
            on_confirmation=lambda sid, preview: ConfirmationAction.PASS,
        )

        self.hub.setup_task(
            task_id="default",
            participants=["idea_agent", "coding_actor", "check_agent", "delivery_agent"],
        )

        async def _run():
            return await executor.execute(user_input="Create a calculator web app")

        result = asyncio.run(_run())
        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.stages), 7)

        board = self.hub.progress_board.get_board("default")
        self.assertIn("pipeline", board)
        pipeline_progress = board["pipeline"]
        self.assertEqual(pipeline_progress.status, "completed")
        self.assertEqual(pipeline_progress.progress, 100)

        self.assertIn("metrics", result.__dict__)
        for stage_id in ["idea", "prd", "design", "plan", "coding", "check", "delivery"]:
            self.assertIn(stage_id, result.stages)


# ============================================================================
# 4. StageAgent 配置验证测试
# ============================================================================

class TestStageAgentsConfig(unittest.TestCase):

    def test_all_stage_ids_in_flow(self):
        expected = ["idea", "prd", "design", "plan", "coding", "check", "delivery"]
        for sid in expected:
            self.assertIsNotNone(get_stage_definition(DEFAULT_FLOW, sid))

    def test_actor_critic_stages_have_actor_and_critic(self):
        for sid in ["prd", "design", "plan", "coding"]:
            stage = get_stage_definition(DEFAULT_FLOW, sid)
            self.assertEqual(stage.stage_type, StageType.ACTOR_CRITIC)
            actor, critic = get_actor_critic_pair(stage)
            self.assertIsNotNone(actor)
            self.assertIsNotNone(critic)
            self.assertEqual(actor.role, AgentRole.ACTOR)
            self.assertEqual(critic.role, AgentRole.CRITIC)

    def test_simple_stages_have_agent(self):
        for sid in ["idea", "check", "delivery"]:
            stage = get_stage_definition(DEFAULT_FLOW, sid)
            self.assertEqual(stage.stage_type, StageType.SIMPLE)
            self.assertIsNotNone(stage.agent)

    def test_quick_flow_has_fewer_stages(self):
        self.assertEqual(len(QUICK_FLOW.stages), 4)
        quick_ids = [s.stage_id for s in QUICK_FLOW.stages]
        self.assertNotIn("idea", quick_ids)
        self.assertNotIn("prd", quick_ids)

    def test_pipeline_agents_11_profiles(self):
        self.assertEqual(len(PIPELINE_AGENTS), 11)
        for agent_id, profile in PIPELINE_AGENTS.items():
            self.assertIsNotNone(profile.name)
            self.assertIsNotNone(profile.role)
            self.assertIsNotNone(profile.stage)
            self.assertGreater(profile.temperature, 0)

    def test_flow_on_success_chain_complete(self):
        current = DEFAULT_FLOW.start_stage
        visited = set()
        while current and current not in visited:
            visited.add(current)
            stage = get_stage_definition(DEFAULT_FLOW, current)
            current = stage.on_success or ""
        self.assertEqual(visited, {"idea", "prd", "design", "plan", "coding", "check", "delivery"})


if __name__ == "__main__":
    unittest.main()
