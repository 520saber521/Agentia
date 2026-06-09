"""
项目分析模块

无论新项目还是加新功能，都要先搞清楚：
1. 新项目：确定架构设计
2. 已有项目：分析现有代码结构、影响范围

核心原则：不留风险，搞得清清楚楚再动手！
"""

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from pathlib import Path
from enum import Enum


class RiskLevel(Enum):
    """风险等级"""
    LOW = "low"         # 低风险 - 独立新增，不影响现有
    MEDIUM = "medium"   # 中风险 - 需要修改少量现有代码
    HIGH = "high"       # 高风险 - 涉及核心模块修改
    CRITICAL = "critical"  # 极高风险 - 可能破坏现有功能


@dataclass
class FileInfo:
    """文件信息"""
    path: str
    language: str
    size: int
    lines: int
    imports: List[str] = field(default_factory=list)
    exports: List[str] = field(default_factory=list)
    classes: List[str] = field(default_factory=list)
    functions: List[str] = field(default_factory=list)


@dataclass
class ComponentInfo:
    """组件信息（前端）"""
    name: str
    path: str
    props: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    used_by: List[str] = field(default_factory=list)


@dataclass
class APIInfo:
    """API 接口信息"""
    method: str
    path: str
    handler: str
    file_path: str
    parameters: List[str] = field(default_factory=list)
    response_type: Optional[str] = None


@dataclass
class ModelInfo:
    """数据模型信息"""
    name: str
    file_path: str
    fields: List[Dict[str, Any]] = field(default_factory=list)
    relationships: List[str] = field(default_factory=list)


@dataclass
class ProjectStructure:
    """项目结构"""
    root_path: str
    project_type: str  # frontend, backend, fullstack, monorepo
    
    # 目录结构
    directories: Dict[str, str] = field(default_factory=dict)  # path -> purpose
    
    # 文件统计
    total_files: int = 0
    files_by_language: Dict[str, int] = field(default_factory=dict)
    
    # 依赖
    dependencies: Dict[str, str] = field(default_factory=dict)
    dev_dependencies: Dict[str, str] = field(default_factory=dict)
    
    # 代码元素
    files: List[FileInfo] = field(default_factory=list)
    components: List[ComponentInfo] = field(default_factory=list)
    apis: List[APIInfo] = field(default_factory=list)
    models: List[ModelInfo] = field(default_factory=list)
    
    # 配置
    config_files: List[str] = field(default_factory=list)
    env_vars: List[str] = field(default_factory=list)


@dataclass
class ImpactArea:
    """影响区域"""
    file_path: str
    reason: str
    risk_level: RiskLevel
    changes_needed: List[str] = field(default_factory=list)


@dataclass
class ImpactAnalysis:
    """影响分析"""
    feature_description: str
    
    # 影响的文件/模块
    affected_files: List[ImpactArea] = field(default_factory=list)
    
    # 需要新增的文件
    new_files: List[str] = field(default_factory=list)
    
    # 需要修改的 API
    api_changes: List[Dict[str, Any]] = field(default_factory=list)
    
    # 需要修改的数据模型
    model_changes: List[Dict[str, Any]] = field(default_factory=list)
    
    # 总体风险评估
    overall_risk: RiskLevel = RiskLevel.MEDIUM
    risk_factors: List[str] = field(default_factory=list)
    
    # 建议
    recommendations: List[str] = field(default_factory=list)
    
    # 前置条件
    prerequisites: List[str] = field(default_factory=list)
    
    # 测试要求
    test_requirements: List[str] = field(default_factory=list)


