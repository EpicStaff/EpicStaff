"""Aggregates per-tool usage counts (staff/projects) for the Tools page's
opt-in "Show usage & orphans" view (EST-3264), plus the per-tool reference
DETAIL lookup (EST-3270) for the "Where is this used?" modal.

Deliberately query-shaped as a small, fixed number of bulk queries + Python
set merging (rather than annotate()-ing multiple Count(distinct=True)
aggregates in one query, which silently multiplies rows across independent
reverse joins) and rather than a per-tool query loop.

Split per tool kind (python-code-tool / mcp-tool) rather than dispatched
through a shared `unique_name` prefix — each kind now has its own
usage/usage-detail actions on its own ViewSet (EST-3207 follow-up: Tools
Redesign), scoped to plain numeric ids instead of `<prefix>:<id>` strings.
"""

from collections import defaultdict

from django.db.models import Q

from tables.models import (
    Agent,
    AgentMcpTools,
    AgentPythonCodeTools,
    AgentPythonCodeToolConfigs,
    Crew,
    McpTool,
    PythonCodeTool,
    Task,
    TaskMcpTools,
    TaskPythonCodeTools,
    TaskPythonCodeToolConfigs,
)


class ToolNotFoundError(Exception):
    """Raised by `get_python_code_tool_usage_detail`/`get_mcp_tool_usage_detail`
    when the given tool id doesn't exist or isn't visible to `org_id`."""


def get_tools_usage(
    org_id: int, tool_class: type, ids: set[int] | None = None
) -> list[dict]:
    id_q = {"id__in": ids} if ids is not None else {}

    if tool_class is PythonCodeTool:
        return _get_python_code_tool_usage(org_id, id_q)
    elif tool_class is McpTool:
        return _get_mcp_tool_usage(org_id, id_q)
    else:
        raise ValueError(f"Unsupported tool_class: {tool_class}")


def _get_python_code_tool_usage(org_id: int, id_q: dict) -> list[dict]:
    tool_built_in = dict(
        PythonCodeTool.objects.filter(
            Q(built_in=True) | Q(org_id=org_id), **id_q
        ).values_list("id", "built_in")
    )
    return _get_tool_usage(
        org_id,
        tool_built_in=tool_built_in,
        agents_by_tool_fn=_python_tool_agents_by_tool,
        tasks_by_tool_fn=_python_tool_tasks_by_tool,
    )


def _get_mcp_tool_usage(org_id: int, id_q: dict) -> list[dict]:
    tool_built_in = dict.fromkeys(
        McpTool.objects.filter(org_id=org_id, **id_q).values_list("id", flat=True),
        False,
    )
    return _get_tool_usage(
        org_id,
        tool_built_in=tool_built_in,
        agents_by_tool_fn=_mcp_tool_agents_by_tool,
        tasks_by_tool_fn=_mcp_tool_tasks_by_tool,
    )


def _get_tool_usage(
    org_id: int,
    tool_built_in: dict[int, bool],
    agents_by_tool_fn,
    tasks_by_tool_fn,
) -> list[dict]:
    """Shared aggregation body for `_get_python_code_tool_usage`/
    `_get_mcp_tool_usage`: given the per-kind `{tool_id: is_built_in}` map
    (already scoped/filtered by the caller) and the kind's own
    agents-by-tool/tasks-by-tool join functions, builds the usage rows."""
    tool_ids = list(tool_built_in.keys())

    agents_by_tool = agents_by_tool_fn(org_id, tool_ids)
    tasks_by_tool = tasks_by_tool_fn(org_id, tool_ids)
    task_crews = _task_crew_map(org_id, _all_task_ids(tasks_by_tool))

    return _build_rows(
        tool_ids,
        agents_by_tool,
        tasks_by_tool,
        task_crews,
        is_built_in=lambda tool_id: tool_built_in.get(tool_id, False),
    )


