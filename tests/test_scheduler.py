"""
智能调度器集成测试

测试任务复杂度判断、任务分解、Agent分配和结果聚合的完整流程。
"""

import os
import sys
import unittest

# 确保 src 目录在路径中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from scheduler.complexity import (
    ComplexityJudge,
    ComplexityResult,
    TaskInput,
    judge_complexity,
)
from scheduler.decomposer import (
    DecomposeResult,
    SubTask,
    TaskDecomposer,
)
from scheduler.agents import (
    SPECIALIZED_AGENTS,
    get_agent_profile,
    match_agent_for_task,
    match_agents_for_domains,
)
from scheduler.scheduler import (
    TaskScheduler,
    ScheduleResult,
    schedule_task,
)
from scheduler.aggregator import (
    AgentResult,
    ResultAggregator,
    FinalResult,
    aggregate_results,
)


class TestComplexityJudge(unittest.TestCase):
    """测试复杂度判断器"""

    def test_simple_task(self):
        """测试简单任务判断"""
        result = judge_complexity("修复登录按钮的样式问题")
        self.assertEqual(result.level, "simple")
        self.assertLess(result.score, 0.5)

    def test_complex_task_multi_domain(self):
        """测试跨领域复杂任务"""
        result = judge_complexity(
            "实现用户登录功能，包括前端表单、后端API、数据库模型"
        )
        self.assertEqual(result.level, "complex")
        self.assertGreaterEqual(result.score, 0.5)
        self.assertGreaterEqual(len(result.domains), 2)

    def test_complex_task_with_files(self):
        """测试带文件列表的复杂任务"""
        result = judge_complexity(
            "重构认证模块",
            files=[
                "src/ui/LoginForm.tsx",
                "src/api/auth.py",
                "src/models/user.py",
                "tests/test_auth.py",
            ],
        )
        self.assertEqual(result.level, "complex")

    def test_domain_detection(self):
        """测试领域检测"""
        judge = ComplexityJudge()

        # 前端任务
        task = TaskInput(description="修改 React 组件的 CSS 样式")
        result = judge.judge(task)
        self.assertIn("frontend", result.domains)

        # 后端任务
        task = TaskInput(description="实现新的 API 接口")
        result = judge.judge(task)
        self.assertIn("backend", result.domains)

        # 数据库任务
        task = TaskInput(description="创建用户表的 SQL 迁移脚本")
        result = judge.judge(task)
        self.assertIn("database", result.domains)


class TestTaskDecomposer(unittest.TestCase):
    """测试任务分解器"""

    def setUp(self):
        self.decomposer = TaskDecomposer()

    def test_decompose_multi_domain(self):
        """测试多领域任务分解"""
        task = TaskInput(
            description="实现用户注册功能，包括前端表单、后端验证、数据存储"
        )
        domains = {"frontend", "backend", "database"}

        result = self.decomposer.decompose(task, domains)

        self.assertEqual(len(result.subtasks), 3)
        self.assertIsInstance(result, DecomposeResult)

        # 检查子任务领域
        subtask_domains = {st.domain for st in result.subtasks}
        self.assertEqual(subtask_domains, domains)

    def test_dependency_resolution(self):
        """测试依赖关系解析"""
        task = TaskInput(description="全栈功能开发")
        domains = {"frontend", "backend", "database"}

        result = self.decomposer.decompose(task, domains)

        # 检查依赖图
        self.assertIn(result.subtasks[0].id, result.dependency_graph)

        # 前端应该依赖后端
        frontend_subtask = next(
            st for st in result.subtasks if st.domain == "frontend"
        )
        backend_subtask = next(
            st for st in result.subtasks if st.domain == "backend"
        )
        self.assertIn(backend_subtask.id, frontend_subtask.dependencies)

    def test_execution_order(self):
        """测试执行顺序计算"""
        task = TaskInput(description="完整功能开发")
        domains = {"frontend", "backend", "database"}

        result = self.decomposer.decompose(task, domains)

        # 应该有多个执行阶段
        self.assertGreater(len(result.execution_order), 0)

        # 数据库应该在第一阶段
        first_layer = result.execution_order[0]
        db_subtask = next(
            st for st in result.subtasks if st.domain == "database"
        )
        self.assertIn(db_subtask.id, first_layer)


class TestAgentConfig(unittest.TestCase):
    """测试专用Agent配置"""

    def test_agent_profiles(self):
        """测试Agent配置文件"""
        self.assertIn("A", SPECIALIZED_AGENTS)
        self.assertIn("B", SPECIALIZED_AGENTS)
        self.assertIn("C", SPECIALIZED_AGENTS)
        self.assertIn("D", SPECIALIZED_AGENTS)

        # 检查前端专家配置
        a_profile = get_agent_profile("A")
        self.assertEqual(a_profile.specialty, "frontend")
        self.assertIn("frontend", a_profile.domains)

        # 检查辅助Agent
        d_profile = get_agent_profile("D")
        self.assertTrue(d_profile.is_helper)

    def test_match_agent_for_task(self):
        """测试任务到Agent的匹配"""
        # 前端任务
        frontend_task = SubTask(
            id="test-frontend",
            domain="frontend",
            description="修改 UI 组件",
        )
        self.assertEqual(match_agent_for_task(frontend_task), "A")

        # 后端任务
        backend_task = SubTask(
            id="test-backend",
            domain="backend",
            description="实现 API",
        )
        self.assertEqual(match_agent_for_task(backend_task), "B")

        # 数据库任务
        db_task = SubTask(
            id="test-db",
            domain="database",
            description="创建数据模型",
        )
        self.assertEqual(match_agent_for_task(db_task), "C")

    def test_match_agents_for_domains(self):
        """测试多领域Agent匹配"""
        domains = {"frontend", "backend", "database"}
        assignments = match_agents_for_domains(domains)

        self.assertEqual(len(assignments), 3)
        self.assertEqual(assignments["frontend"], "A")
        self.assertEqual(assignments["backend"], "B")
        self.assertEqual(assignments["database"], "C")