class ProjectAnalyzer:
    """
    项目分析器
    
    在做任何修改前，先分析清楚：
    1. 项目结构是什么样的
    2. 现有哪些组件、API、数据模型
    3. 新功能会影响哪些地方
    4. 风险有多大
    """
    
    # 语言扩展名映射
    LANGUAGE_MAP = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".vue": "vue",
        ".css": "css",
        ".scss": "scss",
        ".html": "html",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".md": "markdown",
        ".sql": "sql",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
    }
    
    # 忽略的目录
    IGNORE_DIRS = {
        "node_modules", ".git", "__pycache__", ".venv", "venv",
        "dist", "build", ".next", ".nuxt", "coverage", ".pytest_cache",
    }
    
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
    
    def analyze(self) -> ProjectStructure:
        """
        分析项目结构
        
        Returns:
            ProjectStructure: 完整的项目结构信息
        """
        structure = ProjectStructure(
            root_path=str(self.project_root),
            project_type=self._detect_project_type(),
        )
        
        # 扫描目录结构
        structure.directories = self._scan_directories()
        
        # 统计文件
        files_info = self._scan_files()
        structure.files = files_info
        structure.total_files = len(files_info)
        
        # 按语言统计
        for f in files_info:
            lang = f.language
            structure.files_by_language[lang] = structure.files_by_language.get(lang, 0) + 1
        
        # 解析依赖
        structure.dependencies, structure.dev_dependencies = self._parse_dependencies()
        
        # 提取组件
        structure.components = self._extract_components(files_info)
        
        # 提取 API
        structure.apis = self._extract_apis(files_info)
        
        # 提取数据模型
        structure.models = self._extract_models(files_info)
        
        # 找配置文件
        structure.config_files = self._find_config_files()
        
        return structure
    
    def _detect_project_type(self) -> str:
        """检测项目类型"""
        has_package_json = (self.project_root / "package.json").exists()
        has_requirements = (self.project_root / "requirements.txt").exists()
        has_pyproject = (self.project_root / "pyproject.toml").exists()
        has_go_mod = (self.project_root / "go.mod").exists()
        has_cargo = (self.project_root / "Cargo.toml").exists()
        
        # 检查是否是 monorepo
        has_packages = (self.project_root / "packages").is_dir()
        has_apps = (self.project_root / "apps").is_dir()
        
        if has_packages or has_apps:
            return "monorepo"
        
        if has_package_json and (has_requirements or has_pyproject):
            return "fullstack"
        elif has_package_json:
            # 进一步判断是前端还是 Node 后端
            pkg_json = self.project_root / "package.json"
            if pkg_json.exists():
                try:
                    import json
                    with open(pkg_json) as f:
                        pkg = json.load(f)
                    deps = pkg.get("dependencies", {})
                    if any(k in deps for k in ["react", "vue", "angular", "svelte"]):
                        return "frontend"
                    if any(k in deps for k in ["express", "fastify", "koa", "nest"]):
                        return "backend"
                except Exception:
                    pass
            return "frontend"
        elif has_requirements or has_pyproject:
            return "backend"
        elif has_go_mod:
            return "backend"
        elif has_cargo:
            return "backend"
        
        return "unknown"
    
    def _scan_directories(self) -> Dict[str, str]:
        """扫描目录结构"""
        dirs = {}
        
        # 常见目录用途映射
        purpose_map = {
            "src": "源代码",
            "lib": "库代码",
            "app": "应用代码",
            "pages": "页面",
            "components": "组件",
            "views": "视图",
            "api": "API 接口",
            "routes": "路由",
            "controllers": "控制器",
            "services": "服务层",
            "models": "数据模型",
            "schemas": "数据模式",
            "utils": "工具函数",
            "helpers": "辅助函数",
            "hooks": "React Hooks",
            "store": "状态管理",
            "stores": "状态管理",
            "redux": "Redux 状态",
            "context": "React Context",
            "styles": "样式",
            "assets": "静态资源",
            "public": "公共资源",
            "static": "静态文件",
            "tests": "测试",
            "test": "测试",
            "__tests__": "测试",
            "spec": "测试规范",
            "config": "配置",
            "configs": "配置",
            "migrations": "数据库迁移",
            "scripts": "脚本",
            "docs": "文档",
            "types": "类型定义",
            "interfaces": "接口定义",
            "middleware": "中间件",
            "middlewares": "中间件",
            "plugins": "插件",
            "locales": "国际化",
            "i18n": "国际化",
        }
        
        for item in self.project_root.iterdir():
            if item.is_dir() and item.name not in self.IGNORE_DIRS and not item.name.startswith("."):
                purpose = purpose_map.get(item.name.lower(), "")
                dirs[item.name] = purpose
        
        return dirs
    
    def _scan_files(self) -> List[FileInfo]:
        """扫描所有文件"""
        files = []
        
        for root, dirs, filenames in os.walk(self.project_root):
            # 过滤忽略的目录
            dirs[:] = [d for d in dirs if d not in self.IGNORE_DIRS and not d.startswith(".")]
            
            for filename in filenames:
                if filename.startswith("."):
                    continue
                
                filepath = Path(root) / filename
                ext = filepath.suffix.lower()
                
                if ext not in self.LANGUAGE_MAP:
                    continue
                
                try:
                    content = filepath.read_text(encoding="utf-8", errors="ignore")
                    lines = content.count("\n") + 1
                    
                    file_info = FileInfo(
                        path=str(filepath.relative_to(self.project_root)),
                        language=self.LANGUAGE_MAP[ext],
                        size=filepath.stat().st_size,
                        lines=lines,
                    )
                    
                    # 提取导入
                    file_info.imports = self._extract_imports(content, ext)
                    
                    # 提取导出/类/函数
                    file_info.classes = self._extract_classes(content, ext)
                    file_info.functions = self._extract_functions(content, ext)
                    
                    files.append(file_info)
                    
                except Exception:
                    pass
        
        return files
    
    def _extract_imports(self, content: str, ext: str) -> List[str]:
        """提取导入语句"""
        imports = []
        
        if ext in [".py"]:
            # Python imports
            patterns = [
                r"^import\s+(\S+)",
                r"^from\s+(\S+)\s+import",
            ]
            for pattern in patterns:
                imports.extend(re.findall(pattern, content, re.MULTILINE))
        
        elif ext in [".js", ".jsx", ".ts", ".tsx"]:
            # JavaScript/TypeScript imports
            patterns = [
                r"import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]",
                r"require\(['\"]([^'\"]+)['\"]\)",
            ]
            for pattern in patterns:
                imports.extend(re.findall(pattern, content))
        
        return imports[:20]  # 限制数量
    
    def _extract_classes(self, content: str, ext: str) -> List[str]:
        """提取类定义"""
        classes = []
        
        if ext == ".py":
            classes = re.findall(r"^class\s+(\w+)", content, re.MULTILINE)
        elif ext in [".js", ".jsx", ".ts", ".tsx"]:
            classes = re.findall(r"class\s+(\w+)", content)
        
        return classes
    
    def _extract_functions(self, content: str, ext: str) -> List[str]:
        """提取函数定义"""
        functions = []
        
        if ext == ".py":
            functions = re.findall(r"^def\s+(\w+)", content, re.MULTILINE)
        elif ext in [".js", ".jsx", ".ts", ".tsx"]:
            # function declarations and arrow functions
            patterns = [
                r"function\s+(\w+)",
                r"const\s+(\w+)\s*=\s*(?:async\s*)?\(",
                r"export\s+(?:async\s+)?function\s+(\w+)",
            ]
            for pattern in patterns:
                functions.extend(re.findall(pattern, content))
        
        return functions[:30]  # 限制数量
    
    def _parse_dependencies(self) -> Tuple[Dict[str, str], Dict[str, str]]:
        """解析项目依赖"""
        deps = {}
        dev_deps = {}
        
        # package.json
        pkg_json = self.project_root / "package.json"
        if pkg_json.exists():
            try:
                import json
                with open(pkg_json) as f:
                    pkg = json.load(f)
                deps.update(pkg.get("dependencies", {}))
                dev_deps.update(pkg.get("devDependencies", {}))
            except Exception:
                pass
        
        # requirements.txt
        req_txt = self.project_root / "requirements.txt"
        if req_txt.exists():
            try:
                for line in req_txt.read_text().splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        # 解析 package==version 或 package>=version
                        match = re.match(r"([a-zA-Z0-9_-]+)([<>=!]+)?(.*)?", line)
                        if match:
                            deps[match.group(1)] = match.group(3) or "*"
            except Exception:
                pass
        
        return deps, dev_deps
    
    def _extract_components(self, files: List[FileInfo]) -> List[ComponentInfo]:
        """提取前端组件"""
        components = []
        
        for f in files:
            if f.language in ["javascript", "typescript"] and any(
                x in f.path for x in ["components", "pages", "views"]
            ):
                # 简单提取组件名（文件名或目录名）
                path = Path(f.path)
                name = path.stem
                if name in ["index", "Index"]:
                    name = path.parent.name
                
                if name and name[0].isupper():
                    components.append(ComponentInfo(
                        name=name,
                        path=f.path,
                        dependencies=[i for i in f.imports if "/" in i or "@" in i],
                    ))
        
        return components
    
    def _extract_apis(self, files: List[FileInfo]) -> List[APIInfo]:
        """提取 API 接口"""
        apis = []
        
        # API 路径模式
        api_patterns = {
            "python": [
                r"@app\.(get|post|put|delete|patch)\(['\"]([^'\"]+)['\"]",
                r"@router\.(get|post|put|delete|patch)\(['\"]([^'\"]+)['\"]",
            ],
            "javascript": [
                r"router\.(get|post|put|delete|patch)\(['\"]([^'\"]+)['\"]",
                r"app\.(get|post|put|delete|patch)\(['\"]([^'\"]+)['\"]",
            ],
            "typescript": [
                r"@(Get|Post|Put|Delete|Patch)\(['\"]([^'\"]+)['\"]",
                r"router\.(get|post|put|delete|patch)\(['\"]([^'\"]+)['\"]",
            ],
        }
        
        for f in files:
            if f.language not in api_patterns:
                continue
            
            try:
                content = (self.project_root / f.path).read_text(encoding="utf-8", errors="ignore")
                
                for pattern in api_patterns[f.language]:
                    matches = re.findall(pattern, content, re.IGNORECASE)
                    for match in matches:
                        method, path = match
                        apis.append(APIInfo(
                            method=method.upper(),
                            path=path,
                            handler="",
                            file_path=f.path,
                        ))
            except Exception:
                pass
        
        return apis
    
    def _extract_models(self, files: List[FileInfo]) -> List[ModelInfo]:
        """提取数据模型"""
        models = []
        
        for f in files:
            # 只看模型相关文件
            if not any(x in f.path.lower() for x in ["model", "schema", "entity"]):
                continue
            
            for cls in f.classes:
                if any(x in cls.lower() for x in ["model", "schema", "entity", "base"]):
                    continue
                models.append(ModelInfo(
                    name=cls,
                    file_path=f.path,
                ))
        
        return models
    
    def _find_config_files(self) -> List[str]:
        """找配置文件"""
        config_patterns = [
            "*.config.*",
            ".env*",
            "tsconfig.json",
            "package.json",
            "requirements.txt",
            "pyproject.toml",
            "setup.py",
            "docker-compose*.yml",
            "Dockerfile*",
            ".eslintrc*",
            ".prettierrc*",
            "jest.config.*",
            "vite.config.*",
            "webpack.config.*",
            "next.config.*",
        ]
        
        configs = []
        for item in self.project_root.iterdir():
            if item.is_file():
                name = item.name
                for pattern in config_patterns:
                    if self._match_pattern(name, pattern):
                        configs.append(name)
                        break
        
        return configs
    
    def _match_pattern(self, name: str, pattern: str) -> bool:
        """简单模式匹配"""
        if "*" not in pattern:
            return name == pattern
        
        # 转换为正则
        regex = pattern.replace(".", r"\.").replace("*", ".*")
        return bool(re.match(regex, name))


