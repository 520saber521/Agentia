"""
任务复杂度判断器

根据任务特征自动判断任务是简单任务还是复杂任务，决定使用单Agent还是多Agent协作。
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class TaskInput:
    """任务输入"""
    description: str
    files: List[str] = field(default_factory=list)
    context: Optional[str] = None
    hints: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ComplexityResult:
    """复杂度判断结果"""
    level: str  # "simple" | "complex"
    score: float  # 0.0 - 1.0
    reasons: List[str] = field(default_factory=list)
    domains: Set[str] = field(default_factory=set)
    estimated_files: int = 0
    parallelizable: bool = False


# 领域关键词映射
DOMAIN_KEYWORDS = {
    "frontend": [
        "前端", "ui", "界面", "组件", "react", "vue", "css", "html",
        "样式", "布局", "表单", "按钮", "页面", "视图", "交互",
        ".tsx", ".jsx", ".css", ".scss", ".html", "component",
    ],
    "backend": [
        "后端", "api", "接口", "服务", "路由", "控制器", "handler",
        "server", "endpoint", "rest", "graphql", "业务逻辑",
        ".py", "router", "service", "controller",
    ],
    "database": [
        "数据库", "数据", "模型", "表", "sql", "存储", "持久化",
        "migration", "schema", "orm", "query", "索引",
        ".sql", "model", "storage", "repository",
    ],
    "test": [
        "测试", "test", "单元测试", "集成测试", "e2e", "mock",
        "assert", "expect", "spec", "fixture",
        "test_", "_test.py", ".test.", ".spec.",
    ],
    "docs": [
        "文档", "readme", "doc", "说明", "注释", "api文档",
        ".md", "documentation", "comment",
    ],
    "devops": [
        "部署", "ci", "cd", "docker", "kubernetes", "配置",
        "dockerfile", ".yaml", ".yml", "pipeline",
    ],
}

# 复杂度关键词
COMPLEXITY_KEYWORDS = {
    "high": [
        "重构", "架构", "系统", "全面", "完整", "迁移",
        "优化性能", "安全", "认证", "授权", "并发",
        "分布式", "微服务", "集成",
    ],
    "medium": [
        "功能", "模块", "接口", "api", "增删改查",
        "表单", "列表", "详情",
    ],
    "low": [
        "修复", "bug", "typo", "简单", "小改动",
        "注释", "格式", "重命名",
    ],
}


class ComplexityJudge:
    """复杂度判断器"""

    def __init__(
        self,
        simple_max_files: int = 2,
        simple_max_domains: int = 1,
        complex_min_files: int = 3,
        complex_min_domains: int = 2,
    ):
        self.simple_max_files = simple_max_files
        self.simple_max_domains = simple_max_domains
        self.complex_min_files = complex_min_files
        self.complex_min_domains = complex_min_domains

    def judge(self, task: TaskInput) -> ComplexityResult:
        """
        判断任务复杂度

        Args:
            task: 任务输入

        Returns:
            ComplexityResult: 复杂度判断结果
        """
        reasons = []
        score = 0.0

        # 1. 分析涉及的领域
        domains = self._detect_domains(task)
        domain_count = len(domains)

        if domain_count >= self.complex_min_domains:
            score += 0.3
            reasons.append(f"跨{domain_count}个领域: {', '.join(domains)}")
        elif domain_count == 1:
            reasons.append(f"单一领域: {', '.join(domains)}")

        # 2. 估算涉及文件数
        estimated_files = self._estimate_files(task, domains)

        if estimated_files >= self.complex_min_files:
            score += 0.3
            reasons.append(f"预估涉及{estimated_files}个文件")
        elif estimated_files <= self.simple_max_files:
            reasons.append(f"预估仅涉及{estimated_files}个文件")

        # 3. 分析复杂度关键词
        keyword_score, keyword_reasons = self._analyze_keywords(task)
        score += keyword_score
        reasons.extend(keyword_reasons)

        # 4. 检查是否可并行
        parallelizable = domain_count >= 2 or estimated_files >= 3

        if parallelizable:
            score += 0.1
            reasons.append("任务可并行分解")

        # 5. 检查显式文件列表
        if task.files:
            file_domains = self._detect_file_domains(task.files)
            if len(file_domains) >= 2:
                score += 0.2
                reasons.append(f"文件跨越领域: {', '.join(file_domains)}")

        # 6. 判断最终结果
        level = "complex" if score >= 0.5 else "simple"

        return ComplexityResult(
            level=level,
            score=min(1.0, score),
            reasons=reasons,
            domains=domains,
            estimated_files=estimated_files,
            parallelizable=parallelizable,
        )

    def _detect_domains(self, task: TaskInput) -> Set[str]:
        """检测任务涉及的领域"""
        text = f"{task.description} {task.context or ''}".lower()
        domains = set()

        for domain, keywords in DOMAIN_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in text:
                    domains.add(domain)
                    break

        # 如果没有检测到，默认为 backend
        if not domains:
            domains.add("backend")

        return domains

    def _detect_file_domains(self, files: List[str]) -> Set[str]:
        """根据文件列表检测领域"""
        domains = set()
        for file_path in files:
            file_lower = file_path.lower()
            for domain, keywords in DOMAIN_KEYWORDS.items():
                for keyword in keywords:
                    if keyword.lower() in file_lower:
                        domains.add(domain)
                        break
        return domains

    def _estimate_files(self, task: TaskInput, domains: Set[str]) -> int:
        """估算涉及的文件数"""
        if task.files:
            return len(task.files)

        # 根据领域和描述长度估算
        base_count = len(domains) * 2
        desc_length = len(task.description)

        if desc_length > 200:
            base_count += 2
        elif desc_length > 100:
            base_count += 1

        # 检查是否提到多个组件
        component_patterns = [
            r"(\d+)\s*个",
            r"多个",
            r"几个",
            r"各个",
        ]
        text = task.description
        for pattern in component_patterns:
            match = re.search(pattern, text)
            if match:
                if match.groups():
                    try:
                        base_count = max(base_count, int(match.group(1)))
                    except ValueError:
                        pass
                else:
                    base_count = max(base_count, 3)

        return base_count

    def _analyze_keywords(self, task: TaskInput) -> tuple:
        """分析复杂度关键词"""
        text = f"{task.description} {task.context or ''}".lower()
        score = 0.0
        reasons = []

        # 检查高复杂度关键词
        for keyword in COMPLEXITY_KEYWORDS["high"]:
            if keyword.lower() in text:
                score += 0.15
                reasons.append(f"涉及复杂操作: {keyword}")
                break

        # 检查低复杂度关键词
        for keyword in COMPLEXITY_KEYWORDS["low"]:
            if keyword.lower() in text:
                score -= 0.1
                reasons.append(f"简单任务标识: {keyword}")
                break

        return score, reasons


def judge_complexity(
    task_description: str,
    files: Optional[List[str]] = None,
    context: Optional[str] = None,
    **kwargs
) -> ComplexityResult:
    """
    快捷函数：判断任务复杂度

    Args:
        task_description: 任务描述
        files: 涉及的文件列表
        context: 上下文信息

    Returns:
        ComplexityResult: 复杂度判断结果

    Example:
        >>> result = judge_complexity("修复登录按钮样式问题")
        >>> print(result.level)  # "simple"

        >>> result = judge_complexity(
        ...     "实现用户登录功能，包括前端表单、后端API、数据库模型"
        ... )
        >>> print(result.level)  # "complex"
    """
    task = TaskInput(
        description=task_description,
        files=files or [],
        context=context,
        hints=kwargs,
    )
    judge = ComplexityJudge()
    return judge.judge(task)
