"""Aggregates per-tool usage counts (staff/projects) for the Tools page's
opt-in "Show usage & orphans" view (EST-3264), plus the per-tool reference
DETAIL lookup (EST-3270) for the "Where is this used?" modal.

Deliberately query-shaped as a small, fixed number of bulk queries + Python
set merging (rather than annotate()-ing multiple Count(distinct=True)
aggregates in one query, which silently multiplies rows across independent
reverse joins) and rather than a per-tool query loop.
"""

from collections import defaultdict

from django.db.models import Q

from tables.models import (
    Agent,
    AgentConfiguredTools,
    AgentMcpTools,
    AgentPythonCodeTools,
    AgentPythonCodeToolConfigs,
    Crew,
    McpTool,
    PythonCodeTool,
    Task,
    TaskConfiguredTools,
    TaskMcpTools,
    TaskPythonCodeTools,
    TaskPythonCodeToolConfigs,
    Tool,
)

VALID_TOOL_PREFIXES = ("configured-tool", "python-code-tool", "mcp-tool")


class ToolNotFoundError(Exception):
    """Raised by `get_tool_usage_detail`/`get_agent_ids_for_tool` when
    `prefix:tool_id` doesn't exist or isn't visible to `org_id`."""


def get_tools_usage(
    org_id: int, id_filter: dict[str, set[int]] | None = None
) -> list[dict]:
    """Return one usage row per tool (registered/python-code/mcp) visible to
    `org_id`: `{"unique_name": str, "projects_count": int, "staff_count": int,
    "is_built_in": bool}`.

    Registered `Tool` rows are global (no org column) and are always
    included, and are always `is_built_in=True` (EST-3277: the registered
    tool kind has no non-built-in variant). `McpTool` is strictly scoped to
    `org_id` (no built-in concept, always `is_built_in=False`).
    `PythonCodeTool` is hybrid-visible — built-in rows (`org_id=None`) plus
    this org's own custom rows — matching the visibility rule already used by
    `PythonCodeToolViewSet` (`OrgScopedHybridViewSetMixin`); `built_in` is
    surfaced as-is per row. This lets the FE additionally gate
    orphan-highlighting on `!is_built_in` without excluding built-ins from
    the endpoint itself.

    `id_filter` (EST-3207 `ids` query-param support), when given, is a
    `{prefix: {tool_id, ...}}` map (prefix one of `VALID_TOOL_PREFIXES`)
    scoping which tools are computed/returned — pushed down into the initial
    per-kind id queries (rather than computed in full then filtered in
    Python) so a caller asking for a handful of ids doesn't pay for the full
    per-org aggregation. Ids absent from the org's visible set (wrong org,
    wrong kind, or nonexistent) are silently omitted from the result, same
    as any other tool the caller can't see — this endpoint has never errored
    per-row, unlike the single-tool usage-detail lookup.
    """
    tool_id_q = {}
    python_tool_id_q = {}
    mcp_tool_id_q = {}
    if id_filter is not None:
        tool_id_q = {"id__in": id_filter.get("configured-tool", set())}
        python_tool_id_q = {"id__in": id_filter.get("python-code-tool", set())}
        mcp_tool_id_q = {"id__in": id_filter.get("mcp-tool", set())}

    tool_ids = list(
        Tool.objects.filter(**tool_id_q).values_list("id", flat=True)
    )
    python_tool_built_in = dict(
        PythonCodeTool.objects.filter(
            Q(built_in=True) | Q(org_id=org_id), **python_tool_id_q
        ).values_list("id", "built_in")
    )
    python_tool_ids = list(python_tool_built_in.keys())
    mcp_tool_ids = list(
        McpTool.objects.filter(org_id=org_id, **mcp_tool_id_q).values_list(
            "id", flat=True
        )
    )

    configured_agents, python_agents, mcp_agents = _agents_by_tool_per_kind(
        org_id, tool_ids, python_tool_ids, mcp_tool_ids
    )

    configured_tasks, python_tasks, mcp_tasks = _tasks_by_tool_per_kind(
        org_id, tool_ids, python_tool_ids, mcp_tool_ids
    )
    all_task_ids: set[int] = set()
    for tasks_by_tool in (configured_tasks, python_tasks, mcp_tasks):
        for task_ids in tasks_by_tool.values():
            all_task_ids.update(task_ids)
    task_crews = _task_crew_map(org_id, all_task_ids)

    return [
        *_build_rows(
            "configured-tool",
            tool_ids,
            configured_agents,
            configured_tasks,
            task_crews,
            is_built_in=lambda _tool_id: True,
        ),
        *_build_rows(
            "python-code-tool",
            python_tool_ids,
            python_agents,
            python_tasks,
            task_crews,
            is_built_in=lambda tool_id: python_tool_built_in.get(tool_id, False),
        ),
        *_build_rows(
            "mcp-tool",
            mcp_tool_ids,
            mcp_agents,
            mcp_tasks,
            task_crews,
            is_built_in=lambda _tool_id: False,
        ),
    ]