class ImpactAnalyzer:
    """
    影响分析器
    
    分析新功能会影响哪些地方，评估风险
    """
    
    def __init__(self, project_structure: ProjectStructure):
        self.structure = project_structure
    
    def analyze(self, feature_description: str) -> ImpactAnalysis:
        """
        分析新功能的影响
        
        Args:
            feature_description: 新功能描述
            
        Returns:
            ImpactAnalysis: 影响分析结果
        """
        analysis = ImpactAnalysis(feature_description=feature_description)
        
        # 提取关键词
        keywords = self._extract_keywords(feature_description)
        
        # 分析会影响哪些文件
        analysis.affected_files = self._find_affected_files(keywords)
        
        # 分析 API 变更
        analysis.api_changes = self._analyze_api_changes(keywords)
        
        # 分析模型变更
        analysis.model_changes = self._analyze_model_changes(keywords)
        
        # 预测新增文件
        analysis.new_files = self._predict_new_files(keywords)
        
        # 评估风险
        analysis.overall_risk, analysis.risk_factors = self._assess_risk(analysis)
        
        # 生成建议
        analysis.recommendations = self._generate_recommendations(analysis)
        
        # 前置条件
        analysis.prerequisites = self._identify_prerequisites(analysis)
        
        # 测试要求
        analysis.test_requirements = self._generate_test_requirements(analysis)
        
        return analysis
    
    def _extract_keywords(self, description: str) -> Set[str]:
        """提取关键词"""
        keywords = set()
        
        # 功能关键词
        feature_keywords = {
            "登录": ["auth", "login", "user", "session"],
            "注册": ["auth", "register", "user", "signup"],
            "列表": ["list", "table", "pagination"],
            "详情": ["detail", "show", "view"],
            "编辑": ["edit", "update", "form"],
            "删除": ["delete", "remove"],
            "搜索": ["search", "filter", "query"],
            "上传": ["upload", "file", "storage"],
            "支付": ["payment", "order", "checkout"],
            "通知": ["notification", "message", "alert"],
            "权限": ["permission", "role", "access"],
            "评论": ["comment", "reply"],
            "点赞": ["like", "favorite"],
        }
        
        for cn_kw, en_kws in feature_keywords.items():
            if cn_kw in description:
                keywords.update(en_kws)
                keywords.add(cn_kw)
        
        # 提取英文词
        english_words = re.findall(r"[a-zA-Z]+", description.lower())
        keywords.update(english_words)
        
        return keywords
    
    def _find_affected_files(self, keywords: Set[str]) -> List[ImpactArea]:
        """找出会受影响的文件"""
        affected = []
        
        for f in self.structure.files:
            # 检查文件路径是否包含关键词
            path_lower = f.path.lower()
            
            for kw in keywords:
                if kw in path_lower:
                    risk = self._assess_file_risk(f)
                    affected.append(ImpactArea(
                        file_path=f.path,
                        reason=f"路径包含关键词: {kw}",
                        risk_level=risk,
                    ))
                    break
            
            # 检查文件内容（类名、函数名）
            for cls in f.classes:
                if any(kw in cls.lower() for kw in keywords):
                    risk = self._assess_file_risk(f)
                    affected.append(ImpactArea(
                        file_path=f.path,
                        reason=f"包含相关类: {cls}",
                        risk_level=risk,
                    ))
                    break
        
        # 去重
        seen = set()
        unique = []
        for item in affected:
            if item.file_path not in seen:
                seen.add(item.file_path)
                unique.append(item)
        
        return unique
    
    def _assess_file_risk(self, file_info: FileInfo) -> RiskLevel:
        """评估文件修改风险"""
        path = file_info.path.lower()
        
        # 核心文件高风险
        if any(x in path for x in ["config", "auth", "middleware", "base", "core"]):
            return RiskLevel.HIGH
        
        # 路由文件中等风险
        if any(x in path for x in ["router", "routes", "api"]):
            return RiskLevel.MEDIUM
        
        # 工具函数低风险
        if any(x in path for x in ["utils", "helpers", "common"]):
            return RiskLevel.LOW
        
        return RiskLevel.MEDIUM
    
    def _analyze_api_changes(self, keywords: Set[str]) -> List[Dict[str, Any]]:
        """分析 API 变更"""
        changes = []
        
        # 检查现有 API 是否需要修改
        for api in self.structure.apis:
            if any(kw in api.path.lower() for kw in keywords):
                changes.append({
                    "type": "modify",
                    "method": api.method,
                    "path": api.path,
                    "reason": "可能需要修改现有接口",
                })
        
        # 预测新增 API
        if "登录" in keywords or "login" in keywords:
            if not any(a.path == "/api/auth/login" for a in self.structure.apis):
                changes.append({
                    "type": "add",
                    "method": "POST",
                    "path": "/api/auth/login",
                    "reason": "需要新增登录接口",
                })
        
        return changes
    
    def _analyze_model_changes(self, keywords: Set[str]) -> List[Dict[str, Any]]:
        """分析模型变更"""
        changes = []
        
        for model in self.structure.models:
            if any(kw in model.name.lower() for kw in keywords):
                changes.append({
                    "type": "modify",
                    "model": model.name,
                    "file": model.file_path,
                    "reason": "可能需要添加新字段",
                })
        
        return changes
    
    def _predict_new_files(self, keywords: Set[str]) -> List[str]:
        """预测需要新增的文件"""
        new_files = []
        
        # 根据功能预测文件
        if "登录" in keywords or "auth" in keywords:
            if self.structure.project_type in ["frontend", "fullstack"]:
                new_files.extend([
                    "src/pages/Login.tsx",
                    "src/components/LoginForm.tsx",
                ])
            if self.structure.project_type in ["backend", "fullstack"]:
                new_files.extend([
                    "src/api/auth.py",
                    "src/services/auth_service.py",
                ])
        
        return new_files
    
    def _assess_risk(self, analysis: ImpactAnalysis) -> Tuple[RiskLevel, List[str]]:
        """评估总体风险"""
        factors = []
        score = 0
        
        # 受影响文件数量
        affected_count = len(analysis.affected_files)
        if affected_count > 10:
            factors.append(f"影响文件数量多: {affected_count} 个")
            score += 2
        elif affected_count > 5:
            factors.append(f"影响文件数量中等: {affected_count} 个")
            score += 1
        
        # 高风险文件
        high_risk_count = sum(1 for a in analysis.affected_files if a.risk_level == RiskLevel.HIGH)
        if high_risk_count > 0:
            factors.append(f"涉及 {high_risk_count} 个核心文件")
            score += high_risk_count
        
        # API 变更
        if len(analysis.api_changes) > 3:
            factors.append(f"需要修改 {len(analysis.api_changes)} 个 API")
            score += 1
        
        # 模型变更
        if analysis.model_changes:
            factors.append(f"需要修改数据模型")
            score += 1
        
        # 确定风险等级
        if score >= 5:
            level = RiskLevel.CRITICAL
        elif score >= 3:
            level = RiskLevel.HIGH
        elif score >= 1:
            level = RiskLevel.MEDIUM
        else:
            level = RiskLevel.LOW
        
        return level, factors
    
    def _generate_recommendations(self, analysis: ImpactAnalysis) -> List[str]:
        """生成建议"""
        recommendations = []
        
        if analysis.overall_risk in [RiskLevel.HIGH, RiskLevel.CRITICAL]:
            recommendations.append("建议分阶段实现，先实现核心功能，再逐步完善")
            recommendations.append("建议先编写单元测试，再进行开发")
        
        if analysis.api_changes:
            recommendations.append("建议先定义 API 接口文档，前后端协商一致后再开发")
        
        if analysis.model_changes:
            recommendations.append("建议先设计数据模型变更，确认兼容性后再执行迁移")
        
        if len(analysis.affected_files) > 5:
            recommendations.append("涉及文件较多，建议拆分为多个子任务")
        
        return recommendations
    
    def _identify_prerequisites(self, analysis: ImpactAnalysis) -> List[str]:
        """识别前置条件"""
        prereqs = []
        
        # 检查依赖是否齐全
        if "auth" in analysis.feature_description.lower():
            if "jwt" not in self.structure.dependencies and "jsonwebtoken" not in self.structure.dependencies:
                prereqs.append("需要先安装 JWT 相关依赖")
        
        # 数据库迁移
        if analysis.model_changes:
            prereqs.append("需要先执行数据库迁移")
        
        return prereqs
    
    def _generate_test_requirements(self, analysis: ImpactAnalysis) -> List[str]:
        """生成测试要求"""
        tests = []
        
        for area in analysis.affected_files:
            if area.risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL]:
                tests.append(f"需要为 {area.file_path} 添加/更新测试")
        
        if analysis.api_changes:
            tests.append("需要添加 API 集成测试")
        
        return tests


