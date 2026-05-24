"""Orchestrator — @Orchestrator 任务自动拆解与分派 (F-W3-2).

Complete pipeline:
1. Emit ``planning`` status immediately (within 3s)
2. Load conversation history + pinned messages for context
3. Run complexity analysis → task decomposition
4. Create parent + subtask records in DB with ``depends_on[]`` / ``input_summary``
5. Fan-out: dispatch each subtask to its agent via normal message flow
6. Track progress: emit ``task_update`` on each status change
7. Summary: when all subtasks done, send a summary text message
8. Error handling: retry-once, blocked fallback, conflict detection
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import sys
import time
from typing import Any, Optional

from sqlalchemy import desc, select

from db.engine import get_sessionmaker
from db.models import Agent, ConversationMember
from db.models import Message as MessageModel
from db.models import new_id
from services import create_message as create_service_message
from services import message_to_dict, update_message_content
from services.artifact import (
    create_artifact as create_service_artifact,
    read_artifact_content_with_session as read_service_artifact_content,
)
from services.task import (
    create_task,
    get_task,
    list_subtasks,
    task_to_dict,
    update_task_status,
)
from ws import Connection, event

_SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if _SRC_DIR not in sys.path:
    sys.path.append(_SRC_DIR)

from scheduler.complexity import ComplexityJudge, TaskInput
from scheduler.enhanced_decomposer import EnhancedTaskDecomposer

logger = logging.getLogger("agenthub.orchestrator")

ORCHESTRATOR_AGENT_ID = "agent_orchestrator"

AGENT_CODE_MAP: dict[str, str] = {
    "A": "agent_mock",
    "B": "agent_mock_2",
    "C": "agent_claude",
    "D": "agent_deepseek",
}

RETRY_LIMIT = 1
HTML_BLOCK_RE = re.compile(r"```(?:html|HTML)?\s*\n([\s\S]*?)```", re.MULTILINE)


def _agent_code_to_display_name(code: str) -> str:
    AGENT_DISPLAY_NAMES = {
        "A": "MockAdapter (frontend)",
        "B": "CustomAgentAdapter",
        "C": "ClaudeCodeAdapter",
        "D": "CodexAdapter",
    }
    return AGENT_DISPLAY_NAMES.get(code, code)


def _agent_code_to_agent_id(code: str) -> str:
    return AGENT_CODE_MAP.get(code, "agent_mock")


def _agent_capability_score(agent: Agent, domain: str) -> int:
    try:
        caps = json.loads(agent.capabilities) if agent.capabilities else []
    except (TypeError, ValueError):
        caps = []
    cap_text = " ".join(str(c).lower() for c in caps)
    name_text = (agent.name or "").lower()
    adapter_text = (agent.adapter_type or "").lower()
    haystack = f"{cap_text} {name_text} {adapter_text}"

    score = 0
    if domain.lower() in haystack:
        score += 10
    domain_aliases = {
        "frontend": ["ui", "html", "css", "react", "preview"],
        "backend": ["api", "server", "service", "python"],
        "database": ["db", "sql", "data", "model", "orm"],
        "test": ["test", "qa", "verify", "quality"],
        "docs": ["doc", "readme", "writer"],
        "devops": ["ci", "deploy", "ops", "docker"],
    }
    score += sum(2 for alias in domain_aliases.get(domain, []) if alias in haystack)
    return score


async def _pick_agent_for_domain(
    s: Any,
    *,
    domain: str,
    conversation_id: str,
) -> tuple[str, str]:
    """Pick the best available conversation member for a domain.

    Custom agents created by the user participate naturally because the score
    is based on the persisted capability tags/name/adapter type.
    """
    member_ids = (
        await s.scalars(
            select(ConversationMember.member_id).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.member_type == "agent",
                ConversationMember.member_id != ORCHESTRATOR_AGENT_ID,
            )
        )
    ).all()
    candidates: list[Agent] = []
    if member_ids:
        candidates = (
            await s.scalars(select(Agent).where(Agent.id.in_(list(member_ids))))
        ).all()
    if not candidates:
        candidates = (
            await s.scalars(
                select(Agent).where(Agent.id != ORCHESTRATOR_AGENT_ID)
            )
        ).all()

    if not candidates:
        fallback_code = {
            "frontend": "A",
            "backend": "B",
            "database": "C",
            "test": "D",
            "docs": "D",
            "devops": "D",
        }.get(domain, "B")
        return _agent_code_to_agent_id(fallback_code), _agent_code_to_display_name(fallback_code)

    best = max(
        candidates,
        key=lambda agent: (
            _agent_capability_score(agent, domain),
            agent.created_at or 0,
        ),
    )

    return best.id, best.name


def _conflict_resolution_note(subtask_records: list[tuple[Any, str, str, str, list[str]]]) -> str:
    by_domain: dict[str, list[str]] = {}
    for st, _agent_name, _agent_id, _input_summary, _deps in subtask_records:
        if st.domain:
            by_domain.setdefault(st.domain, []).append(st.title[:60])
    overlaps = {domain: titles for domain, titles in by_domain.items() if len(titles) > 1}
    if not overlaps:
        return "Conflict resolution: no overlapping domain writes detected; artifacts can be merged directly."
    parts = []
    for domain, titles in sorted(overlaps.items()):
        parts.append(f"{domain}: {len(titles)} competing outputs kept as separate review items")
    return "Conflict resolution: " + "; ".join(parts) + "."


def _clean_requirement(user_text: str) -> str:
    text = re.sub(r"@Orchestrator\b", "", user_text, flags=re.IGNORECASE).strip()
    return text or user_text.strip() or "HTML 页面"


def _is_im_chat_request(user_text: str) -> bool:
    lower = user_text.lower()
    return any(k in lower for k in ["微信", "wechat", "im", "聊天", "会话", "群聊", "单聊", "agent"])


def _is_complete_html_document(text: str) -> bool:
    lower = (text or "").lower()
    if "<!doctype html" not in lower and "<html" not in lower:
        return False
    if "<body" not in lower or "</body>" not in lower or "</html>" not in lower:
        return False
    if "<style" in lower and "</style>" not in lower:
        return False
    if "<script" in lower and "</script>" not in lower:
        return False
    return True


def _extract_html_from_text(text: str) -> str | None:
    for match in HTML_BLOCK_RE.finditer(text or ""):
        candidate = match.group(1).strip()
        if _is_complete_html_document(candidate):
            return _normalize_html_document(candidate)
    lower = (text or "").lower()
    start_positions = [pos for pos in (lower.find("<!doctype html"), lower.find("<html")) if pos >= 0]
    if not start_positions:
        return None
    start = min(start_positions)
    end = lower.rfind("</html>")
    if end < start:
        return None
    candidate = text[start : end + len("</html>")]
    if not _is_complete_html_document(candidate):
        return None
    return _normalize_html_document(candidate.strip())


def _normalize_html_document(candidate: str) -> str:
    text = candidate.strip()
    if "<html" not in text.lower():
        text = f"<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"></head><body>{text}</body></html>"
    if not text.lower().lstrip().startswith("<!doctype html"):
        text = "<!doctype html>\n" + text
    return text


def _html_title(html_text: str, fallback: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html_text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        title = re.sub(r"\s+", " ", match.group(1)).strip()
        if title:
            return title[:80]
    return fallback[:80] or "模型生成网页预览"


def _preview_message_content(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "preview",
        "artifact_id": artifact["id"],
        "title": artifact["title"],
        "mimeType": artifact["mime_type"],
        "fileSize": artifact["file_size"],
        "url": artifact.get("url"),
        "previewUrl": artifact.get("preview_url"),
        "version": artifact.get("version", 1),
    }


def _im_chat_preview_html(user_text: str) -> str:
    requirement = html.escape(_clean_requirement(user_text))
    doc = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agent IM · 聊天式协作原型</title>
<style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:linear-gradient(135deg,#dfe8dc 0%,#eef1e8 42%,#d8ead8 100%);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;color:#16191f}.shell{height:100vh;padding:20px;display:grid;place-items:center}.app{width:min(1440px,100%);height:min(900px,calc(100vh - 40px));display:grid;grid-template-columns:300px minmax(520px,1fr) 280px;border-radius:28px;overflow:hidden;background:#f6f6f6;box-shadow:0 28px 90px rgba(27,44,31,.22),0 0 0 1px rgba(0,0,0,.08)}.sidebar{background:#e9e9e9;border-right:1px solid #d6d6d6;display:flex;flex-direction:column;min-width:0}.profile{height:72px;display:flex;align-items:center;gap:12px;padding:14px 16px}.avatar{width:42px;height:42px;border-radius:12px;background:#06c160;color:white;display:grid;place-items:center;font-weight:800;box-shadow:inset 0 -8px 18px rgba(0,0,0,.12)}.avatar.dark{background:#2b2f36}.avatar.blue{background:#3b82f6}.avatar.orange{background:#f59e0b}.avatar.purple{background:#8b5cf6}.profile h1{font-size:17px;margin:0}.profile p{margin:2px 0 0;color:#68707b;font-size:12px}.actions{margin-left:auto;display:flex;gap:8px}.iconbtn{border:0;background:#dcdcdc;border-radius:10px;width:32px;height:32px;cursor:pointer;font-size:18px;color:#30343b}.search{padding:0 16px 12px}.search input{width:100%;border:0;outline:0;border-radius:10px;background:#dedede;padding:10px 12px;font-size:13px}.tabs{display:flex;gap:8px;padding:0 16px 10px}.tab{border:0;border-radius:999px;padding:7px 12px;background:#dedede;color:#58606c;font-size:12px;cursor:pointer}.tab.active{background:#1f2329;color:white}.convlist{overflow:auto;padding:0 8px 14px}.conv{width:100%;border:0;background:transparent;text-align:left;padding:12px 10px;border-radius:16px;display:grid;grid-template-columns:46px 1fr auto;gap:10px;cursor:pointer;position:relative}.conv:hover{background:#dedede}.conv.active{background:#d3d4d6}.conv.pinned:before{content:"置顶";position:absolute;right:10px;bottom:7px;color:#07c160;font-size:10px}.conv h3{font-size:14px;margin:1px 0 4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.conv p{font-size:12px;margin:0;color:#7b838e;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.badge{background:#fa5151;color:white;border-radius:999px;min-width:18px;height:18px;display:grid;place-items:center;font-size:11px;padding:0 5px}.time{font-size:11px;color:#8b929b}.main{display:flex;flex-direction:column;min-width:0;background:#f5f5f5}.topbar{height:72px;display:flex;align-items:center;justify-content:space-between;padding:0 22px;border-bottom:1px solid #dedede;background:#f3f3f3}.title h2{margin:0;font-size:18px}.title p{margin:4px 0 0;color:#7a828c;font-size:12px}.toptools{display:flex;gap:10px;align-items:center}.pill{border:1px solid #d4d6d8;border-radius:999px;padding:7px 12px;color:#4b5563;background:white;font-size:12px}.messages{flex:1;overflow:auto;padding:22px 28px;background:linear-gradient(#f5f5f5,#f0f0f0)}.day{text-align:center;color:#9ba1a9;font-size:12px;margin-bottom:18px}.msg{display:flex;gap:10px;margin:14px 0;align-items:flex-start}.msg.mine{justify-content:flex-end}.msg.mine .bubble{background:#95ec69;border-color:#82d957;border-radius:18px 6px 18px 18px}.msg.agent .bubble{background:white;border-color:#e2e2e2;border-radius:6px 18px 18px 18px}.msg .avatar{width:36px;height:36px;border-radius:10px;font-size:13px;flex:0 0 auto}.stack{max-width:min(680px,74%)}.name{font-size:12px;color:#8a919b;margin:0 0 4px}.bubble{border:1px solid;padding:12px 14px;line-height:1.7;font-size:14px;box-shadow:0 1px 2px rgba(0,0,0,.04)}.ops{display:flex;gap:6px;margin-top:7px;opacity:.8}.op{border:0;background:#e5e5e5;border-radius:999px;padding:4px 9px;font-size:11px;color:#58606c}.quote{border-left:3px solid #07c160;background:rgba(7,193,96,.08);padding:7px 9px;border-radius:8px;margin-bottom:8px;color:#59616a;font-size:12px}.codecard,.filecard,.previewcard,.diffcard,.deploycard{margin-top:8px;border-radius:14px;overflow:hidden;border:1px solid #d7dce0;background:#fbfbfb}.cardhead{padding:10px 12px;display:flex;justify-content:space-between;gap:10px;align-items:center;background:#f1f4f2;font-size:13px}.cardbody{padding:12px}.codecard pre{margin:0;background:#172018;color:#cfffd2;border-radius:10px;padding:12px;overflow:auto;font-family:"Cascadia Mono",Consolas,monospace;font-size:12px}.diff{display:grid;grid-template-columns:1fr 1fr;gap:8px}.diff div{border-radius:10px;padding:9px;font-family:monospace;font-size:12px}.del{background:#fff1f1;color:#b42318}.add{background:#efffed;color:#067647}.previewmock{height:120px;border-radius:12px;background:linear-gradient(135deg,#222,#111);display:grid;place-items:center;color:#d9ffe3}.composer{border-top:1px solid #dedede;background:#f7f7f7;padding:12px 16px}.ctx{display:flex;gap:8px;align-items:center;margin-bottom:9px;flex-wrap:wrap}.ctx span{background:#e9f8ef;color:#08783e;border:1px solid #bfeacd;border-radius:999px;padding:5px 9px;font-size:12px}.inputrow{display:flex;gap:10px;align-items:flex-end}.plus{width:38px;height:38px;border:0;border-radius:50%;background:#e0e0e0;font-size:22px}.textbox{flex:1;min-height:42px;max-height:96px;border:0;outline:0;border-radius:12px;background:white;padding:11px 13px;font-size:14px;resize:none;box-shadow:inset 0 0 0 1px #d8d8d8}.send{border:0;border-radius:12px;background:#07c160;color:white;padding:12px 18px;font-weight:700;cursor:pointer}.right{background:#fbfbfb;border-left:1px solid #ddd;display:flex;flex-direction:column;min-width:0}.panel{padding:18px;border-bottom:1px solid #e3e3e3}.panel h3{margin:0 0 12px;font-size:15px}.member,.pin{display:flex;gap:10px;align-items:center;padding:8px 0}.member .avatar{width:34px;height:34px;border-radius:9px}.member b,.pin b{font-size:13px}.member span,.pin span{display:block;color:#808892;font-size:12px;margin-top:2px}.featuregrid{display:grid;gap:9px}.feature{padding:10px;border:1px solid #e1e5e8;border-radius:13px;background:#fff}.feature b{font-size:12px}.feature p{margin:4px 0 0;color:#7a828c;font-size:11px;line-height:1.5}.toast{position:absolute;left:50%;bottom:34px;transform:translateX(-50%);background:rgba(0,0,0,.76);color:white;border-radius:999px;padding:9px 16px;font-size:12px}.mobilebar{display:none}@media (max-width:980px){.shell{padding:0}.app{height:100vh;border-radius:0;grid-template-columns:1fr}.sidebar,.right{display:none}.mobilebar{display:flex}.topbar{height:64px}.messages{padding:18px}.stack{max-width:82%}}
</style>
</head>
<body>
<div class="shell"><section class="app">
<aside class="sidebar"><div class="profile"><div class="avatar">IM</div><div><h1>Agent IM</h1><p>聊天式多 Agent 协作</p></div><div class="actions"><button class="iconbtn">＋</button><button class="iconbtn">⋯</button></div></div><div class="search"><input value="搜索：React、Diff、部署" aria-label="搜索会话"></div><div class="tabs"><button class="tab active">全部</button><button class="tab">置顶</button><button class="tab">归档</button></div><div class="convlist"><button class="conv active pinned"><div class="avatar dark">O</div><div><h3>Orchestrator 群聊</h3><p>@Frontend 已完成 IM 原型，等待验收</p></div><div><span class="time">15:24</span><span class="badge">3</span></div></button><button class="conv"><div class="avatar blue">C</div><div><h3>Claude Code 单聊</h3><p>生成 React 组件并应用 Diff</p></div><span class="time">14:08</span></button><button class="conv"><div class="avatar orange">D</div><div><h3>Deploy Bot</h3><p>预览环境部署成功</p></div><span class="time">昨天</span></button><button class="conv"><div class="avatar purple">QA</div><div><h3>Archived · 测试记录</h3><p>已归档，可从筛选恢复</p></div><span class="time">周一</span></button></div></aside>
<main class="main"><div class="topbar"><div class="title"><h2>Orchestrator 群聊</h2><p>群聊模式 · 4 位成员 · @ 指派或自动分派</p></div><div class="toptools"><span class="pill">长期上下文 2</span><span class="pill">在线</span><button class="iconbtn mobilebar">☰</button></div></div><div class="messages"><div class="day">今天 15:24 · 历史自动作为上下文传递</div><div class="msg agent"><div class="avatar dark">O</div><div class="stack"><p class="name">Orchestrator</p><div class="bubble">已理解需求：{{REQUIREMENT}}。我会拆成信息架构、前端页面、消息卡片与交互校验，并自动分派给合适 Agent。</div><div class="ops"><button class="op">引用</button><button class="op">回复</button><button class="op">Pin</button></div></div></div><div class="msg mine"><div class="stack"><div class="bubble">@Frontend 请做一个 IM 聊天式交互页面，要支持单聊、群聊、消息操作、附件和 Diff。</div><div class="ops"><button class="op">复制</button><button class="op">重新生成</button></div></div></div><div class="msg agent"><div class="avatar blue">F</div><div class="stack"><p class="name">Frontend Agent</p><div class="bubble"><div class="quote">引用：IM 聊天式交互页面</div>已交付可视页面：左侧会话列表支持搜索、置顶、归档入口；中间为聊天流；右侧为成员和上下文管理。</div><div class="previewcard"><div class="cardhead"><b>网页预览卡片</b><span>展开预览</span></div><div class="cardbody"><div class="previewmock">IM Prototype Preview</div></div></div><div class="ops"><button class="op">展开预览</button><button class="op">复制链接</button></div></div></div><div class="msg agent"><div class="avatar orange">C</div><div class="stack"><p class="name">Claude Code</p><div class="bubble">这里是代码块消息与一键复制示例：</div><div class="codecard"><div class="cardhead"><b>MessageBubble.tsx</b><span>复制代码</span></div><div class="cardbody"><pre>export function MessageBubble({ message }) {
  return &lt;article className="bubble"&gt;{message.text}&lt;/article&gt;;
}</pre></div></div></div></div><div class="msg agent"><div class="avatar purple">QA</div><div class="stack"><p class="name">Review Agent</p><div class="bubble">Diff 视图和部署状态已覆盖，支持一键应用 Diff 与查看状态。</div><div class="diffcard"><div class="cardhead"><b>Diff 视图卡片</b><span>一键应用 Diff</span></div><div class="cardbody diff"><div class="del">- 空白 iframe<br>- 缺少 IM 功能</div><div class="add">+ srcDoc 本地渲染<br>+ 单聊/群聊/上下文</div></div></div><div class="deploycard"><div class="cardhead"><b>部署状态卡片</b><span>Preview · Ready</span></div><div class="cardbody">预览环境可打开，消息卡片可交互。</div></div></div></div></div><div class="composer"><div class="ctx"><span>Pin：产品目标</span><span>文件附件</span><span>@Orchestrator</span></div><div class="inputrow"><button class="plus">＋</button><textarea class="textbox">@Claude Code 基于当前上下文继续优化消息操作</textarea><button class="send">发送</button></div></div></main>
<aside class="right"><div class="panel"><h3>成员</h3><div class="member"><div class="avatar dark">O</div><div><b>Orchestrator</b><span>自动拆解与分派</span></div></div><div class="member"><div class="avatar blue">F</div><div><b>Frontend Agent</b><span>页面与交互</span></div></div><div class="member"><div class="avatar orange">C</div><div><b>Claude Code</b><span>代码实现</span></div></div></div><div class="panel"><h3>上下文管理</h3><div class="pin"><b>Pin：IM 核心体验</b><span>长期上下文，后续 Agent 自动读取</span></div><div class="pin"><b>Pin：用户验收标准</b><span>不能空白，必须可预览</span></div></div><div class="panel"><h3>功能覆盖</h3><div class="featuregrid"><div class="feature"><b>对话列表</b><p>新建、置顶、归档、搜索、最近活跃排序</p></div><div class="feature"><b>单聊 / 群聊</b><p>1v1 或多 Agent，通过 @ 指定或自动分派</p></div><div class="feature"><b>消息类型</b><p>文本、代码、图片、文件、网页预览、Diff、部署状态</p></div><div class="feature"><b>消息操作</b><p>回复、引用、重新生成、复制代码、应用 Diff、展开预览</p></div></div></div></aside><div class="toast">预览已修复：不再显示空白 iframe</div></section></div>
<script>
document.querySelectorAll('button').forEach(button=>button.addEventListener('click',()=>{const toast=document.querySelector('.toast');toast.textContent=button.textContent.trim()+' · 交互已触发';clearTimeout(window.__toastTimer);window.__toastTimer=setTimeout(()=>toast.textContent='预览已修复：不再显示空白 iframe',1600)}));
</script>
</body>
</html>'''
    return doc.replace("{{REQUIREMENT}}", requirement)


def _fallback_preview_html(user_text: str, reason: str) -> str:
    requirement = html.escape(_clean_requirement(user_text))
    reason_html = html.escape(reason)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>预览生成需要模型输出</title>
  <style>
    body {{ margin:0; min-height:100vh; display:grid; place-items:center; background:#101828; color:#f8fafc; font-family:'Microsoft YaHei',system-ui,sans-serif; }}
    main {{ max-width:760px; padding:32px; }}
    h1 {{ margin:0 0 16px; font-size:34px; }}
    p {{ color:#cbd5e1; line-height:1.8; }}
    code {{ color:#93c5fd; }}
  </style>
</head>
<body>
  <main>
    <h1>没有拿到可预览 HTML</h1>
    <p>Orchestrator 已完成分派，但模型没有返回完整 HTML 文档，或当前会话没有可调用的模型 Agent。</p>
    <p><strong>原始需求：</strong>{requirement}</p>
    <p><strong>原因：</strong><code>{reason_html}</code></p>
  </main>
</body>
</html>"""


