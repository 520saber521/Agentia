"""
需求分析与设计模块

核心理念：
1. 设计是最关键的一步 - 设计错了，后面做的都是白费
2. 必须与用户需求对齐 - 设计完成后要与用户确认
3. 新项目需要完整设计流程

流程：
用户需求 → 需求澄清 → 架构设计 → 用户确认 → 分解执行
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from enum import Enum
import time


class ProjectType(Enum):
    """项目类型"""
    NEW = "new"           # 新项目 - 需要完整设计
    EXISTING = "existing" # 已有项目 - 基于现有架构
    REFACTOR = "refactor" # 重构 - 需要分析现有代码


class DesignStatus(Enum):
    """设计状态"""
    DRAFT = "draft"               # 草稿 - 待完善
    PENDING_REVIEW = "pending"    # 待审核 - 等待用户确认
    APPROVED = "approved"         # 已批准 - 可以开始实现
    REJECTED = "rejected"         # 被拒绝 - 需要重新设计
    NEEDS_CLARIFY = "clarify"     # 需要澄清 - 有不清楚的地方


@dataclass
class Requirement:
    """需求项"""
    id: str
    description: str
    priority: str = "medium"      # high, medium, low
    category: str = "functional"  # functional, non-functional, constraint
    acceptance_criteria: List[str] = field(default_factory=list)
    questions: List[str] = field(default_factory=list)  # 待澄清的问题
    answered: bool = False


@dataclass
class ArchitectureComponent:
    """架构组件"""
    name: str
    type: str  # frontend, backend, database, service, external
    description: str
    technologies: List[str] = field(default_factory=list)
    responsibilities: List[str] = field(default_factory=list)
    interfaces: List[str] = field(default_factory=list)  # 提供的接口


@dataclass
class DataEntity:
    """数据实体"""
    name: str
    description: str
    fields: List[Dict[str, Any]] = field(default_factory=list)
    relationships: List[str] = field(default_factory=list)


@dataclass
class APIEndpoint:
    """API 接口设计"""
    method: str
    path: str
    description: str
    request_schema: Optional[str] = None
    response_schema: Optional[str] = None
    auth_required: bool = True


@dataclass
class UIScreen:
    """UI 页面/屏幕"""
    name: str
    path: str  # 路由路径
    description: str
    components: List[str] = field(default_factory=list)
    data_needs: List[str] = field(default_factory=list)  # 需要的数据


@dataclass
class DesignDocument:
    """设计文档"""
    project_name: str
    project_type: ProjectType
    status: DesignStatus
    
    # 需求
    requirements: List[Requirement] = field(default_factory=list)
    
    # 架构
    architecture_overview: str = ""
    components: List[ArchitectureComponent] = field(default_factory=list)
    
    # 数据设计
    entities: List[DataEntity] = field(default_factory=list)
    
    # API 设计
    api_endpoints: List[APIEndpoint] = field(default_factory=list)
    
    # UI 设计
    screens: List[UIScreen] = field(default_factory=list)
    
    # 技术栈
    tech_stack: Dict[str, str] = field(default_factory=dict)
    
    # 用户反馈
    user_feedback: List[str] = field(default_factory=list)
    clarification_questions: List[str] = field(default_factory=list)
    
    # 元数据
    created_at: int = 0
    updated_at: int = 0
    version: int = 1


class RequirementAnalyzer:
    """需求分析器"""
    
    def analyze(self, user_input: str) -> List[Requirement]:
        """
        分析用户输入，提取需求项
        
        Args:
            user_input: 用户的需求描述
            
        Returns:
            List[Requirement]: 需求列表
        """
        requirements = []
        
        # 提取功能性需求
        functional_reqs = self._extract_functional_requirements(user_input)
        requirements.extend(functional_reqs)
        
        # 提取非功能性需求
        non_functional_reqs = self._extract_non_functional_requirements(user_input)
        requirements.extend(non_functional_reqs)
        
        # 生成待澄清问题
        for req in requirements:
            req.questions = self._generate_clarification_questions(req)
        
        return requirements
    
    def _extract_functional_requirements(self, text: str) -> List[Requirement]:
        """提取功能性需求"""
        requirements = []
        
        # 关键词映射到需求
        feature_keywords = {
            "登录": {
                "desc": "用户登录功能",
                "criteria": ["用户可以使用用户名密码登录", "登录失败显示错误信息", "登录成功跳转到主页"],
            },
            "注册": {
                "desc": "用户注册功能",
                "criteria": ["用户可以注册新账号", "用户名不能重复", "密码强度校验"],
            },
            "列表": {
                "desc": "数据列表展示",
                "criteria": ["支持分页", "支持排序", "支持搜索/筛选"],
            },
            "详情": {
                "desc": "详情页面展示",
                "criteria": ["展示完整信息", "支持编辑/删除操作"],
            },
            "增删改查": {
                "desc": "CRUD 操作",
                "criteria": ["创建数据", "读取数据", "更新数据", "删除数据"],
            },
            "权限": {
                "desc": "权限管理",
                "criteria": ["角色定义", "权限分配", "访问控制"],
            },
            "搜索": {
                "desc": "搜索功能",
                "criteria": ["关键词搜索", "高级筛选", "搜索结果高亮"],
            },
        }
        
        text_lower = text.lower()
        req_id = 1
        
        for keyword, info in feature_keywords.items():
            if keyword in text_lower:
                requirements.append(Requirement(
                    id=f"REQ-FUNC-{req_id:03d}",
                    description=info["desc"],
                    priority="high" if keyword in ["登录", "注册"] else "medium",
                    category="functional",
                    acceptance_criteria=info["criteria"],
                ))
                req_id += 1
        
        return requirements
    
    def _extract_non_functional_requirements(self, text: str) -> List[Requirement]:
        """提取非功能性需求"""
        requirements = []
        text_lower = text.lower()
        req_id = 1
        
        # 性能要求
        if any(kw in text_lower for kw in ["快", "性能", "响应", "高并发"]):
            requirements.append(Requirement(
                id=f"REQ-NFR-{req_id:03d}",
                description="性能要求",
                category="non-functional",
                acceptance_criteria=["页面加载时间 < 2秒", "API 响应时间 < 500ms"],
            ))
            req_id += 1
        
        # 安全要求
        if any(kw in text_lower for kw in ["安全", "加密", "认证", "授权"]):
            requirements.append(Requirement(
                id=f"REQ-NFR-{req_id:03d}",
                description="安全要求",
                category="non-functional",
                acceptance_criteria=["密码加密存储", "Token 认证", "防止 SQL 注入"],
            ))
            req_id += 1
        
        # 响应式设计
        if any(kw in text_lower for kw in ["手机", "移动端", "响应式", "适配"]):
            requirements.append(Requirement(
                id=f"REQ-NFR-{req_id:03d}",
                description="响应式设计",
                category="non-functional",
                acceptance_criteria=["支持桌面端", "支持移动端", "自适应布局"],
            ))
            req_id += 1
        
        return requirements
    
    def _generate_clarification_questions(self, req: Requirement) -> List[str]:
        """生成澄清问题"""
        questions = []
        
        if "登录" in req.description:
            questions.extend([
                "是否需要第三方登录（微信、Google 等）？",
                "是否需要记住密码功能？",
                "登录失败是否需要锁定账号？",
            ])
        elif "权限" in req.description:
            questions.extend([
                "有哪些角色？各自的权限是什么？",
                "权限是基于角色还是基于资源？",
            ])
        elif "列表" in req.description:
            questions.extend([
                "每页显示多少条数据？",
                "需要支持哪些排序字段？",
                "需要支持哪些筛选条件？",
            ])
        
        return questions


class ArchitectureDesigner:
    """架构设计器"""
    
    def design(
        self,
        requirements: List[Requirement],
        project_type: ProjectType,
    ) -> tuple:
        """
        根据需求设计架构
        
        Returns:
            (overview, components, tech_stack)
        """
        # 分析需要的组件
        components = self._design_components(requirements)
        
        # 选择技术栈
        tech_stack = self._select_tech_stack(requirements, project_type)
        
        # 生成架构概述
        overview = self._generate_overview(components, tech_stack)
        
        return overview, components, tech_stack
    
    def _design_components(self, requirements: List[Requirement]) -> List[ArchitectureComponent]:
        """设计架构组件"""
        components = []
        
        # 根据需求判断需要哪些组件
        has_ui = any("页面" in r.description or "界面" in r.description 
                     or "列表" in r.description or "表单" in r.description
                     for r in requirements)
        has_api = any("api" in r.description.lower() or "接口" in r.description 
                      for r in requirements) or has_ui
        has_db = any("数据" in r.description or "存储" in r.description 
                     or "用户" in r.description 
                     for r in requirements)
        has_auth = any("登录" in r.description or "认证" in r.description 
                       or "权限" in r.description 
                       for r in requirements)
        
        # 前端组件
        if has_ui or True:  # 大多数项目都需要前端
            components.append(ArchitectureComponent(
                name="Frontend",
                type="frontend",
                description="Web 前端应用",
                technologies=["React", "TypeScript", "TailwindCSS"],
                responsibilities=["用户界面展示", "用户交互处理", "状态管理"],
                interfaces=["HTTP API 调用"],
            ))
        
        # 后端 API
        if has_api or True:
            components.append(ArchitectureComponent(
                name="Backend API",
                type="backend",
                description="后端 API 服务",
                technologies=["Python", "FastAPI"],
                responsibilities=["业务逻辑处理", "数据验证", "API 接口"],
                interfaces=["REST API"],
            ))
        
        # 数据库
        if has_db or True:
            components.append(ArchitectureComponent(
                name="Database",
                type="database",
                description="数据存储",
                technologies=["PostgreSQL", "SQLAlchemy"],
                responsibilities=["数据持久化", "数据查询"],
                interfaces=["SQL"],
            ))
        
        # 认证服务
        if has_auth:
            components.append(ArchitectureComponent(
                name="Auth Service",
                type="service",
                description="认证授权服务",
                technologies=["JWT", "OAuth2"],
                responsibilities=["用户认证", "Token 管理", "权限验证"],
                interfaces=["Auth API"],
            ))
        
        return components
    
    def _select_tech_stack(
        self,
        requirements: List[Requirement],
        project_type: ProjectType,
    ) -> Dict[str, str]:
        """选择技术栈"""
        # 默认技术栈
        stack = {
            "frontend_framework": "React",
            "frontend_language": "TypeScript",
            "frontend_style": "TailwindCSS",
            "backend_framework": "FastAPI",
            "backend_language": "Python",
            "database": "PostgreSQL",
            "orm": "SQLAlchemy",
            "auth": "JWT",
            "api_style": "REST",
        }
        
        # 根据需求调整
        for req in requirements:
            if "实时" in req.description or "推送" in req.description:
                stack["realtime"] = "WebSocket"
            if "文件" in req.description or "上传" in req.description:
                stack["storage"] = "S3 / MinIO"
            if "缓存" in req.description or "性能" in req.description:
                stack["cache"] = "Redis"
        
        return stack
    
    def _generate_overview(
        self,
        components: List[ArchitectureComponent],
        tech_stack: Dict[str, str],
    ) -> str:
        """生成架构概述"""
        lines = [
            "## 系统架构概述",
            "",
            "本系统采用前后端分离架构：",
            "",
        ]
        
        for comp in components:
            techs = ", ".join(comp.technologies)
            lines.append(f"- **{comp.name}**: {comp.description} ({techs})")
        
        lines.extend([
            "",
            "### 技术栈",
            "",
        ])
        
        for key, value in tech_stack.items():
            lines.append(f"- {key}: {value}")
        
        return "\n".join(lines)


class DataDesigner:
    """数据设计器"""
    
    def design(self, requirements: List[Requirement]) -> List[DataEntity]:
        """根据需求设计数据模型"""
        entities = []
        
        # 提取实体
        entity_keywords = {
            "用户": DataEntity(
                name="User",
                description="用户",
                fields=[
                    {"name": "id", "type": "uuid", "pk": True},
                    {"name": "username", "type": "string", "unique": True},
                    {"name": "email", "type": "string", "unique": True},
                    {"name": "password_hash", "type": "string"},
                    {"name": "created_at", "type": "datetime"},
                    {"name": "updated_at", "type": "datetime"},
                ],
            ),
            "订单": DataEntity(
                name="Order",
                description="订单",
                fields=[
                    {"name": "id", "type": "uuid", "pk": True},
                    {"name": "user_id", "type": "uuid", "fk": "User.id"},
                    {"name": "status", "type": "enum", "values": ["pending", "paid", "shipped", "completed"]},
                    {"name": "total_amount", "type": "decimal"},
                    {"name": "created_at", "type": "datetime"},
                ],
                relationships=["User"],
            ),
            "商品": DataEntity(
                name="Product",
                description="商品",
                fields=[
                    {"name": "id", "type": "uuid", "pk": True},
                    {"name": "name", "type": "string"},
                    {"name": "description", "type": "text"},
                    {"name": "price", "type": "decimal"},
                    {"name": "stock", "type": "integer"},
                ],
            ),
            "文章": DataEntity(
                name="Article",
                description="文章",
                fields=[
                    {"name": "id", "type": "uuid", "pk": True},
                    {"name": "title", "type": "string"},
                    {"name": "content", "type": "text"},
                    {"name": "author_id", "type": "uuid", "fk": "User.id"},
                    {"name": "status", "type": "enum", "values": ["draft", "published"]},
                    {"name": "created_at", "type": "datetime"},
                ],
                relationships=["User"],
            ),
        }
        
        for req in requirements:
            for keyword, entity in entity_keywords.items():
                if keyword in req.description and entity not in entities:
                    entities.append(entity)
        
        # 如果有登录需求但没有用户实体，添加用户实体
        has_auth = any("登录" in r.description or "注册" in r.description for r in requirements)
        has_user = any(e.name == "User" for e in entities)
        if has_auth and not has_user:
            entities.insert(0, entity_keywords["用户"])
        
        return entities


class DesignGenerator:
    """设计文档生成器"""
    
    def __init__(self):
        self.requirement_analyzer = RequirementAnalyzer()
        self.architecture_designer = ArchitectureDesigner()
        self.data_designer = DataDesigner()
    
    def generate(
        self,
        user_input: str,
        project_name: str = "新项目",
        project_type: ProjectType = ProjectType.NEW,
    ) -> DesignDocument:
        """
        根据用户输入生成设计文档
        
        这是最关键的一步！设计文档需要：
        1. 准确理解用户需求
        2. 列出所有待澄清的问题
        3. 设计合理的架构
        4. 等待用户确认后才能进入实现
        """
        now = int(time.time() * 1000)
        
        # 1. 分析需求
        requirements = self.requirement_analyzer.analyze(user_input)
        
        # 2. 设计架构
        overview, components, tech_stack = self.architecture_designer.design(
            requirements, project_type
        )
        
        # 3. 设计数据模型
        entities = self.data_designer.design(requirements)
        
        # 4. 设计 API（基于数据模型）
        api_endpoints = self._design_api(entities, requirements)
        
        # 5. 设计 UI 页面
        screens = self._design_screens(requirements)
        
        # 6. 收集所有待澄清问题
        clarification_questions = []
        for req in requirements:
            clarification_questions.extend(req.questions)
        
        # 添加通用问题
        clarification_questions.extend([
            "以上设计是否符合您的预期？",
            "是否有遗漏的功能？",
            "技术栈是否可以接受？",
        ])
        
        return DesignDocument(
            project_name=project_name,
            project_type=project_type,
            status=DesignStatus.PENDING_REVIEW,  # 等待用户确认！
            requirements=requirements,
            architecture_overview=overview,
            components=components,
            entities=entities,
            api_endpoints=api_endpoints,
            screens=screens,
            tech_stack=tech_stack,
            clarification_questions=clarification_questions,
            created_at=now,
            updated_at=now,
        )
    
    def _design_api(
        self,
        entities: List[DataEntity],
        requirements: List[Requirement],
    ) -> List[APIEndpoint]:
        """设计 API 接口"""
        endpoints = []
        
        # 认证相关 API
        has_auth = any("登录" in r.description or "注册" in r.description for r in requirements)
        if has_auth:
            endpoints.extend([
                APIEndpoint(
                    method="POST",
                    path="/api/v1/auth/login",
                    description="用户登录",
                    request_schema="LoginRequest",
                    response_schema="LoginResponse",
                    auth_required=False,
                ),
                APIEndpoint(
                    method="POST",
                    path="/api/v1/auth/register",
                    description="用户注册",
                    request_schema="RegisterRequest",
                    response_schema="User",
                    auth_required=False,
                ),
                APIEndpoint(
                    method="POST",
                    path="/api/v1/auth/logout",
                    description="用户登出",
                    auth_required=True,
                ),
            ])
        
        # 为每个实体生成 CRUD API
        for entity in entities:
            name = entity.name
            resource = name.lower() + "s"
            
            endpoints.extend([
                APIEndpoint(
                    method="GET",
                    path=f"/api/v1/{resource}",
                    description=f"获取{entity.description}列表",
                    response_schema=f"{name}List",
                ),
                APIEndpoint(
                    method="GET",
                    path=f"/api/v1/{resource}/{{id}}",
                    description=f"获取{entity.description}详情",
                    response_schema=name,
                ),
                APIEndpoint(
                    method="POST",
                    path=f"/api/v1/{resource}",
                    description=f"创建{entity.description}",
                    request_schema=f"Create{name}Request",
                    response_schema=name,
                ),
                APIEndpoint(
                    method="PUT",
                    path=f"/api/v1/{resource}/{{id}}",
                    description=f"更新{entity.description}",
                    request_schema=f"Update{name}Request",
                    response_schema=name,
                ),
                APIEndpoint(
                    method="DELETE",
                    path=f"/api/v1/{resource}/{{id}}",
                    description=f"删除{entity.description}",
                ),
            ])
        
        return endpoints
    
    def _design_screens(self, requirements: List[Requirement]) -> List[UIScreen]:
        """设计 UI 页面"""
        screens = []
        
        # 认证页面
        has_auth = any("登录" in r.description for r in requirements)
        if has_auth:
            screens.extend([
                UIScreen(
                    name="登录页",
                    path="/login",
                    description="用户登录页面",
                    components=["LoginForm"],
                    data_needs=[],
                ),
                UIScreen(
                    name="注册页",
                    path="/register",
                    description="用户注册页面",
                    components=["RegisterForm"],
                    data_needs=[],
                ),
            ])
        
        # 主页
        screens.append(UIScreen(
            name="首页",
            path="/",
            description="应用首页/仪表盘",
            components=["Dashboard", "NavigationMenu"],
            data_needs=["统计数据"],
        ))
        
        # 列表页
        has_list = any("列表" in r.description or "管理" in r.description for r in requirements)
        if has_list:
            screens.append(UIScreen(
                name="列表页",
                path="/items",
                description="数据列表页面",
                components=["DataTable", "SearchBar", "Pagination"],
                data_needs=["列表数据", "总数"],
            ))
        
        return screens


def format_design_document(doc: DesignDocument) -> str:
    """
    格式化设计文档为可读文本
    
    这个文档会展示给用户确认！
    """
    lines = [
        f"# {doc.project_name} - 设计文档",
        "",
        f"**状态**: {doc.status.value}",
        f"**项目类型**: {doc.project_type.value}",
        "",
        "---",
        "",
        "## 1. 需求列表",
        "",
    ]
    
    # 需求
    for req in doc.requirements:
        priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(req.priority, "⚪")
        lines.append(f"### {req.id} {priority_icon}")
        lines.append(f"**{req.description}**")
        lines.append("")
        if req.acceptance_criteria:
            lines.append("验收标准：")
            for criteria in req.acceptance_criteria:
                lines.append(f"- [ ] {criteria}")
            lines.append("")
    
    # 架构
    lines.extend([
        "---",
        "",
        "## 2. 系统架构",
        "",
        doc.architecture_overview,
        "",
    ])
    
    # 数据模型
    if doc.entities:
        lines.extend([
            "---",
            "",
            "## 3. 数据模型",
            "",
        ])
        for entity in doc.entities:
            lines.append(f"### {entity.name}")
            lines.append(f"{entity.description}")
            lines.append("")
            lines.append("| 字段 | 类型 | 说明 |")
            lines.append("|------|------|------|")
            for field in entity.fields:
                field_type = field.get("type", "string")
                if field.get("pk"):
                    field_type += " (PK)"
                if field.get("fk"):
                    field_type += f" (FK -> {field['fk']})"
                lines.append(f"| {field['name']} | {field_type} | |")
            lines.append("")
    
    # API
    if doc.api_endpoints:
        lines.extend([
            "---",
            "",
            "## 4. API 接口",
            "",
            "| 方法 | 路径 | 说明 | 认证 |",
            "|------|------|------|------|",
        ])
        for endpoint in doc.api_endpoints:
            auth = "是" if endpoint.auth_required else "否"
            lines.append(f"| {endpoint.method} | {endpoint.path} | {endpoint.description} | {auth} |")
        lines.append("")
    
    # UI 页面
    if doc.screens:
        lines.extend([
            "---",
            "",
            "## 5. UI 页面",
            "",
        ])
        for screen in doc.screens:
            lines.append(f"### {screen.name}")
            lines.append(f"- 路由: `{screen.path}`")
            lines.append(f"- 描述: {screen.description}")
            if screen.components:
                lines.append(f"- 组件: {', '.join(screen.components)}")
            lines.append("")
    
    # 待确认问题（最重要！）
    if doc.clarification_questions:
        lines.extend([
            "---",
            "",
            "## ⚠️ 待确认问题",
            "",
            "**请在继续之前确认以下问题：**",
            "",
        ])
        for i, question in enumerate(doc.clarification_questions, 1):
            lines.append(f"{i}. {question}")
        lines.append("")
    
    return "\n".join(lines)


# ============================================================
# 快捷函数
# ============================================================

def analyze_and_design(
    user_input: str,
    project_name: str = "新项目",
) -> DesignDocument:
    """
    分析用户需求并生成设计文档
    
    这是启动新项目的第一步！
    """
    generator = DesignGenerator()
    return generator.generate(user_input, project_name)


def print_design_for_review(doc: DesignDocument) -> str:
    """
    打印设计文档供用户审阅
    
    用户必须确认后才能开始实现！
    """
    return format_design_document(doc)