def _python_tool_agents_by_tool(
    org_id: int, tool_ids: list[int]
) -> dict[int, set[int]]:
    """Python-code tools merge two join paths (direct + via config)."""
    python_agents = _pairs_by_tool(
        AgentPythonCodeTools.objects.filter(
            agent__org_id=org_id, pythoncodetool_id__in=tool_ids
        ).values_list("pythoncodetool_id", "agent_id")
    )
    _merge_pairs_by_tool(
        python_agents,
        AgentPythonCodeToolConfigs.objects.filter(
            agent__org_id=org_id,
            pythoncodetoolconfig__tool_id__in=tool_ids,
        ).values_list("pythoncodetoolconfig__tool_id", "agent_id"),
    )
    return python_agents


def _mcp_tool_agents_by_tool(org_id: int, tool_ids: list[int]) -> dict[int, set[int]]:
    return _pairs_by_tool(
        AgentMcpTools.objects.filter(
            agent__org_id=org_id, mcptool_id__in=tool_ids
        ).values_list("mcptool_id", "agent_id")
    )


def _python_tool_tasks_by_tool(org_id: int, tool_ids: list[int]) -> dict[int, set[int]]:
    """Python-code tools merge two join paths (direct + via config), mirroring
    `_python_tool_agents_by_tool`."""
    python_tasks = _pairs_by_tool(
        TaskPythonCodeTools.objects.filter(
            task__crew__org_id=org_id, tool_id__in=tool_ids
        ).values_list("tool_id", "task_id")
    )
    _merge_pairs_by_tool(
        python_tasks,
        TaskPythonCodeToolConfigs.objects.filter(
            task__crew__org_id=org_id,
            tool__tool_id__in=tool_ids,
        ).values_list("tool__tool_id", "task_id"),
    )
    return python_tasks


def _mcp_tool_tasks_by_tool(org_id: int, tool_ids: list[int]) -> dict[int, set[int]]:
    return _pairs_by_tool(
        TaskMcpTools.objects.filter(
            task__crew__org_id=org_id, tool_id__in=tool_ids
        ).values_list("tool_id", "task_id")
    )


def _all_task_ids(tasks_by_tool: dict[int, set[int]]) -> set[int]:
    all_task_ids: set[int] = set()
    for task_ids in tasks_by_tool.values():
        all_task_ids.update(task_ids)
    return all_task_ids


def _python_tool_exists(tool_id: int, org_id: int) -> bool:
    """Existence + org-visibility check for a single PythonCodeTool id.
    Hybrid-scoped — built-in rows are global (`org_id=None`), custom rows are
    org-scoped — matching `PythonCodeToolViewSet`'s own
    `global_visibility_q=Q(built_in=True)` rule and the same widened
    visibility `get_python_code_tool_usage` uses, so a tool visible in the
    usage list is never a 404 in the usage-detail lookup."""
    return _tool_exists(PythonCodeTool, tool_id, Q(built_in=True) | Q(org_id=org_id))


def _mcp_tool_exists(tool_id: int, org_id: int) -> bool:
    """`McpTool` is strictly scoped to `org_id` (no built-in concept)."""
    return _tool_exists(McpTool, tool_id, Q(org_id=org_id))


def _tool_exists(model: type, tool_id: int, visibility_q: Q) -> bool:
    return model.objects.filter(visibility_q, id=tool_id).exists()


def get_python_code_tool_usage_detail(tool_id: int, org_id: int) -> dict:
    """Return the "Where is this used?" detail for a single `PythonCodeTool`:
    `{"projects": [{"id", "name"}, ...], "staff": [{"id", "role"}, ...]}`.

    `staff` are the Agents referencing the tool directly (Agent-level join).
    `projects` are the distinct Crews (the FE "Project") reached from the
    tool's *Tasks* (Task-level join, via each Task's direct `crew` FK) — NOT
    derived from Agent/Crew membership, since that would make `projects`
    trivially correlated with `staff` (EST-3207 design fix; see module
    docstring). Raises `ToolNotFoundError` if the tool doesn't exist / isn't
    visible to `org_id`.
    """
    return _get_tool_usage_detail(
        tool_id,
        org_id,
        exists_fn=_python_tool_exists,
        agents_by_tool_fn=_python_tool_agents_by_tool,
        tasks_by_tool_fn=_python_tool_tasks_by_tool,
        not_found_message=f"python-code-tool:{tool_id} not found",
    )