class TestTaskScheduler(unittest.TestCase):
    """测试任务调度器"""

    def setUp(self):
        self.scheduler = TaskScheduler()

    def test_schedule_simple_task(self):
        """测试简单任务调度"""
        task = TaskInput(description="修复按钮颜色")
        result = self.scheduler.schedule(task)

        self.assertEqual(result.mode, "single")
        self.assertEqual(len(result.assignments), 1)

    def test_schedule_complex_task(self):
        """测试复杂任务调度"""
        task = TaskInput(
            description="实现完整的用户认证系统，包括前端登录页面、后端API、数据库用户表"
        )
        result = self.scheduler.schedule(task)

        self.assertEqual(result.mode, "parallel")
        self.assertGreater(len(result.assignments), 1)
        self.assertIsNotNone(result.decompose_result)

    def test_schedule_task_shortcut(self):
        """测试快捷函数"""
        result = schedule_task("修复 CSS 样式问题")
        self.assertIsInstance(result, ScheduleResult)

    def test_schedule_result_summary(self):
        """测试调度结果摘要"""
        task = TaskInput(description="全栈功能开发，前端后端数据库")
        result = self.scheduler.schedule(task)

        self.assertIn("任务调度结果", result.summary)
        # 摘要中使用中文描述，不直接包含 mode 值
        if result.mode == "parallel":
            self.assertIn("并行", result.summary)
        else:
            self.assertIn("单Agent", result.summary)


class TestResultAggregator(unittest.TestCase):
    """测试结果聚合器"""

    def test_aggregate_all_success(self):
        """测试全部成功的聚合"""
        results = [
            AgentResult(task_id="t1", agent="A", status="done", summary="前端完成"),
            AgentResult(task_id="t2", agent="B", status="done", summary="后端完成"),
            AgentResult(task_id="t3", agent="C", status="done", summary="数据库完成"),
        ]

        final = aggregate_results(results, "parent-task")

        self.assertEqual(final.status, "success")
        self.assertEqual(final.success_count, 3)
        self.assertEqual(final.fail_count, 0)

    def test_aggregate_partial_success(self):
        """测试部分成功的聚合"""
        results = [
            AgentResult(task_id="t1", agent="A", status="done"),
            AgentResult(task_id="t2", agent="B", status="fail", error="编译错误"),
        ]

        final = aggregate_results(results)

        self.assertEqual(final.status, "partial")
        self.assertEqual(final.success_count, 1)
        self.assertEqual(final.fail_count, 1)

    def test_aggregate_all_failed(self):
        """测试全部失败的聚合"""
        results = [
            AgentResult(task_id="t1", agent="A", status="fail"),
            AgentResult(task_id="t2", agent="B", status="timeout"),
        ]

        final = aggregate_results(results)

        self.assertEqual(final.status, "failed")

    def test_conflict_detection(self):
        """测试冲突检测"""
        results = [
            AgentResult(
                task_id="t1",
                agent="A",
                status="done",
                changes=["src/common.py"],
            ),
            AgentResult(
                task_id="t2",
                agent="B",
                status="done",
                changes=["src/common.py", "src/api.py"],
            ),
        ]

        aggregator = ResultAggregator()
        final = aggregator.aggregate(results)

        # 应该检测到 src/common.py 被多个 Agent 修改
        self.assertGreater(len(final.conflicts), 0)
        conflict_files = [c.file_path for c in final.conflicts]
        self.assertIn("src/common.py", conflict_files)


class TestEndToEndScheduling(unittest.TestCase):
    """端到端调度测试"""

    def test_full_workflow_simple(self):
        """测试简单任务的完整流程"""
        # 1. 创建任务
        description = "修复首页 Banner 的显示问题"

        # 2. 调度
        result = schedule_task(description)

        # 3. 验证
        self.assertEqual(result.mode, "single")
        self.assertEqual(result.complexity.level, "simple")
        self.assertEqual(len(result.assignments), 1)

    def test_full_workflow_complex(self):
        """测试复杂任务的完整流程"""
        # 1. 创建任务
        description = """
        实现订单管理系统：
        - 前端：订单列表页面、订单详情页面
        - 后端：订单 CRUD API、状态流转逻辑
        - 数据库：订单表、订单项表
        - 测试：单元测试和集成测试
        """

        # 2. 调度
        result = schedule_task(description)

        # 3. 验证
        self.assertEqual(result.mode, "parallel")
        self.assertEqual(result.complexity.level, "complex")
        self.assertGreaterEqual(len(result.assignments), 3)

        # 4. 检查分配
        agents_assigned = {a.agent for a in result.assignments}
        # 应该分配给多个 Agent
        self.assertGreaterEqual(len(agents_assigned), 2)

        # 5. 检查执行顺序
        self.assertIsNotNone(result.decompose_result)
        self.assertGreater(len(result.decompose_result.execution_order), 0)


if __name__ == "__main__":
    unittest.main()
