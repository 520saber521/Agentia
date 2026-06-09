"""
增强版任务分解器

在分解任务时自动生成接口契约，确保各 Agent 的工作能够对接。

核心理念：契约优先设计 (Contract-First Design)
1. 先定义接口契约（API、数据模型、组件规格）
2. 将契约注入到每个子任务中
3. 各 Agent 按契约实现，天然对接
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from .decomposer import SubTask, DecomposeResult, TaskDecomposer, DOMAIN_DEPENDENCIES
from .complexity import TaskInput
from .contracts import (
    InterfaceContract,
    ContractBuilder,
    ModelSpec,
    EndpointSpec,
    ComponentSpec,
    FieldSpec,
    DataType,
    generate_contract_document,
)


@dataclass
class EnhancedSubTask(SubTask):
    """增强版子任务 - 包含契约信息"""
    # 继承自 SubTask 的所有字段
    
    # 新增：契约相关字段
    contract_section: str = ""           # 该子任务负责的契约部分
    shared_models: List[str] = field(default_factory=list)  # 使用的共享模型
    provided_interfaces: List[str] = field(default_factory=list)  # 提供的接口
    required_interfaces: List[str] = field(default_factory=list)  # 依赖的接口
    integration_tests: List[str] = field(default_factory=list)    # 集成测试要求


@dataclass
class EnhancedDecomposeResult(DecomposeResult):
    """增强版分解结果 - 包含契约"""
    contract: Optional[InterfaceContract] = None
    contract_document: str = ""


class EnhancedTaskDecomposer(TaskDecomposer):
    """
    增强版任务分解器
    
    特点：
    1. 自动分析任务需要的接口契约
    2. 生成统一的数据模型和 API 规格
    3. 将契约信息注入到每个子任务
    4. 确保各领域 Agent 的工作能够对接
    """
    
    def __init__(self):
        super().__init__()
        self.contract_builder = ContractBuilder()
    
    def decompose_with_contract(
        self,
        task: TaskInput,
        domains: Set[str],
        parent_task_id: Optional[str] = None,
    ) -> EnhancedDecomposeResult:
        """
        分解任务并生成接口契约
        
        流程：
        1. 分析任务需要的实体和接口
        2. 生成接口契约
        3. 分解为子任务
        4. 将契约信息注入子任务
        """
        if not parent_task_id:
            parent_task_id = self._generate_task_id("TASK")
        
        # 1. 分析任务，提取实体和接口
        entities = self._extract_entities(task)
        api_patterns = self._extract_api_patterns(task, entities)
        ui_components = self._extract_ui_components(task, entities)
        
        # 2. 构建接口契约
        contract = self._build_contract(
            task_id=parent_task_id,
            description=task.description,
            entities=entities,
            api_patterns=api_patterns,
            ui_components=ui_components,
        )
        
        # 3. 生成契约文档
        contract_doc = generate_contract_document(contract)
        
        # 4. 分解为子任务（带契约信息）
        subtasks = self._create_subtasks_with_contract(
            task=task,
            domains=domains,
            parent_task_id=parent_task_id,
            contract=contract,
            contract_doc=contract_doc,
        )
        
        # 5. 构建依赖图和执行顺序（由 LLM 决定，不做硬编码预设）
        dependency_graph = {}
        for subtask in subtasks:
            subtask.dependencies = []
            dependency_graph[subtask.id] = []
        
        execution_order = self._compute_execution_order(subtasks, dependency_graph)
        
        # 6. 生成摘要
        summary = self._generate_enhanced_summary(
            task, subtasks, execution_order, contract
        )
        
        return EnhancedDecomposeResult(
            parent_task_id=parent_task_id,
            subtasks=subtasks,
            dependency_graph=dependency_graph,
            execution_order=execution_order,
            summary=summary,
            contract=contract,
            contract_document=contract_doc,
        )
    
    def _extract_entities(self, task: TaskInput) -> List[Dict[str, Any]]:
        """
        从任务描述中提取实体
        
        例如：
        "实现用户登录功能" -> 提取出 "User" 实体
        "订单管理系统" -> 提取出 "Order", "OrderItem" 实体
        """
        entities = []
        description = task.description.lower()
        
        # 常见实体关键词映射
        entity_keywords = {
            "用户": {"name": "User", "table": "users", "fields": [
                ("id", "uuid", "用户ID"),
                ("username", "string", "用户名"),
                ("password_hash", "string", "密码哈希"),
                ("email", "string", "邮箱"),
                ("created_at", "datetime", "创建时间"),
            ]},
            "登录": {"name": "Session", "table": "sessions", "fields": [
                ("id", "uuid", "会话ID"),
                ("user_id", "uuid", "用户ID"),
                ("token", "string", "Token"),
                ("expires_at", "datetime", "过期时间"),
            ]},
            "订单": {"name": "Order", "table": "orders", "fields": [
                ("id", "uuid", "订单ID"),
                ("user_id", "uuid", "用户ID"),
                ("status", "string", "状态"),
                ("total_amount", "float", "总金额"),
                ("created_at", "datetime", "创建时间"),
            ]},
            "商品": {"name": "Product", "table": "products", "fields": [
                ("id", "uuid", "商品ID"),
                ("name", "string", "名称"),
                ("price", "float", "价格"),
                ("stock", "integer", "库存"),
            ]},
            "评论": {"name": "Comment", "table": "comments", "fields": [
                ("id", "uuid", "评论ID"),
                ("user_id", "uuid", "用户ID"),
                ("content", "string", "内容"),
                ("created_at", "datetime", "创建时间"),
            ]},
            "文章": {"name": "Article", "table": "articles", "fields": [
                ("id", "uuid", "文章ID"),
                ("title", "string", "标题"),
                ("content", "string", "内容"),
                ("author_id", "uuid", "作者ID"),
            ]},
        }
        
        for keyword, entity_info in entity_keywords.items():
            if keyword in description:
                entities.append(entity_info)
        
        # 不兜底返回通用实体 — 如果没有匹配到关键词，返回空列表
        return entities
    
    def _extract_api_patterns(
        self,
        task: TaskInput,
        entities: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        根据实体生成 API 接口模式
        """
        patterns = []
        description = task.description.lower()
        
        for entity in entities:
            name = entity["name"]
            resource = name.lower() + "s"  # users, orders, products
            
            # 基于任务描述推断需要的 API
            if "登录" in description and name == "User":
                patterns.append({
                    "method": "POST",
                    "path": f"/api/v1/auth/login",
                    "description": "用户登录",
                    "request": f"{name}LoginRequest",
                    "response": f"{name}LoginResponse",
                })
            elif "注册" in description and name == "User":
                patterns.append({
                    "method": "POST",
                    "path": f"/api/v1/auth/register",
                    "description": "用户注册",
                    "request": f"{name}RegisterRequest",
                    "response": f"{name}",
                })
            else:
                # 默认 CRUD API
                patterns.extend([
                    {
                        "method": "GET",
                        "path": f"/api/v1/{resource}",
                        "description": f"获取{name}列表",
                        "response": f"{name}List",
                    },
                    {
                        "method": "GET",
                        "path": f"/api/v1/{resource}/{{id}}",
                        "description": f"获取{name}详情",
                        "response": name,
                    },
                    {
                        "method": "POST",
                        "path": f"/api/v1/{resource}",
                        "description": f"创建{name}",
                        "request": f"Create{name}Request",
                        "response": name,
                    },
                ])
        
        return patterns
    
    def _extract_ui_components(
        self,
        task: TaskInput,
        entities: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        根据实体推断 UI 组件
        """
        components = []
        description = task.description.lower()
        
        for entity in entities:
            name = entity["name"]
            
            if "登录" in description and name == "User":
                components.append({
                    "name": "LoginForm",
                    "description": "登录表单",
                    "props": [
                        {"name": "onSuccess", "type": "object"},
                        {"name": "onError", "type": "object"},
                        {"name": "loading", "type": "boolean"},
                    ],
                    "events": ["submit"],
                })
            elif "表单" in description or "编辑" in description:
                components.append({
                    "name": f"{name}Form",
                    "description": f"{name}表单",
                    "props": [
                        {"name": "initialData", "type": "object"},
                        {"name": "onSubmit", "type": "object"},
                    ],
                    "events": ["submit", "cancel"],
                })
            
            # 默认列表组件
            if "列表" in description or "管理" in description:
                components.append({
                    "name": f"{name}List",
                    "description": f"{name}列表",
                    "props": [
                        {"name": "data", "type": "array"},
                        {"name": "loading", "type": "boolean"},
                        {"name": "onSelect", "type": "object"},
                    ],
                    "events": ["select", "delete", "edit"],
                })
        
        return components
    
    def _build_contract(
        self,
        task_id: str,
        description: str,
        entities: List[Dict[str, Any]],
        api_patterns: List[Dict[str, Any]],
        ui_components: List[Dict[str, Any]],
    ) -> InterfaceContract:
        """
        构建接口契约
        """
        builder = ContractBuilder()
        
        # 添加数据模型
        for entity in entities:
            fields = [
                {
                    "name": f[0],
                    "type": f[1],
                    "description": f[2],
                }
                for f in entity["fields"]
            ]
            builder.add_model(
                name=entity["name"],
                description=f"{entity['name']}实体",
                table_name=entity["table"],
                fields=fields,
            )
        
        # 添加 API 接口
        for api in api_patterns:
            builder.add_endpoint(
                method=api["method"],
                path=api["path"],
                description=api["description"],
                request_model=api.get("request"),
                response_model=api.get("response"),
            )
        
        # 添加 UI 组件
        for comp in ui_components:
            builder.add_component(
                name=comp["name"],
                description=comp["description"],
                props=comp.get("props", []),
                events=comp.get("events", []),
            )
        
        return builder.build(task_id, description)
    
    def _create_subtasks_with_contract(
        self,
        task: TaskInput,
        domains: Set[str],
        parent_task_id: str,
        contract: InterfaceContract,
        contract_doc: str,
    ) -> List[EnhancedSubTask]:
        """
        创建带契约信息的子任务
        """
        subtasks = []
        
        for domain in domains:
            subtask_id = f"{parent_task_id}-{domain.upper()}"
            
            # 根据领域提取契约部分
            contract_section = self._get_contract_section(domain, contract)
            shared_models = self._get_shared_models(domain, contract)
            provided_interfaces = self._get_provided_interfaces(domain, contract)
            required_interfaces = self._get_required_interfaces(domain, contract)
            integration_tests = self._get_integration_tests(domain, contract)
            
            # 构建增强描述（包含契约信息）
            description = self._build_enhanced_description(
                domain=domain,
                task=task,
                contract_doc=contract_doc,
                contract_section=contract_section,
            )
            
            subtask = EnhancedSubTask(
                id=subtask_id,
                domain=domain,
                description=description,
                files=self._infer_files_for_domain(task, domain),
                success_criteria=self._generate_success_criteria_with_contract(
                    domain, contract
                ),
                priority=self._compute_priority(domain),
                contract_section=contract_section,
                shared_models=shared_models,
                provided_interfaces=provided_interfaces,
                required_interfaces=required_interfaces,
                integration_tests=integration_tests,
            )
            subtasks.append(subtask)
        
        return subtasks
    
    def _get_contract_section(
        self, domain: str, contract: InterfaceContract
    ) -> str:
        """获取该领域负责的契约部分"""
        sections = {
            "database": "数据模型（models）",
            "backend": "API 接口（endpoints）",
            "frontend": "UI 组件（components）",
            "test": "集成测试",
            "docs": "文档",
        }
        return sections.get(domain, "")
    
    def _get_shared_models(
        self, domain: str, contract: InterfaceContract
    ) -> List[str]:
        """获取该领域使用的共享模型"""
        model_names = [m.name for m in contract.models]
        
        if domain == "database":
            return model_names  # 数据库定义所有模型
        elif domain in ("backend", "frontend"):
            return model_names  # 后端和前端使用所有模型
        return []
    
    def _get_provided_interfaces(
        self, domain: str, contract: InterfaceContract
    ) -> List[str]:
        """获取该领域提供的接口"""
        if domain == "backend":
            return [f"{e.method} {e.path}" for e in contract.endpoints]
        elif domain == "database":
            return [f"Table: {m.table_name}" for m in contract.models]
        return []
    
    def _get_required_interfaces(
        self, domain: str, contract: InterfaceContract
    ) -> List[str]:
        """获取该领域依赖的接口"""
        if domain == "frontend":
            return [f"{e.method} {e.path}" for e in contract.endpoints]
        elif domain == "backend":
            return [f"Table: {m.table_name}" for m in contract.models]
        return []
    
    def _get_integration_tests(
        self, domain: str, contract: InterfaceContract
    ) -> List[str]:
        """获取该领域的集成测试要求"""
        tests = []
        
        if domain == "backend":
            for endpoint in contract.endpoints:
                tests.append(f"测试 {endpoint.method} {endpoint.path} 返回正确格式")
        elif domain == "frontend":
            for comp in contract.components:
                tests.append(f"测试 {comp.name} 组件渲染正确")
        elif domain == "database":
            for model in contract.models:
                tests.append(f"测试 {model.table_name} 表结构正确")
        
        return tests
    
    def _build_enhanced_description(
        self,
        domain: str,
        task: TaskInput,
        contract_doc: str,
        contract_section: str,
        llm_description: str = "",
    ) -> str:
        """Build a domain-specific subtask description.

        When ``llm_description`` is provided (LLM-driven decomposition), it is
        used as the primary description supplemented with the relevant contract
        section. Otherwise falls back to the legacy format.
        """
        domain_names = {
            "frontend": "前端",
            "backend": "后端",
            "database": "数据库",
            "test": "测试",
            "docs": "文档",
            "devops": "运维部署",
            "code": "通用代码",
        }
        domain_name = domain_names.get(domain, domain)

        if llm_description:
            parts = [f"[{domain_name}] {llm_description}"]
            if contract_section:
                parts.append(f"\n\n负责契约部分: {contract_section}")
            return "".join(parts)

        return f"[{domain_name}] {task.description}"
    
    def _generate_success_criteria_with_contract(
        self,
        domain: str,
        contract: InterfaceContract,
    ) -> List[str]:
        """生成带契约验证的成功标准"""
        base_criteria = {
            "frontend": [
                "UI组件正确渲染",
                "API调用路径与契约一致",
                "请求/响应数据格式与契约一致",
            ],
            "backend": [
                "API接口路径与契约一致",
                "请求/响应数据格式与契约一致",
                "数据库操作字段名与契约一致",
            ],
            "database": [
                "表名与契约一致",
                "字段名和类型与契约一致",
                "迁移脚本可执行",
            ],
            "test": [
                "集成测试覆盖所有接口",
                "测试数据使用契约定义的字段",
            ],
        }
        
        criteria = base_criteria.get(domain, ["任务完成"])
        
        # 添加契约验证点
        criteria.extend(contract.integration_checkpoints)
        
        return criteria[:5]  # 最多5条
    
    def _resolve_enhanced_dependencies(
        self,
        subtask: EnhancedSubTask,
        all_subtasks: List[EnhancedSubTask],
        contract: InterfaceContract,
    ) -> List[str]:
        """解析增强版依赖关系"""
        deps = []
        domain_deps = DOMAIN_DEPENDENCIES.get(subtask.domain, [])
        
        for dep_domain in domain_deps:
            for other in all_subtasks:
                if other.domain == dep_domain and other.id != subtask.id:
                    deps.append(other.id)
        
        return deps
    
    def _generate_enhanced_summary(
        self,
        task: TaskInput,
        subtasks: List[EnhancedSubTask],
        execution_order: List[List[str]],
        contract: InterfaceContract,
    ) -> str:
        """生成增强版摘要"""
        lines = [
            f"任务分解完成，共 {len(subtasks)} 个子任务",
            "",
            "=== 接口契约 ===",
            f"数据模型: {len(contract.models)} 个",
            f"API 接口: {len(contract.endpoints)} 个",
            f"UI 组件: {len(contract.components)} 个",
            "",
            "=== 执行顺序 ===",
        ]
        
        for i, layer in enumerate(execution_order):
            layer_desc = ", ".join(layer)
            if len(layer) > 1:
                lines.append(f"  阶段 {i+1}（并行）: {layer_desc}")
            else:
                lines.append(f"  阶段 {i+1}: {layer_desc}")
        
        lines.extend([
            "",
            "=== 集成验证点 ===",
        ])
        for checkpoint in contract.integration_checkpoints:
            lines.append(f"  [ ] {checkpoint}")
        
        return "\n".join(lines)
    
    def _infer_files_for_domain(self, task: TaskInput, domain: str) -> List[str]:
        """推断领域相关的文件"""
        from .decomposer import DOMAIN_FILE_PATTERNS
        return DOMAIN_FILE_PATTERNS.get(domain, [])[:3]
    
    # def _compute_priority(self, domain: str) -> int:
    #     """计算优先级"""
    #     priority_map = {
    #         "database": 2,
    #         "backend": 1,
    #         "frontend": 0,
    #         "test": -1,
    #         "docs": -1,
    #     }
    #     return priority_map.get(domain, 0)

    async def decompose_with_llm(
        self,
        task: TaskInput,
        domains: Set[str],
        llm_send_fn: Callable,
        timeout: float = 30.0,
        parent_task_id: Optional[str] = None,
    ) -> EnhancedDecomposeResult:
        """LLM-driven intelligent task decomposition.

        Uses an LLM to analyze the user's requirement and produce domain-specific
        subtasks with meaningful descriptions, extracted entities, APIs, and UI
        components. Falls back to keyword-based ``decompose_with_contract()`` on
        any failure (timeout, parse error, empty response).
        """
        logger = logging.getLogger("agenthub.decomposer")
        if not parent_task_id:
            parent_task_id = self._generate_task_id("TASK")

        prompt = self._build_llm_decomposition_prompt(task, domains)

        try:
            async with asyncio.timeout(timeout):
                response_text = ""
                async for chunk in llm_send_fn(
                    messages=[{"role": "user", "content": prompt}]
                ):
                    if chunk.get("type") == "text":
                        response_text += chunk.get("delta", "")
                    elif chunk.get("type") == "error":
                        logger.warning("LLM decomposition error: %s", chunk.get("message"))
                        return self.decompose_with_contract(task, domains, parent_task_id)
                    elif chunk.get("type") == "done":
                        break

            parsed = self._parse_llm_decomposition_response(
                response_text, task, domains, parent_task_id
            )
            if parsed is None:
                logger.warning("Failed to parse LLM decomposition response, falling back")
                return self.decompose_with_contract(task, domains, parent_task_id)

            logger.info(
                "LLM decomposition produced %d subtasks: %s",
                len(parsed.subtasks),
                {st.id: st.description[:60] for st in parsed.subtasks},
            )
            return parsed

        except asyncio.TimeoutError:
            logger.warning("LLM decomposition timed out after %.1fs, falling back", timeout)
            return self.decompose_with_contract(task, domains, parent_task_id)
        except Exception as exc:
            logger.warning("LLM decomposition failed: %s, falling back", exc)
            return self.decompose_with_contract(task, domains, parent_task_id)

    def _build_llm_decomposition_prompt(
        self, task: TaskInput, domains: Set[str]
    ) -> str:
        """Build the LLM prompt for intelligent task decomposition."""
        domain_cn = {
            "frontend": "前端UI",
            "backend": "后端API",
            "database": "数据库",
            "test": "测试",
            "docs": "技术文档",
            "devops": "运维部署",
            "code": "通用代码",
        }
        domain_list = "\n".join(
            f"  - {d} ({domain_cn.get(d, d)})" for d in sorted(domains)
        )

        return (
            "你是一个软件任务分解专家。分析用户需求，将其拆解为领域特定的子任务。\n\n"
            f"用户需求：\n{task.description[:3000]}\n\n"
            f"可用领域（只能从以下选择）：\n{domain_list}\n\n"
            "请完成以下分析并以 JSON 格式返回（只输出 JSON，不要解释）：\n\n"
            "1. **entities**: 从需求中提取数据实体（用户、订单、文章等），每个实体包含 name、table_name、fields（字段列表，每个字段有 name/type/description）\n"
            "2. **apis**: 分析需要的 API 接口，每个接口包含 method、path、description、request_model、response_model\n"
            "3. **components**: 分析需要的 UI 组件，每个组件包含 name、description、props（属性列表）、events（事件列表）\n"
            "4. **subtasks**: 为每个可用领域创建具体子任务，每个子任务包含：\n"
            '   - domain: 领域名（必须从上方的可用领域列表中选择，不可自创）\n'
            "   - description: **具体的、可执行的**任务描述（200-500字），说明该领域的 Agent 具体要做什么、实现什么功能\n"
            "   - dependencies: 依赖的其他领域列表（只有存在明确数据/接口传递关系时才添加，默认空数组）\n"
            "   - acceptance_criteria: 验收标准列表（3-5条具体可验证的标准）\n\n"
            "重要原则：\n"
            "- 每个 subtask 的 description 必须包含该领域的具体实现要求，而非简单重复用户需求\n"
            "- 例如数据库 subtask 应说明要创建哪些表、关键字段；前端 subtask 应说明要创建哪些组件、交互逻辑\n"
            "- 默认所有 subtask 无依赖（dependencies: []），只有明确需要另一领域产出时才添加\n"
            "- 前端可用 mock 数据独立开发，不需要等后端\n"
            "- entities/apis/components 只提取需求中实际提到的，不要编造\n\n"
            'JSON 格式：\n'
            "{\n"
            '  "entities": [{"name": "...", "table_name": "...", "fields": [{"name": "...", "type": "...", "description": "..."}]}],\n'
            '  "apis": [{"method": "GET/POST/PUT/DELETE", "path": "/api/v1/...", "description": "...", "request_model": "...", "response_model": "..."}],\n'
            '  "components": [{"name": "...", "description": "...", "props": [{"name": "...", "type": "..."}], "events": ["..."]}],\n'
            '  "subtasks": [\n'
            '    {"domain": "...", "description": "...", "dependencies": [], "acceptance_criteria": ["..."]}\n'
            "  ]\n"
            "}"
        )

    def _parse_llm_decomposition_response(
        self,
        text: str,
        task: TaskInput,
        domains: Set[str],
        parent_task_id: str,
    ) -> Optional[EnhancedDecomposeResult]:
        """Parse the LLM's JSON decomposition response into an EnhancedDecomposeResult."""
        import re

        # Extract JSON block — try code-fenced first, then raw brace match
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            json_match = re.search(r"\{[\s\S]*\}", text)
            if not json_match:
                return None
            json_str = json_match.group()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return None

        if not isinstance(data, dict) or "subtasks" not in data:
            return None

        # Build contract from LLM-extracted entities/APIs/components
        contract = self._build_contract_from_llm_response(
            parent_task_id, task.description, data
        )
        contract_doc = generate_contract_document(contract)

        # Create subtasks from LLM response
        subtasks: List[EnhancedSubTask] = []
        seen_domains: Set[str] = set()

        for i, st_data in enumerate(data.get("subtasks", [])):
            if not isinstance(st_data, dict):
                continue
            domain = st_data.get("domain", "")
            if not domain or domain not in domains:
                continue
            if domain in seen_domains:
                # Append suffix for duplicate domains
                domain_key = f"{domain}_{i}"
            else:
                domain_key = domain
            seen_domains.add(domain)

            subtask_id = f"{parent_task_id}-{domain.upper()}"
            if domain_key != domain:
                subtask_id = f"{parent_task_id}-{domain.upper()}-{i}"

            llm_description = st_data.get("description", "")
            contract_section = self._get_contract_section(domain, contract)
            shared_models = self._get_shared_models(domain, contract)

            description = self._build_enhanced_description(
                domain=domain,
                task=task,
                contract_doc=contract_doc,
                contract_section=contract_section,
                llm_description=llm_description,
            )

            subtask = EnhancedSubTask(
                id=subtask_id,
                domain=domain,
                description=description,
                files=self._infer_files_for_domain(task, domain),
                success_criteria=st_data.get("acceptance_criteria", [])[:5],
                priority=self._compute_priority(domain),
                dependencies=list(st_data.get("dependencies", [])),
                contract_section=contract_section,
                shared_models=shared_models,
                provided_interfaces=self._get_provided_interfaces(domain, contract),
                required_interfaces=self._get_required_interfaces(domain, contract),
                integration_tests=self._get_integration_tests(domain, contract),
            )
            subtasks.append(subtask)

        if not subtasks:
            return None

        # Build dependency graph
        dependency_graph: Dict[str, List[str]] = {}
        for st in subtasks:
            resolved = []
            for dep_domain in st.dependencies:
                for other in subtasks:
                    if other.domain == dep_domain and other.id != st.id:
                        resolved.append(other.id)
            dependency_graph[st.id] = resolved
            st.dependencies = resolved

        execution_order = self._compute_execution_order(subtasks, dependency_graph)

        summary = self._generate_enhanced_summary(
            task, subtasks, execution_order, contract
        )

        return EnhancedDecomposeResult(
            parent_task_id=parent_task_id,
            subtasks=subtasks,
            dependency_graph=dependency_graph,
            execution_order=execution_order,
            summary=summary,
            contract=contract,
            contract_document=contract_doc,
        )

    def _build_contract_from_llm_response(
        self,
        task_id: str,
        description: str,
        data: Dict[str, Any],
    ) -> InterfaceContract:
        """Build an InterfaceContract from the LLM's JSON response."""
        builder = ContractBuilder()

        for entity in data.get("entities", []):
            if not isinstance(entity, dict):
                continue
            fields = entity.get("fields", [])
            builder.add_model(
                name=entity.get("name", "Unknown"),
                description=entity.get("description", ""),
                table_name=entity.get("table_name", entity.get("name", "unknown").lower()),
                fields=[
                    {
                        "name": f.get("name", ""),
                        "type": f.get("type", "string"),
                        "description": f.get("description", ""),
                    }
                    for f in fields
                    if isinstance(f, dict)
                ],
            )

        for api in data.get("apis", []):
            if not isinstance(api, dict):
                continue
            builder.add_endpoint(
                method=api.get("method", "GET"),
                path=api.get("path", ""),
                description=api.get("description", ""),
                request_model=api.get("request_model"),
                response_model=api.get("response_model"),
            )

        for comp in data.get("components", []):
            if not isinstance(comp, dict):
                continue
            builder.add_component(
                name=comp.get("name", ""),
                description=comp.get("description", ""),
                props=comp.get("props", []),
                events=comp.get("events", []),
            )

        return builder.build(task_id, description)

    async def resolve_dependencies_llm(
        self,
        result: EnhancedDecomposeResult,
        llm_send_fn: Callable,
        timeout: float = 30.0,
    ) -> EnhancedDecomposeResult:
        """Use LLM to semantically resolve dependencies between subtasks.

        Replaces the hardcoded DOMAIN_DEPENDENCIES with LLM-driven
        semantic analysis. Each subtask's description is analyzed to
        determine if it truly depends on another subtask's output.

        Falls back to the original hardcoded dependencies on failure.
        """
        if not result.subtasks:
            return result

        logger = logging.getLogger("agenthub.decomposer")

        prompt = self._build_dependency_prompt(result.subtasks)

        try:
            async with asyncio.timeout(timeout):
                response_text = ""
                async for chunk in llm_send_fn(
                    messages=[{"role": "user", "content": prompt}]
                ):
                    if chunk.get("type") == "text":
                        response_text += chunk.get("delta", "")
                    elif chunk.get("type") == "error":
                        logger.warning("LLM dependency resolution error: %s", chunk.get("message"))
                        return result
                    elif chunk.get("type") == "done":
                        break

            deps_map = self._parse_dependency_response(response_text, result.subtasks)
            if deps_map is None:
                logger.warning("Failed to parse LLM dependency response, using hardcoded deps")
                return result

            for subtask in result.subtasks:
                subtask.dependencies = deps_map.get(subtask.id, [])

            dependency_graph = {st.id: list(st.dependencies) for st in result.subtasks}
            execution_order = self._compute_execution_order(result.subtasks, dependency_graph)

            result.dependency_graph = dependency_graph
            result.execution_order = execution_order
            result.summary = self._generate_enhanced_summary(
                TaskInput(description=result.parent_task_id, context=""),
                result.subtasks,
                execution_order,
                result.contract,
            )

            logger.info(
                "LLM-resolved deps: %s",
                {st.id: st.dependencies for st in result.subtasks}
            )
            return result

        except asyncio.TimeoutError:
            logger.warning("LLM dependency resolution timed out, using hardcoded deps")
            return result
        except Exception as exc:
            logger.warning("LLM dependency resolution failed: %s, using hardcoded deps", exc)
            return result

    def _build_dependency_prompt(self, subtasks: List[EnhancedSubTask]) -> str:
        """Build the LLM prompt for semantic dependency analysis."""
        domain_cn = {
            "frontend": "前端UI",
            "backend": "后端API",
            "database": "数据库",
            "test": "测试",
            "docs": "技术文档",
            "devops": "运维部署",
            "code": "通用代码",
        }
        subtask_lines = []
        for i, st in enumerate(subtasks, 1):
            desc = st.description
            cn = domain_cn.get(st.domain, st.domain)
            subtask_lines.append(f"{i}. ID: {st.id}, 领域: {cn}, 描述: {desc[:200]}")

        return (
            '你是一个任务依赖分析器。根据以下子任务的具体语义内容，分析它们之间的实际依赖关系。\n\n'
            '核心原则：默认并行。只有存在明确的数据/接口传递关系时，才添加依赖。\n\n'
            '子任务列表：\n'
            + '\n'.join(subtask_lines) +
            '\n\n'
            '判断规则（按优先级）：\n'
            '1. 如果所有子任务描述几乎相同（同一用户需求被拆分到不同领域），则全部并行，全部[]，不要加任何依赖\n'
            '2. 如果子任务B必须使用子任务A产出的具体API/数据模型/函数签名，B才依赖A\n'
            '3. 前端完全可以用模拟数据(mock data)独立开发，不需要等后端。描述相同的前端/后端任务各自独立实现\n'
            '4. 如果两个子任务可以完全独立并行完成，则不应有依赖关系\n'
            '5. 技术文档(docs)依赖实现结果来撰写\n\n'
            '格式示例（全并行，无依赖）：\n'
            '{"dependencies": {"TASK-xxx-FRONTEND": [], "TASK-xxx-BACKEND": []}}\n\n'
            '确保：\n'
            '1. 所有子任务ID都必须出现在dependencies中\n'
            '2. 依赖列表必须是子任务ID的数组，即使是空数组也要写[]\n'
            '3. 只输出JSON，不要输出解释文字\n'
            '4. 默认全部[]，只有非常明确的数据传递关系才加依赖\n'
        )

    def _parse_dependency_response(
        self, text: str, subtasks: List[EnhancedSubTask]
    ) -> Optional[Dict[str, List[str]]]:
        """Parse the LLM dependency response JSON."""
        import re

        valid_ids = {st.id for st in subtasks}

        json_match = re.search(r'\{[\s\S]*"dependencies"[\s\S]*\}', text)
        if not json_match:
            return None

        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError:
            return None

        if "dependencies" not in data or not isinstance(data["dependencies"], dict):
            return None

        deps_map: Dict[str, List[str]] = {}
        for st_id, deps in data["dependencies"].items():
            if st_id not in valid_ids:
                continue
            if not isinstance(deps, list):
                deps = []
            deps_map[st_id] = [d for d in deps if d in valid_ids]

        for st in subtasks:
            if st.id not in deps_map:
                deps_map[st.id] = []

        return deps_map