def get_mcp_tool_usage_detail(tool_id: int, org_id: int) -> dict:
    """MCP-tool counterpart of `get_python_code_tool_usage_detail`. See its
    docstring for the `projects`/`staff` semantics (unchanged for MCP tools).
    """
    return _get_tool_usage_detail(
        tool_id,
        org_id,
        exists_fn=_mcp_tool_exists,
        agents_by_tool_fn=_mcp_tool_agents_by_tool,
        tasks_by_tool_fn=_mcp_tool_tasks_by_tool,
        not_found_message=f"mcp-tool:{tool_id} not found",
    )


def _get_tool_usage_detail(
    tool_id: int,
    org_id: int,
    exists_fn,
    agents_by_tool_fn,
    tasks_by_tool_fn,
    not_found_message: str,
) -> dict:
    """Shared body for `get_python_code_tool_usage_detail`/
    `get_mcp_tool_usage_detail`: existence check + agent/task join lookups +
    projects/staff shaping, parameterized on the kind's own exists-check and
    agents-by-tool/tasks-by-tool functions."""
    if not exists_fn(tool_id, org_id):
        raise ToolNotFoundError(not_found_message)

    agent_ids = agents_by_tool_fn(org_id, [tool_id]).get(tool_id, set())
    staff = list(Agent.objects.filter(id__in=agent_ids).values("id", "role"))

    task_ids = tasks_by_tool_fn(org_id, [tool_id]).get(tool_id, set())
    task_crews = _task_crew_map(org_id, task_ids)
    projects = list(
        Crew.objects.filter(id__in=set(task_crews.values())).values("id", "name")
    )
    return {"projects": projects, "staff": staff}


def _pairs_by_tool(pairs) -> dict[int, set[int]]:
    by_tool: dict[int, set[int]] = defaultdict(set)
    for tool_id, value_id in pairs:
        by_tool[tool_id].add(value_id)
    return by_tool


def _merge_pairs_by_tool(by_tool: dict[int, set[int]], pairs) -> None:
    for tool_id, value_id in pairs:
        by_tool.setdefault(tool_id, set()).add(value_id)


def _task_crew_map(org_id: int, task_ids: set[int]) -> dict[int, int]:
    """Map each relevant task id to its (single) Crew id, scoped to
    `org_id`. `Task.crew` is a direct, single-valued FK (unlike
    Agent<->Crew, which is many-valued), so this is a plain
    `{task_id: crew_id}` dict, not a dict of sets."""
    if not task_ids:
        return {}

    return dict(
        Task.objects.filter(id__in=task_ids, crew__org_id=org_id).values_list(
            "id", "crew_id"
        )
    )


def _build_rows(
    tool_ids: list[int],
    agents_by_tool: dict[int, set[int]],
    tasks_by_tool: dict[int, set[int]],
    task_crews: dict[int, int],
    is_built_in,
) -> list[dict]:
    rows: list[dict] = []
    for tool_id in tool_ids:
        agent_ids = agents_by_tool.get(tool_id, set())
        task_ids = tasks_by_tool.get(tool_id, set())
        crew_ids = {
            task_crews[task_id] for task_id in task_ids if task_id in task_crews
        }
        rows.append(
            {
                "id": tool_id,
                "projects_count": len(crew_ids),
                "staff_count": len(agent_ids),
                "is_built_in": bool(is_built_in(tool_id)),
            }
        )
    return rows
