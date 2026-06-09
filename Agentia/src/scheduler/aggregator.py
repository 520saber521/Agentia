"""
结果聚合器

收集并聚合多个Agent的执行结果，处理冲突检测和最终汇总。
"""

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set


@dataclass
class AgentResult:
    """Agent执行结果"""
    task_id: str
    agent: str
    status: str  # done, fail, timeout
    message: Optional[Dict[str, Any]] = None
    changes: List[str] = field(default_factory=list)
    summary: str = ""
    error: Optional[str] = None
    timestamp: int = 0


@dataclass
class Conflict:
    """冲突信息"""
    file_path: str
    agents: List[str]
    description: str
    severity: str = "warning"  # warning, error


@dataclass
class FinalResult:
    """最终聚合结果"""
    task_id: str
    status: str  # success, partial, failed
    total_count: int
    success_count: int
    fail_count: int
    timeout_count: int
    results: List[AgentResult] = field(default_factory=list)
    conflicts: List[Conflict] = field(default_factory=list)
    all_changes: List[str] = field(default_factory=list)
    summary: str = ""
    duration_ms: int = 0


class ResultAggregator:
    """结果聚合器"""

    def __init__(
        self,
        router_client: Optional[Any] = None,
        poll_interval: float = 1.0,
        default_timeout: int = 3600,
    ):
        """
        初始化聚合器

        Args:
            router_client: Router客户端
            poll_interval: 轮询间隔（秒）
            default_timeout: 默认超时时间（秒）
        """
        self.client = router_client
        self.poll_interval = poll_interval
        self.default_timeout = default_timeout

    def wait_for_results(
        self,
        task_ids: List[str],
        timeout: Optional[int] = None,
        trace_fn: Optional[Callable] = None,
    ) -> List[AgentResult]:
        """
        等待所有子任务完成

        Args:
            task_ids: 任务ID列表
            timeout: 超时时间（秒）
            trace_fn: 追踪函数（用于获取任务状态）

        Returns:
            List[AgentResult]: 结果列表
        """
        if trace_fn is None and self.client:
            trace_fn = lambda tid: self.client.trace(task_id=tid)

        if trace_fn is None:
            # 无法追踪，返回空结果
            return [
                AgentResult(
                    task_id=tid,
                    agent=self._extract_agent_from_task_id(tid),
                    status="unknown",
                    summary="无法追踪任务状态",
                )
                for tid in task_ids
            ]

        timeout = timeout or self.default_timeout
        deadline = time.time() + timeout
        start_time = time.time()

        results: Dict[str, AgentResult] = {}
        pending = set(task_ids)

        while pending and time.time() < deadline:
            for task_id in list(pending):
                try:
                    trace = trace_fn(task_id)
                    result = self._parse_trace_result(task_id, trace)

                    if result and result.status in ("done", "fail"):
                        results[task_id] = result
                        pending.remove(task_id)
                except Exception as e:
                    # 忽略单个任务的错误，继续轮询
                    pass

            if pending:
                time.sleep(self.poll_interval)

        # 处理超时的任务
        for task_id in pending:
            results[task_id] = AgentResult(
                task_id=task_id,
                agent=self._extract_agent_from_task_id(task_id),
                status="timeout",
                summary="任务超时未完成",
                timestamp=int(time.time() * 1000),
            )

        return list(results.values())

    def aggregate(
        self,
        results: List[AgentResult],
        parent_task_id: str = "",
    ) -> FinalResult:
        """
        聚合所有结果

        Args:
            results: Agent结果列表
            parent_task_id: 父任务ID

        Returns:
            FinalResult: 最终结果
        """
        success_count = sum(1 for r in results if r.status == "done")
        fail_count = sum(1 for r in results if r.status == "fail")
        timeout_count = sum(1 for r in results if r.status == "timeout")

        # 收集所有变更
        all_changes = []
        for result in results:
            all_changes.extend(result.changes)

        # 检测冲突
        conflicts = self._detect_conflicts(results)

        # 确定最终状态
        if fail_count == 0 and timeout_count == 0:
            status = "success"
        elif success_count > 0:
            status = "partial"
        else:
            status = "failed"

        # 生成摘要
        summary = self._generate_summary(results, conflicts)

        return FinalResult(
            task_id=parent_task_id,
            status=status,
            total_count=len(results),
            success_count=success_count,
            fail_count=fail_count,
            timeout_count=timeout_count,
            results=results,
            conflicts=conflicts,
            all_changes=list(set(all_changes)),
            summary=summary,
        )

    def _parse_trace_result(
        self, task_id: str, trace: Dict[str, Any]
    ) -> Optional[AgentResult]:
        """解析追踪结果"""
        messages = trace.get("messages", [])

        for msg in messages:
            msg_type = msg.get("type")
            if msg_type in ("done", "fail"):
                # 解析body
                body = msg.get("body", "{}")
                if isinstance(body, str):
                    try:
                        body_data = json.loads(body)
                    except json.JSONDecodeError:
                        body_data = {"raw": body}
                else:
                    body_data = body

                return AgentResult(
                    task_id=task_id,
                    agent=msg.get("from", ""),
                    status=msg_type,
                    message=msg,
                    changes=body_data.get("changes", []),
                    summary=body_data.get("summary", ""),
                    error=body_data.get("reason") if msg_type == "fail" else None,
                    timestamp=msg.get("ts", 0),
                )

        return None

    def _detect_conflicts(self, results: List[AgentResult]) -> List[Conflict]:
        """检测文件冲突"""
        conflicts = []

        # 收集每个文件被哪些Agent修改
        file_agents: Dict[str, List[str]] = {}
        for result in results:
            for change in result.changes:
                if change not in file_agents:
                    file_agents[change] = []
                file_agents[change].append(result.agent)

        # 找出被多个Agent修改的文件
        for file_path, agents in file_agents.items():
            if len(agents) > 1:
                conflicts.append(Conflict(
                    file_path=file_path,
                    agents=agents,
                    description=f"文件 {file_path} 被多个Agent修改: {', '.join(agents)}",
                    severity="warning",
                ))

        return conflicts

    def _generate_summary(
        self, results: List[AgentResult], conflicts: List[Conflict]
    ) -> str:
        """生成聚合摘要"""
        lines = ["=== 执行结果汇总 ==="]

        # 状态统计
        success = [r for r in results if r.status == "done"]
        failed = [r for r in results if r.status == "fail"]
        timeout = [r for r in results if r.status == "timeout"]

        lines.append(f"总计: {len(results)} 个子任务")
        lines.append(f"  成功: {len(success)}")
        lines.append(f"  失败: {len(failed)}")
        lines.append(f"  超时: {len(timeout)}")

        # 各Agent结果
        lines.append("")
        lines.append("各Agent执行情况:")
        for result in results:
            status_icon = "✓" if result.status == "done" else "✗"
            lines.append(f"  [{status_icon}] {result.agent}: {result.status}")
            if result.summary:
                lines.append(f"      {result.summary[:50]}...")
            if result.error:
                lines.append(f"      错误: {result.error[:50]}...")

        # 冲突警告
        if conflicts:
            lines.append("")
            lines.append(f"⚠ 发现 {len(conflicts)} 个潜在冲突:")
            for conflict in conflicts:
                lines.append(f"  - {conflict.description}")

        return "\n".join(lines)

    def _extract_agent_from_task_id(self, task_id: str) -> str:
        """从任务ID中提取Agent角色"""
        # 假设格式为 PARENT-DOMAIN 或 PARENT-AGENT
        parts = task_id.split("-")
        if len(parts) >= 2:
            last_part = parts[-1].upper()
            if last_part in ("A", "B", "C", "D"):
                return last_part
            # 尝试从领域推断
            domain_map = {
                "FRONTEND": "A",
                "BACKEND": "B",
                "DATABASE": "C",
                "TEST": "D",
                "DOCS": "D",
            }
            return domain_map.get(last_part, "B")
        return "B"


def aggregate_results(
    results: List[AgentResult],
    parent_task_id: str = "",
) -> FinalResult:
    """
    快捷函数：聚合结果

    Args:
        results: Agent结果列表
        parent_task_id: 父任务ID

    Returns:
        FinalResult: 最终结果
    """
    aggregator = ResultAggregator()
    return aggregator.aggregate(results, parent_task_id)


def wait_and_aggregate(
    task_ids: List[str],
    router_client: Any,
    timeout: int = 3600,
    parent_task_id: str = "",
) -> FinalResult:
    """
    等待并聚合结果

    Args:
        task_ids: 任务ID列表
        router_client: Router客户端
        timeout: 超时时间
        parent_task_id: 父任务ID

    Returns:
        FinalResult: 最终结果
    """
    aggregator = ResultAggregator(router_client=router_client)
    results = aggregator.wait_for_results(task_ids, timeout=timeout)
    return aggregator.aggregate(results, parent_task_id)