def _agents_by_tool_per_kind(
    org_id: int,
    tool_ids: list[int],
    python_tool_ids: list[int],
    mcp_tool_ids: list[int],
) -> tuple[dict[int, set[int]], dict[int, set[int]], dict[int, set[int]]]:
    """Build the `tool_id -> {agent_id, ...}` map for each of the 3 tool
    kinds, via the shared per-kind helpers (also used by the single-tool
    detail lookup below)."""
    return (
        _configured_tool_agents_by_tool(org_id, tool_ids),
        _python_tool_agents_by_tool(org_id, python_tool_ids),
        _mcp_tool_agents_by_tool(org_id, mcp_tool_ids),
    )


def _configured_tool_agents_by_tool(
    org_id: int, tool_ids: list[int]
) -> dict[int, set[int]]:
    return _pairs_by_tool(
        AgentConfiguredTools.objects.filter(
            agent__org_id=org_id, toolconfig__tool_id__in=tool_ids
        ).values_list("toolconfig__tool_id", "agent_id")
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


def _mcp_tool_agents_by_tool(
    org_id: int, tool_ids: list[int]
) -> dict[int, set[int]]:
    return _pairs_by_tool(
        AgentMcpTools.objects.filter(
            agent__org_id=org_id, mcptool_id__in=tool_ids
        ).values_list("mcptool_id", "agent_id")
    )


_AGENTS_BY_TOOL_FN_PER_PREFIX = {
    "configured-tool": _configured_tool_agents_by_tool,
    "python-code-tool": _python_tool_agents_by_tool,
    "mcp-tool": _mcp_tool_agents_by_tool,
}


def _tasks_by_tool_per_kind(
    org_id: int,
    tool_ids: list[int],
    python_tool_ids: list[int],
    mcp_tool_ids: list[int],
) -> tuple[dict[int, set[int]], dict[int, set[int]], dict[int, set[int]]]:
    """Task-side counterpart of `_agents_by_tool_per_kind`: builds the
    `tool_id -> {task_id, ...}` map for each of the 3 tool kinds. Project
    (Crew) usage is derived from Task-level tool usage, not Agent-level — see
    module docstring / EST-3207 design fix."""
    return (
        _configured_tool_tasks_by_tool(org_id, tool_ids),
        _python_tool_tasks_by_tool(org_id, python_tool_ids),
        _mcp_tool_tasks_by_tool(org_id, mcp_tool_ids),
    )


def _configured_tool_tasks_by_tool(
    org_id: int, tool_ids: list[int]
) -> dict[int, set[int]]:
    return _pairs_by_tool(
        TaskConfiguredTools.objects.filter(
            task__crew__org_id=org_id, tool__tool_id__in=tool_ids
        ).values_list("tool__tool_id", "task_id")
    )


def _python_tool_tasks_by_tool(
    org_id: int, tool_ids: list[int]
) -> dict[int, set[int]]:
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


def _mcp_tool_tasks_by_tool(
    org_id: int, tool_ids: list[int]
) -> dict[int, set[int]]:
    return _pairs_by_tool(
        TaskMcpTools.objects.filter(
            task__crew__org_id=org_id, tool_id__in=tool_ids
        ).values_list("tool_id", "task_id")
    )


_TASKS_BY_TOOL_FN_PER_PREFIX = {
    "configured-tool": _configured_tool_tasks_by_tool,
    "python-code-tool": _python_tool_tasks_by_tool,
    "mcp-tool": _mcp_tool_tasks_by_tool,
}


def _tool_exists(prefix: str, tool_id: int, org_id: int) -> bool:
    """Existence + org-visibility check for a single `prefix:tool_id`.
    Registered `Tool` rows are global (no org column); `McpTool` is strictly
    scoped to `org_id` (no built-in concept). `PythonCodeTool` is
    hybrid-scoped — built-in rows are global (`org_id=None`), custom rows are
    org-scoped — matching `PythonCodeToolViewSet`'s own
    `global_visibility_q=Q(built_in=True)` rule and the same widened
    visibility `get_tools_usage` uses, so a tool visible in the usage list is
    never a 404 in the usage-detail lookup."""
    if prefix == "configured-tool":
        return Tool.objects.filter(id=tool_id).exists()
    if prefix == "python-code-tool":
        return PythonCodeTool.objects.filter(
            Q(built_in=True) | Q(org_id=org_id), id=tool_id
        ).exists()
    if prefix == "mcp-tool":
        return McpTool.objects.filter(id=tool_id, org_id=org_id).exists()
    raise ValueError(f"Unknown tool prefix: {prefix}")


def get_agent_ids_for_tool(prefix: str, tool_id: int, org_id: int) -> set[int]:
    """Validate that `prefix:tool_id` exists and is visible to `org_id`, then
    return the set of Agent ids referencing it — the same per-kind join
    logic `get_tools_usage` uses, reused via the shared per-kind helpers.

    Raises `ToolNotFoundError` if the tool doesn't exist / isn't visible to
    `org_id`. Assumes `prefix` has already been validated against
    `VALID_TOOL_PREFIXES` by the caller.
    """
    if not _tool_exists(prefix, tool_id, org_id):
        raise ToolNotFoundError(f"{prefix}:{tool_id} not found")

    agents_by_tool_fn = _AGENTS_BY_TOOL_FN_PER_PREFIX[prefix]
    agents_by_tool = agents_by_tool_fn(org_id, [tool_id])
    return agents_by_tool.get(tool_id, set())


def get_task_ids_for_tool(prefix: str, tool_id: int, org_id: int) -> set[int]:
    """Task-side counterpart of `get_agent_ids_for_tool`: validate that
    `prefix:tool_id` exists and is visible to `org_id`, then return the set
    of Task ids referencing it — used to derive `projects` (Crew usage) from
    Task-level tool usage rather than Agent-level (EST-3207 design fix).

    Raises `ToolNotFoundError` if the tool doesn't exist / isn't visible to
    `org_id`. Assumes `prefix` has already been validated against
    `VALID_TOOL_PREFIXES` by the caller.
    """
    if not _tool_exists(prefix, tool_id, org_id):
        raise ToolNotFoundError(f"{prefix}:{tool_id} not found")

    tasks_by_tool_fn = _TASKS_BY_TOOL_FN_PER_PREFIX[prefix]
    tasks_by_tool = tasks_by_tool_fn(org_id, [tool_id])
    return tasks_by_tool.get(tool_id, set())


def get_tool_usage_detail(prefix: str, tool_id: int, org_id: int) -> dict:
    """Return the "Where is this used?" detail for `prefix:tool_id`:
    `{"projects": [{"id", "name"}, ...], "staff": [{"id", "role"}, ...]}`.

    `staff` are the Agents referencing the tool directly (Agent-level join).
    `projects` are the distinct Crews (the FE "Project") reached from the
    tool's *Tasks* (Task-level join, via each Task's direct `crew` FK) — NOT
    derived from Agent/Crew membership, since that would make `projects`
    trivially correlated with `staff` (EST-3207 design fix; see module
    docstring). Raises `ToolNotFoundError` if the tool doesn't exist / isn't
    visible to `org_id`.
    """
    agent_ids = get_agent_ids_for_tool(prefix, tool_id, org_id)
    staff = list(Agent.objects.filter(id__in=agent_ids).values("id", "role"))

    task_ids = get_task_ids_for_tool(prefix, tool_id, org_id)
    task_crews = _task_crew_map(org_id, task_ids)
    crew_ids: set[int] = set(task_crews.values())

    projects = list(Crew.objects.filter(id__in=crew_ids).values("id", "name"))
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
        Task.objects.filter(
            id__in=task_ids, crew__org_id=org_id
        ).values_list("id", "crew_id")
    )


def _build_rows(
    prefix: str,
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
            task_crews[task_id]
            for task_id in task_ids
            if task_id in task_crews
        }
        rows.append(
            {
                "unique_name": f"{prefix}:{tool_id}",
                "projects_count": len(crew_ids),
                "staff_count": len(agent_ids),
                "is_built_in": bool(is_built_in(tool_id)),
            }
        )
    return rows
