"""
契约定义模块

在任务分解前，先定义各 Agent 之间的接口契约、数据模型和命名规范。
确保所有 Agent 在同一套约定下工作，避免对接失败。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum
import json


class DataType(Enum):
    """数据类型"""
    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    FLOAT = "float"
    ARRAY = "array"
    OBJECT = "object"
    DATETIME = "datetime"
    UUID = "uuid"


@dataclass
class FieldSpec:
    """字段规格"""
    name: str
    type: DataType
    required: bool = True
    description: str = ""
    example: Any = None
    constraints: Dict[str, Any] = field(default_factory=dict)
    # 约束示例: {"min": 0, "max": 100, "pattern": "^[a-z]+$"}


@dataclass
class ModelSpec:
    """数据模型规格"""
    name: str
    description: str
    fields: List[FieldSpec]
    table_name: Optional[str] = None  # 数据库表名
    class_name: Optional[str] = None  # 代码中的类名
    file_path: Optional[str] = None   # 定义文件路径


@dataclass
class EndpointSpec:
    """API 接口规格"""
    method: str  # GET, POST, PUT, DELETE
    path: str    # /api/users/{id}
    description: str
    request_body: Optional[ModelSpec] = None
    response_body: Optional[ModelSpec] = None
    path_params: List[FieldSpec] = field(default_factory=list)
    query_params: List[FieldSpec] = field(default_factory=list)
    headers: List[FieldSpec] = field(default_factory=list)
    error_codes: Dict[int, str] = field(default_factory=dict)


@dataclass
class ComponentSpec:
    """UI 组件规格"""
    name: str
    description: str
    props: List[FieldSpec]
    events: List[str] = field(default_factory=list)
    slots: List[str] = field(default_factory=list)
    file_path: Optional[str] = None


@dataclass
class NamingConvention:
    """命名约定"""
    # 文件命名
    component_file_pattern: str = "{name}.tsx"      # LoginForm.tsx
    api_file_pattern: str = "{name}.py"             # auth.py
    model_file_pattern: str = "{name}.py"           # user.py
    test_file_pattern: str = "test_{name}.py"       # test_auth.py
    
    # 代码命名
    class_style: str = "PascalCase"                 # UserService
    function_style: str = "snake_case"              # get_user_by_id
    variable_style: str = "snake_case"              # user_name
    constant_style: str = "UPPER_SNAKE_CASE"        # MAX_RETRIES
    
    # API 路径
    api_prefix: str = "/api/v1"
    api_resource_style: str = "kebab-case"          # /user-profiles
    
    # 数据库
    table_prefix: str = ""
    table_style: str = "snake_case"                 # user_sessions
    column_style: str = "snake_case"                # created_at


@dataclass
class InterfaceContract:
    """
    接口契约 - 定义 Agent 之间的协作约定
    
    这是避免对接失败的关键！
    """
    task_id: str
    description: str
    
    # 数据模型约定
    models: List[ModelSpec] = field(default_factory=list)
    
    # API 接口约定
    endpoints: List[EndpointSpec] = field(default_factory=list)
    
    # UI 组件约定
    components: List[ComponentSpec] = field(default_factory=list)
    
    # 命名约定
    naming: NamingConvention = field(default_factory=NamingConvention)
    
    # 依赖关系
    dependencies: Dict[str, List[str]] = field(default_factory=dict)
    # 示例: {"frontend": ["backend_api"], "backend": ["database_models"]}
    
    # 集成验证点
    integration_checkpoints: List[str] = field(default_factory=list)
    # 示例: ["API接口可调用", "数据模型字段一致", "组件props匹配"]


class ContractBuilder:
    """契约构建器"""
    
    def __init__(self):
        self.models: List[ModelSpec] = []
        self.endpoints: List[EndpointSpec] = []
        self.components: List[ComponentSpec] = []
        self.naming = NamingConvention()
    
    def add_model(
        self,
        name: str,
        fields: List[Dict[str, Any]],
        description: str = "",
        table_name: Optional[str] = None,
    ) -> "ContractBuilder":
        """添加数据模型"""
        field_specs = [
            FieldSpec(
                name=f["name"],
                type=DataType(f.get("type", "string")),
                required=f.get("required", True),
                description=f.get("description", ""),
                example=f.get("example"),
            )
            for f in fields
        ]
        self.models.append(ModelSpec(
            name=name,
            description=description,
            fields=field_specs,
            table_name=table_name or name.lower(),
            class_name=name,
        ))
        return self
    
    def add_endpoint(
        self,
        method: str,
        path: str,
        description: str = "",
        request_model: Optional[str] = None,
        response_model: Optional[str] = None,
        error_codes: Optional[Dict[int, str]] = None,
    ) -> "ContractBuilder":
        """添加 API 接口"""
        request_body = None
        response_body = None
        
        if request_model:
            request_body = next(
                (m for m in self.models if m.name == request_model), None
            )
        if response_model:
            response_body = next(
                (m for m in self.models if m.name == response_model), None
            )
        
        self.endpoints.append(EndpointSpec(
            method=method,
            path=path,
            description=description,
            request_body=request_body,
            response_body=response_body,
            error_codes=error_codes or {},
        ))
        return self
    
    def add_component(
        self,
        name: str,
        props: List[Dict[str, Any]],
        description: str = "",
        events: Optional[List[str]] = None,
    ) -> "ContractBuilder":
        """添加 UI 组件"""
        prop_specs = [
            FieldSpec(
                name=p["name"],
                type=DataType(p.get("type", "string")),
                required=p.get("required", False),
                description=p.get("description", ""),
            )
            for p in props
        ]
        self.components.append(ComponentSpec(
            name=name,
            description=description,
            props=prop_specs,
            events=events or [],
        ))
        return self
    
    def set_naming(self, **kwargs) -> "ContractBuilder":
        """设置命名约定"""
        for key, value in kwargs.items():
            if hasattr(self.naming, key):
                setattr(self.naming, key, value)
        return self
    
    def build(self, task_id: str, description: str = "") -> InterfaceContract:
        """构建契约"""
        # 自动生成集成验证点
        checkpoints = []
        
        if self.endpoints:
            checkpoints.append("API 接口路径和参数格式一致")
        if self.models:
            checkpoints.append("数据模型字段名和类型一致")
        if self.components:
            checkpoints.append("UI 组件 props 与 API 响应匹配")
        
        # 自动推断依赖关系
        dependencies = {}
        if self.components and self.endpoints:
            dependencies["frontend"] = ["backend_api"]
        if self.endpoints and self.models:
            dependencies["backend"] = ["database_models"]
        
        return InterfaceContract(
            task_id=task_id,
            description=description,
            models=self.models,
            endpoints=self.endpoints,
            components=self.components,
            naming=self.naming,
            dependencies=dependencies,
            integration_checkpoints=checkpoints,
        )


def generate_contract_document(contract: InterfaceContract) -> str:
    """
    生成契约文档
    
    这个文档会被注入到每个 Agent 的任务描述中，
    确保所有 Agent 遵循相同的约定。
    """
    lines = [
        "# 接口契约文档",
        "",
        f"任务ID: {contract.task_id}",
        f"描述: {contract.description}",
        "",
    ]
    
    # 命名约定
    lines.extend([
        "## 1. 命名约定",
        "",
        f"- API 前缀: `{contract.naming.api_prefix}`",
        f"- API 资源风格: `{contract.naming.api_resource_style}`",
        f"- 类名风格: `{contract.naming.class_style}`",
        f"- 函数名风格: `{contract.naming.function_style}`",
        f"- 数据库表风格: `{contract.naming.table_style}`",
        "",
    ])
    
    # 数据模型
    if contract.models:
        lines.extend([
            "## 2. 数据模型",
            "",
        ])
        for model in contract.models:
            lines.append(f"### {model.name}")
            lines.append(f"表名: `{model.table_name}`")
            lines.append("")
            lines.append("| 字段 | 类型 | 必填 | 说明 |")
            lines.append("|------|------|------|------|")
            for field in model.fields:
                required = "是" if field.required else "否"
                lines.append(
                    f"| {field.name} | {field.type.value} | {required} | {field.description} |"
                )
            lines.append("")
    
    # API 接口
    if contract.endpoints:
        lines.extend([
            "## 3. API 接口",
            "",
        ])
        for endpoint in contract.endpoints:
            lines.append(f"### {endpoint.method} {endpoint.path}")
            lines.append(f"{endpoint.description}")
            lines.append("")
            
            if endpoint.request_body:
                lines.append(f"**请求体**: `{endpoint.request_body.name}`")
            if endpoint.response_body:
                lines.append(f"**响应体**: `{endpoint.response_body.name}`")
            
            if endpoint.error_codes:
                lines.append("")
                lines.append("**错误码**:")
                for code, msg in endpoint.error_codes.items():
                    lines.append(f"- {code}: {msg}")
            lines.append("")
    
    # UI 组件
    if contract.components:
        lines.extend([
            "## 4. UI 组件",
            "",
        ])
        for component in contract.components:
            lines.append(f"### {component.name}")
            lines.append(f"{component.description}")
            lines.append("")
            if component.props:
                lines.append("**Props**:")
                for prop in component.props:
                    required = "(必填)" if prop.required else "(可选)"
                    lines.append(f"- `{prop.name}`: {prop.type.value} {required}")
            if component.events:
                lines.append("")
                lines.append("**Events**:")
                for event in component.events:
                    lines.append(f"- `{event}`")
            lines.append("")
    
    # 集成验证点
    if contract.integration_checkpoints:
        lines.extend([
            "## 5. 集成验证点",
            "",
            "完成任务后，请确保以下验证通过：",
            "",
        ])
        for i, checkpoint in enumerate(contract.integration_checkpoints, 1):
            lines.append(f"{i}. [ ] {checkpoint}")
        lines.append("")
    
    return "\n".join(lines)


# ============================================================
# 示例：用户登录功能的契约
# ============================================================

def create_login_contract() -> InterfaceContract:
    """
    创建用户登录功能的接口契约示例
    
    这个契约确保：
    - 前端知道调用什么 API
    - 后端知道返回什么格式
    - 数据库知道存什么字段
    """
    builder = ContractBuilder()
    
    # 1. 定义数据模型（数据库 Agent C 实现）
    builder.add_model(
        name="User",
        description="用户表",
        table_name="users",
        fields=[
            {"name": "id", "type": "uuid", "description": "用户ID"},
            {"name": "username", "type": "string", "description": "用户名"},
            {"name": "password_hash", "type": "string", "description": "密码哈希"},
            {"name": "email", "type": "string", "required": False, "description": "邮箱"},
            {"name": "created_at", "type": "datetime", "description": "创建时间"},
        ],
    )
    
    builder.add_model(
        name="LoginRequest",
        description="登录请求",
        fields=[
            {"name": "username", "type": "string", "description": "用户名"},
            {"name": "password", "type": "string", "description": "密码"},
        ],
    )
    
    builder.add_model(
        name="LoginResponse",
        description="登录响应",
        fields=[
            {"name": "success", "type": "boolean", "description": "是否成功"},
            {"name": "token", "type": "string", "required": False, "description": "JWT Token"},
            {"name": "user_id", "type": "uuid", "required": False, "description": "用户ID"},
            {"name": "error", "type": "string", "required": False, "description": "错误信息"},
        ],
    )
    
    # 2. 定义 API 接口（后端 Agent B 实现）
    builder.add_endpoint(
        method="POST",
        path="/api/v1/auth/login",
        description="用户登录",
        request_model="LoginRequest",
        response_model="LoginResponse",
        error_codes={
            400: "请求参数错误",
            401: "用户名或密码错误",
            500: "服务器内部错误",
        },
    )
    
    # 3. 定义 UI 组件（前端 Agent A 实现）
    builder.add_component(
        name="LoginForm",
        description="登录表单组件",
        props=[
            {"name": "onSuccess", "type": "object", "description": "登录成功回调"},
            {"name": "onError", "type": "object", "description": "登录失败回调"},
            {"name": "loading", "type": "boolean", "description": "加载状态"},
        ],
        events=["submit", "cancel"],
    )
    
    # 4. 设置命名约定
    builder.set_naming(
        api_prefix="/api/v1",
        class_style="PascalCase",
        function_style="snake_case",
    )
    
    return builder.build(
        task_id="LOGIN-001",
        description="用户登录功能",
    )