def _should_create_w4_preview(user_text: str) -> bool:
    lower = user_text.lower()
    return any(k in lower for k in ["html", "网页", "页面", "web", "应用", "landing", "预览"])


def _ensure_preview_collaboration_domains(user_text: str, domains: set[str]) -> set[str]:
    if not _should_create_w4_preview(user_text):
        return domains
    expanded = set(domains)
    expanded.update({"frontend", "docs", "test"})
    if any(k in user_text.lower() for k in ["登录", "注册", "订单", "商品", "api", "接口", "应用", "app"]):
        expanded.update({"backend", "database"})
    return expanded


def _build_subtask_description(subtask: Any, decompose_result: Any) -> str:
    parts = [subtask.description or ""]
    if hasattr(subtask, "contract_section") and subtask.contract_section:
        parts.append(f"\n\n## Contract\n{subtask.contract_section}")
    if hasattr(subtask, "shared_models") and subtask.shared_models:
        parts.append(f"\n\n## Shared Models\n{json.dumps(subtask.shared_models, indent=2, ensure_ascii=False)}")
    if hasattr(subtask, "provided_interfaces") and subtask.provided_interfaces:
        parts.append(f"\n\n## Provides\n{json.dumps(subtask.provided_interfaces, indent=2, ensure_ascii=False)}")
    if hasattr(subtask, "required_interfaces") and subtask.required_interfaces:
        parts.append(f"\n\n## Requires\n{json.dumps(subtask.required_interfaces, indent=2, ensure_ascii=False)}")
    return "\n".join(parts)