def format_project_analysis(structure: ProjectStructure) -> str:
    """格式化项目分析结果"""
    lines = [
        "# 项目分析报告",
        "",
        f"**项目路径**: `{structure.root_path}`",
        f"**项目类型**: {structure.project_type}",
        f"**文件总数**: {structure.total_files}",
        "",
        "## 目录结构",
        "",
    ]
    
    for dir_name, purpose in structure.directories.items():
        lines.append(f"- `{dir_name}/` - {purpose or '未知'}")
    
    lines.extend([
        "",
        "## 文件统计",
        "",
        "| 语言 | 文件数 |",
        "|------|--------|",
    ])
    
    for lang, count in sorted(structure.files_by_language.items(), key=lambda x: -x[1]):
        lines.append(f"| {lang} | {count} |")
    
    if structure.dependencies:
        lines.extend([
            "",
            "## 主要依赖",
            "",
        ])
        for dep, version in list(structure.dependencies.items())[:15]:
            lines.append(f"- {dep}: {version}")
    
    if structure.components:
        lines.extend([
            "",
            "## 组件列表",
            "",
        ])
        for comp in structure.components[:20]:
            lines.append(f"- `{comp.name}` ({comp.path})")
    
    if structure.apis:
        lines.extend([
            "",
            "## API 接口",
            "",
            "| 方法 | 路径 | 文件 |",
            "|------|------|------|",
        ])
        for api in structure.apis[:20]:
            lines.append(f"| {api.method} | {api.path} | {api.file_path} |")
    
    if structure.models:
        lines.extend([
            "",
            "## 数据模型",
            "",
        ])
        for model in structure.models[:20]:
            lines.append(f"- `{model.name}` ({model.file_path})")
    
    return "\n".join(lines)


