from __future__ import annotations

import re


SPELLS: dict[str, str] = {
    "map-reduce": """You are executing the map-reduce orchestration spell.

Protocol:
1. Split the user task into independent shards.
2. Use list_agents to inspect available workers.
3. Use create_agent when a missing specialist is needed.
4. Use send_message to delegate each shard with precise acceptance criteria.
5. Aggregate the returned work into one concise final answer with risks and next steps.

User task:
{task}
""",
    "router-experts": """You are executing the router-experts orchestration spell.

Protocol:
1. Classify the task into expert domains such as frontend, backend, database, test, docs, or devops.
2. Use list_agents to inspect available experts.
3. Use create_agent for any expert role that is missing.
4. Use send_message to route focused work to the best expert Agent.
5. Return the routed plan and summarize expert outputs.

User task:
{task}
""",
    "tree-executor": """You are executing the tree-executor orchestration spell.

Protocol:
1. Build a task tree from the user's objective.
2. Execute leaf tasks first by delegating to child Agents with create_agent and send_message.
3. Combine child outputs bottom-up.
4. Keep the final answer structured as: tree, completed work, open risks.

User task:
{task}
""",
}

_SPELL_RE = re.compile(r"^/(?P<name>map-reduce|router-experts|tree-executor)\s*:?\s*(?P<task>[\s\S]*)$", re.I)


def expand_spell(text: str) -> str:
    match = _SPELL_RE.match(text.strip())
    if not match:
        return text
    name = match.group("name").lower()
    task = match.group("task").strip()
    template = SPELLS[name]
    return template.format(task=task or "(no task supplied)")