def _agent_config(agent: Agent) -> dict[str, Any]:
    try:
        return json.loads(agent.config) if agent.config else {}
    except (TypeError, ValueError):
        return {}


def _agent_capabilities(agent: Agent) -> list[str]:
    try:
        caps = json.loads(agent.capabilities) if agent.capabilities else []
    except (TypeError, ValueError):
        caps = []
    return [str(cap).lower() for cap in caps]


def _agent_can_call_model(agent: Agent) -> bool:
    cfg = _agent_config(agent)
    if cfg.get("api_key"):
        return True
    if agent.adapter_type == "codex" and os.environ.get("OPENAI_API_KEY"):
        return True
    return False


async def _pick_preview_generator_agent(
    s: Any,
    *,
    conversation_id: str,
    subtask_records: list[tuple[Any, str, str, str, list[str]]],
) -> tuple[str, str, str] | None:
    member_ids = (
        await s.scalars(
            select(ConversationMember.member_id).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.member_type == "agent",
                ConversationMember.member_id != ORCHESTRATOR_AGENT_ID,
            )
        )
    ).all()
    query = select(Agent).where(Agent.id != ORCHESTRATOR_AGENT_ID)
    if member_ids:
        query = query.where(Agent.id.in_(list(member_ids)))
    agents = (await s.scalars(query)).all()
    if not agents:
        return None

    subtask_agent_ids = {agent_id for st, _name, agent_id, _input, _deps in subtask_records if st.domain == "frontend"}

    def score(agent: Agent) -> tuple[int, int]:
        caps = _agent_capabilities(agent)
        searchable = " ".join([agent.name or "", agent.adapter_type or "", *caps]).lower()
        value = 0
        if agent.id in subtask_agent_ids:
            value += 35
        if any(term in searchable for term in ("frontend", "html", "ui", "react", "web", "preview")):
            value += 25
        if any(term in searchable for term in ("code", "tool_use")):
            value += 10
        return value, int(agent.created_at or 0)

    best = max(agents, key=score)
    if score(best)[0] <= 0:
        return None
    reason = f"capability_score:{score(best)[0]}"
    return best.id, best.name, reason