def format_impact_analysis(analysis: ImpactAnalysis) -> str:
    """格式化影响分析结果"""
    risk_icons = {
        RiskLevel.LOW: "🟢",
        RiskLevel.MEDIUM: "🟡",
        RiskLevel.HIGH: "🟠",
        RiskLevel.CRITICAL: "🔴",
    }
    
    lines = [
        "# 影响分析报告",
        "",
        f"**功能**: {analysis.feature_description}",
        f"**总体风险**: {risk_icons[analysis.overall_risk]} {analysis.overall_risk.value}",
        "",
    ]
    
    if analysis.risk_factors:
        lines.extend([
            "## ⚠️ 风险因素",
            "",
        ])
        for factor in analysis.risk_factors:
            lines.append(f"- {factor}")
        lines.append("")
    
    if analysis.affected_files:
        lines.extend([
            "## 📁 受影响的文件",
            "",
            "| 风险 | 文件 | 原因 |",
            "|------|------|------|",
        ])
        for area in analysis.affected_files:
            icon = risk_icons[area.risk_level]
            lines.append(f"| {icon} | `{area.file_path}` | {area.reason} |")
        lines.append("")
    
    if analysis.new_files:
        lines.extend([
            "## ➕ 需要新增的文件",
            "",
        ])
        for f in analysis.new_files:
            lines.append(f"- `{f}`")
        lines.append("")
    
    if analysis.api_changes:
        lines.extend([
            "## 🔌 API 变更",
            "",
        ])
        for change in analysis.api_changes:
            lines.append(f"- [{change['type']}] {change['method']} {change['path']} - {change['reason']}")
        lines.append("")
    
    if analysis.prerequisites:
        lines.extend([
            "## 📋 前置条件",
            "",
        ])
        for prereq in analysis.prerequisites:
            lines.append(f"- [ ] {prereq}")
        lines.append("")
    
    if analysis.recommendations:
        lines.extend([
            "## 💡 建议",
            "",
        ])
        for rec in analysis.recommendations:
            lines.append(f"- {rec}")
        lines.append("")
    
    if analysis.test_requirements:
        lines.extend([
            "## 🧪 测试要求",
            "",
        ])
        for test in analysis.test_requirements:
            lines.append(f"- [ ] {test}")
    
    return "\n".join(lines)


# ============================================================
# 快捷函数
# ============================================================

def analyze_project(project_path: str) -> ProjectStructure:
    """分析项目结构"""
    analyzer = ProjectAnalyzer(project_path)
    return analyzer.analyze()


def analyze_impact(project_structure: ProjectStructure, feature: str) -> ImpactAnalysis:
    """分析新功能影响"""
    analyzer = ImpactAnalyzer(project_structure)
    return analyzer.analyze(feature)