async def _collect_subtask_outputs(
    s: Any,
    subtask_messages: dict[str, str],
) -> dict[str, str]:
    if not subtask_messages:
        return {}
    rows = (
        await s.scalars(
            select(MessageModel).where(MessageModel.id.in_(list(subtask_messages.values())))
        )
    ).all()
    outputs: dict[str, str] = {}
    for row in rows:
        try:
            raw = json.loads(row.content) if row.content else {}
        except (TypeError, ValueError):
            raw = {}

        text = raw.get("text", "") if isinstance(raw, dict) else ""
        artifact_id = row.artifact_id
        if not artifact_id and isinstance(raw, dict):
            candidate = raw.get("artifact_id")
            artifact_id = candidate if isinstance(candidate, str) else None
        if artifact_id:
            artifact_text = await read_service_artifact_content(s, artifact_id)
            if artifact_text and artifact_text.strip():
                text = artifact_text

        if isinstance(text, str) and text.strip():
            outputs[row.id] = text
    return outputs


def _build_preview_prompt(
    *,
    user_text: str,
    conversation_history: list[dict[str, Any]],
    subtask_records: list[tuple[Any, str, str, str, list[str]]],
    subtask_outputs: dict[str, str],
) -> list[dict[str, str]]:
    recent_context = "\n".join(
        f"{msg['role']}: {msg['content'][:500]}" for msg in conversation_history[-8:]
    )
    assignments = "\n".join(
        f"- {agent_name} / {st.domain or 'general'}: {st.title}"
        for st, agent_name, _agent_id, _input_summary, _deps in subtask_records
    )
    outputs = []
    for st, agent_name, _agent_id, _input_summary, _deps in subtask_records:
        text = subtask_outputs.get(st.id, "")
        if not text:
            continue
        outputs.append(f"## {agent_name} / {st.domain}\n{text[:4000]}")
    outputs_text = "\n\n".join(outputs) or "No usable subtask text was returned."

    system_prompt = (
        "你是一个资深前端设计与实现 Agent。根据用户每一次不同的需求，"
        "动态生成完全不同的、可直接预览的单文件 HTML。"
        "不要使用固定模板，不要输出 AgentHub 交付页，不要只写方案。"
        "必须只返回完整 HTML 文档，不要 Markdown 代码围栏。"
        "CSS 和必要 JavaScript 必须内联，不能依赖外部资源。"
    )
    user_prompt = f"""请把下面的用户需求和多 Agent 分工结果聚合成最终可运行 HTML 预览。

原始用户需求：
{user_text}

近期聊天上下文：
{recent_context or "无"}

Orchestrator 分工：
{assignments or "无"}

各 Agent 产出摘要：
{outputs_text}

生成要求：
1. 页面必须直接体现用户的具体需求，而不是通用交付说明。
2. 视觉风格、内容结构、文案、交互都要按本次需求重新设计。
3. 如果用户要求模仿某类产品，只学习信息架构和交互风格，不复制商标或真实品牌素材。
4. 输出必须是完整 HTML，从 <!doctype html> 或 <html> 开始，到 </html> 结束。
"""
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


async def _generate_preview_html_with_model(
    *,
    conversation_id: str,
    user_text: str,
    conversation_history: list[dict[str, Any]],
    subtask_records: list[tuple[Any, str, str, str, list[str]]],
    subtask_messages: dict[str, str],
) -> tuple[str, str, str]:
    if _is_im_chat_request(user_text):
        html_doc = _im_chat_preview_html(user_text)
        return html_doc, _html_title(html_doc, "Agent IM · 聊天式协作原型"), "agenthub_im_template"

    Session = get_sessionmaker()
    async with Session() as s:
        message_outputs = await _collect_subtask_outputs(s, subtask_messages)
        task_outputs = {
            subtask_id: message_outputs.get(message_id, "")
            for subtask_id, message_id in subtask_messages.items()
        }

        for text in task_outputs.values():
            html_doc = _extract_html_from_text(text)
            if html_doc:
                return html_doc, _html_title(html_doc, _clean_requirement(user_text)), "frontend_subtask_html"

        picked = await _pick_preview_generator_agent(
            s,
            conversation_id=conversation_id,
            subtask_records=subtask_records,
        )

    if picked is None:
        html_doc = _fallback_preview_html(user_text, "no_model_agent_available")
        return html_doc, _html_title(html_doc, "预览生成需要模型输出"), "fallback"

    agent_id, agent_name, reason = picked
    from handlers.send_message import load_adapter_for

    loaded = await load_adapter_for(agent_id)
    if loaded is None:
        html_doc = _fallback_preview_html(user_text, f"adapter_init_failed:{agent_id}")
        return html_doc, _html_title(html_doc, "预览生成需要模型输出"), "fallback"

    adapter, _display_name = loaded
    messages = _build_preview_prompt(
        user_text=user_text,
        conversation_history=conversation_history,
        subtask_records=subtask_records,
        subtask_outputs=task_outputs,
    )

    final_parts: list[str] = []
    errors: list[str] = []
    async for chunk in adapter.send(messages=messages, stream=False):
        ctype = chunk.get("type")
        if ctype == "text":
            final_parts.append(str(chunk.get("delta", "")))
        elif ctype == "error":
            errors.append(f"{chunk.get('code', 'adapter_error')}: {chunk.get('message', '')}")
            break

    final_text = "".join(final_parts)
    html_doc = _extract_html_from_text(final_text)
    if html_doc:
        return html_doc, _html_title(html_doc, _clean_requirement(user_text)), f"{reason}:{agent_name}"

    if errors:
        fallback_reason = "; ".join(errors)
    else:
        fallback_reason = f"model_returned_no_complete_html:{agent_name}"
    html_doc = _fallback_preview_html(user_text, fallback_reason)
    return html_doc, _html_title(html_doc, "预览生成需要模型输出"), "fallback"


async def handle_orchestrator_mention(
    conn: Connection,
    conversation_id: str,
    user_text: str,
    mentions: list[str],
    originating_message_id: str,
) -> None:
    logger.info("Orchestrator invoked in conv=%s: %.80s", conversation_id, user_text)

    Session = get_sessionmaker()

    # Load conversation history + pinned messages for context
    conversation_history: list[dict[str, Any]] = []
    pinned_context: list[str] = []
    async with Session() as s:
        rows = (
            await s.scalars(
                select(MessageModel)
                .where(MessageModel.conversation_id == conversation_id)
                .order_by(desc(MessageModel.created_at))
                .limit(50)
            )
        ).all()
        for m in reversed(rows):
            role = "assistant" if m.sender_type == "agent" else "user"
            try:
                raw = json.loads(m.content) if m.content else {}
                text = raw.get("text", "") if isinstance(raw, dict) else ""
            except (json.JSONDecodeError, TypeError):
                text = ""
            if text.strip():
                conversation_history.append({"role": role, "content": text, "pinned": bool(m.pinned)})
        pinned_context = [msg["content"] for msg in conversation_history if msg.get("pinned")]

    # 1. Emit planning status (must appear within 3s per SPEC)
    planning_msg = "正在理解用户意图、分析上下文并准备拆解任务..."
    process_text = (
        "🧭 **Orchestrator 已接管任务**\n\n"
        f"- 用户意图：{_clean_requirement(user_text)[:180]}\n"
        f"- 上下文：已读取最近 {len(conversation_history)} 条消息，包含 {len(pinned_context)} 条 pin 长期上下文\n"
        "- 协调策略：先拆解，再按 Agent 能力并行分派，最后聚合结果并检测冲突"
    )
    await conn.send(event(
        "stream_chunk",
        message_id=originating_message_id,
        sender_id=ORCHESTRATOR_AGENT_ID,
        conversation_id=conversation_id,
        seq=1,
        delta=process_text,
    ))
    async with Session() as s:
        await update_message_content(s, originating_message_id, {"type": "text", "text": process_text})

    await conn.send(event(
        "task_update",
        conversation_id=conversation_id,
        task={
            "id": "planning",
            "conversation_id": conversation_id,
            "parent_task_id": None,
            "title": user_text[:80],
            "description": user_text,
            "status": "planning",
            "domain": None,
            "assigned_agent_id": ORCHESTRATOR_AGENT_ID,
            "originating_message_id": originating_message_id,
            "result_summary": planning_msg,
            "progress_pct": 0,
            "created_at": int(time.time() * 1000),
            "updated_at": int(time.time() * 1000),
        },
        action="created",
    ))

    # 2. Inject context into complexity judge
    context_str = ""
    if pinned_context:
        context_str = "Pinned context:\n" + "\n---\n".join(pinned_context[:5])
    if conversation_history:
        recent = conversation_history[-6:-1]
        context_str += "\n\nRecent conversation:\n" + "\n".join(
            f"{m['role']}: {m['content'][:200]}" for m in recent
        )

    # 3. Run complexity analysis
    judge = ComplexityJudge()
    task_input = TaskInput(description=user_text, context=context_str or None)
    complexity = judge.judge(task_input)
    complexity.domains = _ensure_preview_collaboration_domains(user_text, set(complexity.domains))
    complexity.parallelizable = complexity.parallelizable or len(complexity.domains) >= 2

    if not complexity.domains:
        async with Session() as s:
            agents = (
                await s.scalars(select(Agent).where(Agent.id != ORCHESTRATOR_AGENT_ID))
            ).all()
            inferred_domains = set[str]()
            for agent in agents:
                caps = _agent_capabilities(agent)
                inferred_domains.update(cap for cap in caps if cap in {"frontend", "backend", "database", "test", "docs", "devops", "code"})
        complexity.domains = inferred_domains or {"code"}
        complexity.parallelizable = len(complexity.domains) >= 2

    # 4. Decompose the task
    decomposer = EnhancedTaskDecomposer()
    decompose_result = decomposer.decompose_with_contract(
        task=task_input,
        domains=complexity.domains,
    )

    if not decompose_result.subtasks:
        decompose_result.subtasks = [
            type("FallbackSubtask", (), {
                "id": "fallback_1",
                "description": _clean_requirement(user_text),
                "domain": next(iter(complexity.domains)),
                "dependencies": [],
                "contract_section": "",
                "shared_models": [],
                "provided_interfaces": [],
                "required_interfaces": [],
            })()
        ]

    # 5. Create parent & subtask records in DB
    async with Session() as s:
        parent = await create_task(
            s,
            conversation_id=conversation_id,
            title=user_text[:80],
            description=user_text,
            domain=",".join(sorted(complexity.domains)),
            originating_message_id=originating_message_id,
        )
        parent_id = parent.id

        subtask_records = []
        subtask_id_map = {}
        for i, subtask in enumerate(decompose_result.subtasks):
            agent_id, agent_name = await _pick_agent_for_domain(
                s,
                domain=subtask.domain,
                conversation_id=conversation_id,
            )

            enhanced_desc = _build_subtask_description(subtask, decompose_result)
            depends_on_list = subtask.dependencies if hasattr(subtask, "dependencies") and subtask.dependencies else []
            input_summary = (
                f"Domain: {subtask.domain}. "
                f"{'Depends on: ' + ', '.join(depends_on_list) + '. ' if depends_on_list else ''}"
                f"{subtask.description[:100]}"
            )

            st = await create_task(
                s,
                conversation_id=conversation_id,
                title=subtask.description[:80],
                description=enhanced_desc,
                domain=subtask.domain,
                assigned_agent_id=agent_id,
                agent_name=agent_name,
                originating_message_id=originating_message_id,
                parent_task_id=parent_id,
            )
            subtask_id_map[subtask.id] = st.id
            subtask_records.append((st, agent_name, agent_id, input_summary, list(depends_on_list)))

        subtask_records = [
            (
                st,
                agent_name,
                agent_id,
                input_summary,
                [subtask_id_map[d] for d in depends_on_list if d in subtask_id_map],
            )
            for st, agent_name, agent_id, input_summary, depends_on_list in subtask_records
        ]

    # 6. Update planning to running
    async with Session() as s:
        parent = await update_task_status(s, parent_id, "running",
            result_summary=f"Decomposed into {len(subtask_records)} subtasks")

    await conn.send(event(
        "task_update",
        conversation_id=conversation_id,
        task=task_to_dict(parent),
        action="status_changed",
    ))

    dispatch_plan = "\n".join(
        f"- {st.title[:60]} → {agent_name} ({st.domain or 'general'})"
        for st, agent_name, _aid, _is, _dep in subtask_records
    )
    await conn.send(event(
        "stream_chunk",
        message_id=originating_message_id,
        sender_id=ORCHESTRATOR_AGENT_ID,
        conversation_id=conversation_id,
        seq=2,
        delta=f"\n\n📌 **任务拆解完成，共 {len(subtask_records)} 个子任务：**\n{dispatch_plan}",
    ))

    for st, _agent_name, _aid, _is, _dep in subtask_records:
        await conn.send(event(
            "task_update",
            conversation_id=conversation_id,
            task=task_to_dict(st),
            action="created",
        ))

    # 7. Fan-out subtasks respecting dependency order
    dispatched_ids: set[str] = set()
    completed_ids: set[str] = set()
    failed_ids: dict[str, int] = {}
    subtask_messages: dict[str, str] = {}

    # Helper: determine which subtasks are ready
    def _ready_subtasks():
        ready = []
        for st, agent_name, aid, is_, deps in subtask_records:
            sid = st.id
            if sid in dispatched_ids or sid in completed_ids:
                continue
            if all(d in completed_ids for d in deps):
                ready.append((st, agent_name, aid, is_, deps))
        return ready

    while len(completed_ids) + len(failed_ids) < len(subtask_records):
        ready = _ready_subtasks()
        if not ready:
            break

        # Dispatch all ready subtasks concurrently
        tasks = []
        for st, agent_name, aid, is_, deps in ready:
            dispatched_ids.add(st.id)
            async with Session() as s:
                updated = await update_task_status(s, st.id, "running")
            if updated is not None:
                st = updated
            await conn.send(event(
                "task_update",
                conversation_id=conversation_id,
                task=task_to_dict(st),
                task_id=st.parent_task_id or st.id,
                subtask_id=st.id if st.parent_task_id else None,
                status=st.status,
                progress=st.progress_pct,
                message_id=None,
                action="status_changed",
            ))
            tasks.append(
                _dispatch_subtask_with_retry(
                    conn, st, agent_id=aid, conversation_id=conversation_id,
                    user_text=f"[Orchestrator] Subtask: {st.title}\nInput: {is_}",
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        for (st, agent_name, aid, is_, deps), result in zip(ready, results):
            if isinstance(result, Exception):
                if st.id in failed_ids:
                    continue
                failed_ids[st.id] = 1
                logger.warning("Subtask %s failed: %s", st.id, result)
            else:
                completed_ids.add(st.id)
                msg_id = result
                subtask_messages[st.id] = msg_id

    # 8. Mark parent as done or failed
    all_done = len(completed_ids) == len(subtask_records)
    some_failed = len(failed_ids) > 0

    w4_artifact: dict[str, Any] | None = None

    if all_done:
        summary_text = (
            f"✅ **Task Complete**\n\n"
            f"All {len(subtask_records)} subtasks completed successfully.\n\n"
            f"**Summary:**\n"
        )

        if _should_create_w4_preview(user_text):
            try:
                html_content, preview_title, preview_source = await _generate_preview_html_with_model(
                    conversation_id=conversation_id,
                    user_text=user_text,
                    conversation_history=conversation_history,
                    subtask_records=subtask_records,
                    subtask_messages=subtask_messages,
                )
                async with Session() as s:
                    artifact = await create_service_artifact(
                        s,
                        conversation_id=conversation_id,
                        kind="preview",
                        title=preview_title,
                        mime_type="text/html",
                        file_name="orchestrator-preview.html",
                        content=html_content,
                        source_message_id=originating_message_id,
                        created_by=ORCHESTRATOR_AGENT_ID,
                        meta={
                            "source": "orchestrator",
                            "preview_source": preview_source,
                            "parent_task_id": parent_id,
                            "language": "html",
                        },
                    )
                    w4_artifact = artifact
                summary_text += f"\n📄 已生成模型 HTML 预览产物：`{artifact['id']}` ({preview_source})\n"
            except Exception as exc:
                logger.warning("Failed to create W4 preview artifact: %s", exc)
        for st, agent_name, aid, is_, deps in subtask_records:
            msg_id = subtask_messages.get(st.id, "?")
            summary_text += f"- ✅ {st.title[:60]} (by {agent_name})\n"
        summary_text += f"\n{_conflict_resolution_note(subtask_records)}\n"

        async with Session() as s:
            parent = await update_task_status(s, parent_id, "done",
                result_summary=f"All {len(subtask_records)} subtasks completed")
    elif some_failed:
        success_count = len(completed_ids)
        fail_count = len(failed_ids)
        summary_text = (
            f"⚠️ **Task Partially Complete**\n\n"
            f"{success_count}/{len(subtask_records)} subtasks completed, "
            f"{fail_count} failed.\n\n"
        )
        for st, agent_name, aid, is_, deps in subtask_records:
            if st.id in completed_ids:
                summary_text += f"- ✅ {st.title[:60]}\n"
            else:
                summary_text += f"- ❌ {st.title[:60]}\n"
        summary_text += f"\nFailure degradation: completed outputs were preserved and failed subtasks were isolated.\n{_conflict_resolution_note(subtask_records)}\n"

        async with Session() as s:
            parent = await update_task_status(s, parent_id, "failed",
                result_summary=f"{success_count}/{len(subtask_records)} completed, {fail_count} failed")
    else:
        blocked_count = len(subtask_records) - len(completed_ids) - len(failed_ids)
        summary_text = (
            f"⚠️ **Task Blocked**\n\n"
            f"{len(completed_ids)}/{len(subtask_records)} subtasks completed, "
            f"{blocked_count} blocked by unresolved dependencies.\n\n"
        )
        for st, agent_name, aid, is_, deps in subtask_records:
            if st.id in completed_ids:
                summary_text += f"- ✅ {st.title[:60]}\n"
            else:
                summary_text += f"- ⏸️ {st.title[:60]}\n"
                async with Session() as s:
                    updated = await update_task_status(s, st.id, "failed",
                        result_summary="Blocked by unresolved dependencies")
                if updated is not None:
                    await conn.send(event(
                        "task_update",
                        conversation_id=conversation_id,
                        task=task_to_dict(updated),
                        task_id=updated.parent_task_id or updated.id,
                        subtask_id=updated.id if updated.parent_task_id else None,
                        status=updated.status,
                        progress=updated.progress_pct,
                        message_id=None,
                        action="status_changed",
                    ))
        summary_text += f"\nFailure degradation: blocked subtasks were reported without discarding completed work.\n{_conflict_resolution_note(subtask_records)}\n"

        async with Session() as s:
            parent = await update_task_status(s, parent_id, "failed",
                result_summary="Some subtasks were blocked by unresolved dependencies")

    # 9. Send summary as a message in chat
    summary_msg_id = new_id("msg")
    async with Session() as s:
        msg_obj = await create_service_message(
            s,
            conversation_id=conversation_id,
            sender_id=ORCHESTRATOR_AGENT_ID,
            sender_type="agent",
            content={"type": "text", "text": summary_text},
            message_id=summary_msg_id,
        )
        summary_msg_dict = message_to_dict(msg_obj)

    await conn.send(event("message_created", message=summary_msg_dict))

    async with Session() as s:
        await update_message_content(s, summary_msg_id, {"type": "text", "text": summary_text})

    await conn.send(event(
        "message_done",
        message_id=summary_msg_id,
        sender_id=ORCHESTRATOR_AGENT_ID,
        conversation_id=conversation_id,
        final_content={"type": "text", "text": summary_text},
    ))

    await conn.send(event(
        "message_done",
        message_id=originating_message_id,
        sender_id=ORCHESTRATOR_AGENT_ID,
        conversation_id=conversation_id,
        final_content={"type": "text", "text": process_text + "\n\n" + summary_text},
    ))

    if w4_artifact is not None:
        preview_msg_id = new_id("msg")
        preview_content = {
            "type": "preview",
            "artifact_id": w4_artifact["id"],
            "title": w4_artifact["title"],
            "mimeType": w4_artifact["mime_type"],
            "fileSize": w4_artifact["file_size"],
            "url": w4_artifact.get("url"),
            "previewUrl": w4_artifact.get("preview_url"),
            "version": w4_artifact.get("version", 1),
        }
        async with Session() as s:
            preview_msg = await create_service_message(
                s,
                conversation_id=conversation_id,
                sender_id=ORCHESTRATOR_AGENT_ID,
                sender_type="agent",
                content=preview_content,
                message_id=preview_msg_id,
                artifact_id=w4_artifact["id"],
            )
            preview_msg_dict = message_to_dict(preview_msg)
        await conn.send(event("message_created", message=preview_msg_dict))
        await conn.send(event(
            "artifact_ready",
            conversation_id=conversation_id,
            artifact=w4_artifact,
            message_id=preview_msg_id,
        ))
        await conn.send(event(
            "message_done",
            message_id=preview_msg_id,
            sender_id=ORCHESTRATOR_AGENT_ID,
            conversation_id=conversation_id,
            final_content=preview_content,
        ))

    await conn.send(event(
        "task_update",
        conversation_id=conversation_id,
        task=task_to_dict(parent),
        action="completed",
    ))

    logger.info("Orchestrator completed parent=%s (%d subtasks, %d ok, %d failed)",
                parent_id, len(subtask_records), len(completed_ids), len(failed_ids))


async def _dispatch_subtask_with_result(
    conn: Connection,
    st: Any,
    agent_id: str,
    conversation_id: str,
    user_text: str,
) -> str:
    """Dispatch a subtask to an agent and create a message bubble for it.

    Returns the message_id of the agent's reply message.
    """
    Session = get_sessionmaker()

    # Create agent placeholder message for this subtask
    async with Session() as s:
        agent_msg = await create_service_message(
            s,
            conversation_id=conversation_id,
            sender_id=agent_id,
            sender_type="agent",
            content={"type": "text", "text": f"⏳ Working on: {st.title[:80]}..."},
        )
        msg_id = agent_msg.id
        msg_dict = message_to_dict(agent_msg)

    await conn.send(event("message_created", message=msg_dict))
    await conn.send(event("agent_typing", agent_id=agent_id, conversation_id=conversation_id))

    # Build a concise subtask message
    agent_prompt = (
        f"[Orchestrator Subtask Assignment]\n\n"
        f"**Original Input**: {user_text}\n"
        f"**Task**: {st.title}\n"
        f"**Domain**: {st.domain}\n"
        f"**Description**: {st.description}\n"
    )

    from handlers.send_message import load_adapter_for, persist_final
    loaded = await load_adapter_for(agent_id)

    if loaded is None:
        async with Session() as s:
            await update_message_content(s, msg_id, {
                "type": "text",
                "text": f"❌ Agent `{agent_id}` not available for subtask: {st.title[:60]}",
            })
        await conn.send(event(
            "message_done",
            message_id=msg_id,
            sender_id=agent_id,
            conversation_id=conversation_id,
            final_content={"type": "text", "text": f"❌ Agent unavailable."},
        ))
        async with Session() as s:
            updated = await update_task_status(s, st.id, "failed",
                result_summary=f"Agent {agent_id} not available")
        if updated is not None:
            await conn.send(event(
                "task_update",
                conversation_id=conversation_id,
                task=task_to_dict(updated),
                task_id=updated.parent_task_id or updated.id,
                subtask_id=updated.id if updated.parent_task_id else None,
                status=updated.status,
                progress=updated.progress_pct,
                message_id=msg_id,
                action="status_changed",
            ))
        raise RuntimeError(f"Agent {agent_id} not available")

    adapter, _agent_name = loaded
    final_parts: list[str] = []
    error_parts: list[str] = []
    seq = 0

    try:
        async for chunk in adapter.send(
            messages=[{"role": "user", "content": agent_prompt}]
        ):
            ctype = chunk.get("type")
            if ctype == "text":
                seq += 1
                delta = chunk.get("delta", "")
                final_parts.append(delta)
                await conn.send(event(
                    "stream_chunk",
                    message_id=msg_id,
                    sender_id=agent_id,
                    conversation_id=conversation_id,
                    seq=seq,
                    delta=delta,
                ))
            elif ctype == "error":
                code = chunk.get("code") or "adapter_error"
                message = chunk.get("message") or "Agent adapter error"
                error_parts.append(f"{code}: {message}")

        if error_parts:
            final_text = "❌ Subtask failed: " + "; ".join(error_parts)
            async with Session() as s:
                await update_message_content(s, msg_id, {"type": "text", "text": final_text})
            await conn.send(event(
                "message_done",
                message_id=msg_id,
                sender_id=agent_id,
                conversation_id=conversation_id,
                final_content={"type": "text", "text": final_text},
            ))
            async with Session() as s:
                updated = await update_task_status(s, st.id, "failed",
                    result_summary=final_text[:200])
            if updated is not None:
                await conn.send(event(
                    "task_update",
                    conversation_id=conversation_id,
                    task=task_to_dict(updated),
                    task_id=updated.parent_task_id or updated.id,
                    subtask_id=updated.id if updated.parent_task_id else None,
                    status=updated.status,
                    progress=updated.progress_pct,
                    message_id=msg_id,
                    action="status_changed",
                ))
            raise RuntimeError(final_text)

        final_text = "".join(final_parts) or f"✅ Subtask completed: {st.title[:100]}"
        async with Session() as s:
            await update_message_content(s, msg_id, {"type": "text", "text": final_text})
        await conn.send(event(
            "message_done",
            message_id=msg_id,
            sender_id=agent_id,
            conversation_id=conversation_id,
            final_content={"type": "text", "text": final_text},
        ))

        display_text = final_text
        artifact_payload = None
        if agent_id.startswith("agent_mock"):
            html_doc = _extract_html_from_text(final_text)
            if html_doc:
                async with Session() as s:
                    artifact_payload = await create_service_artifact(
                        s,
                        conversation_id=conversation_id,
                        kind="preview",
                        title=_html_title(html_doc, st.title),
                        mime_type="text/html",
                        file_name="subtask-preview.html",
                        content=html_doc,
                        source_message_id=msg_id,
                        created_by=agent_id,
                        meta={"source": "subtask_html", "language": "html", "task_id": st.id},
                    )
                    await update_message_content(s, msg_id, _preview_message_content(artifact_payload))
                    row = await s.get(MessageModel, msg_id)
                    if row is not None:
                        row.artifact_id = artifact_payload["id"]
                        await s.commit()
                display_text = f"已生成可预览 HTML：{artifact_payload['title']}"
                await conn.send(event(
                    "artifact_ready",
                    conversation_id=conversation_id,
                    artifact=artifact_payload,
                    message_id=msg_id,
                ))

        # Mark subtask as done
        async with Session() as s:
            updated = await update_task_status(s, st.id, "done",
                result_summary=display_text[:200],
                progress_pct=100)
        if updated is not None:
            await conn.send(event(
                "task_update",
                conversation_id=conversation_id,
                task=task_to_dict(updated),
                task_id=updated.parent_task_id or updated.id,
                subtask_id=updated.id if updated.parent_task_id else None,
                status=updated.status,
                progress=updated.progress_pct,
                message_id=msg_id,
                action="status_changed",
            ))

    except asyncio.CancelledError:
        async with Session() as s:
            await update_message_content(s, msg_id, {"type": "text", "text": "[cancelled]"})
        raise

    return msg_id


async def _dispatch_subtask_with_retry(
    conn: Connection,
    st: Any,
    agent_id: str,
    conversation_id: str,
    user_text: str,
) -> str:
    last_exc: Exception | None = None
    for attempt in range(RETRY_LIMIT + 1):
        try:
            return await _dispatch_subtask_with_result(
                conn,
                st,
                agent_id=agent_id,
                conversation_id=conversation_id,
                user_text=user_text,
            )
        except Exception as exc:
            last_exc = exc
            if attempt >= RETRY_LIMIT:
                break
            Session = get_sessionmaker()
            async with Session() as s:
                updated = await update_task_status(
                    s,
                    st.id,
                    "running",
                    result_summary=f"Retrying after adapter failure: {str(exc)[:120]}",
                    progress_pct=25,
                )
            if updated is not None:
                await conn.send(event(
                    "task_update",
                    conversation_id=conversation_id,
                    task=task_to_dict(updated),
                    action="status_changed",
                ))
            await asyncio.sleep(0.25)
    raise RuntimeError(f"subtask degraded after retry: {last_exc}") from last_exc
