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
    Graph,
    McpTool,
    PythonCodeTool,
    Tool,
)

VALID_TOOL_PREFIXES = ("configured-tool", "python-code-tool", "mcp-tool")


class ToolNotFoundError(Exception):
    """Raised by `get_tool_usage_detail`/`get_agent_ids_for_tool` when
    `prefix:tool_id` doesn't exist or isn't visible to `org_id`."""


def get_tools_usage(org_id: int) -> list[dict]:
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
    """
    tool_ids = list(Tool.objects.values_list("id", flat=True))
    python_tool_built_in = dict(
        PythonCodeTool.objects.filter(
            Q(built_in=True) | Q(org_id=org_id)
        ).values_list("id", "built_in")
    )
    python_tool_ids = list(python_tool_built_in.keys())
    mcp_tool_ids = list(
        McpTool.objects.filter(org_id=org_id).values_list("id", flat=True)
    )

    configured_agents, python_agents, mcp_agents = _agents_by_tool_per_kind(
        org_id, tool_ids, python_tool_ids, mcp_tool_ids
    )
    all_agent_ids: set[int] = set()
    for agents_by_tool in (configured_agents, python_agents, mcp_agents):
        for agent_ids in agents_by_tool.values():
            all_agent_ids.update(agent_ids)
    agent_graphs = _agent_graph_map(org_id, all_agent_ids)

    return [
        *_build_rows(
            "configured-tool",
            tool_ids,
            configured_agents,
            agent_graphs,
            is_built_in=lambda _tool_id: True,
        ),
        *_build_rows(
            "python-code-tool",
            python_tool_ids,
            python_agents,
            agent_graphs,
            is_built_in=lambda tool_id: python_tool_built_in.get(tool_id, False),
        ),
        *_build_rows(
            "mcp-tool",
            mcp_tool_ids,
            mcp_agents,
            agent_graphs,
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
    return _agents_by_tool(
        AgentConfiguredTools.objects.filter(
            agent__org_id=org_id, toolconfig__tool_id__in=tool_ids
        ).values_list("toolconfig__tool_id", "agent_id")
    )


def _python_tool_agents_by_tool(
    org_id: int, tool_ids: list[int]
) -> dict[int, set[int]]:
    """Python-code tools merge two join paths (direct + via config)."""
    python_agents = _agents_by_tool(
        AgentPythonCodeTools.objects.filter(
            agent__org_id=org_id, pythoncodetool_id__in=tool_ids
        ).values_list("pythoncodetool_id", "agent_id")
    )
    _merge_agents_by_tool(
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
    return _agents_by_tool(
        AgentMcpTools.objects.filter(
            agent__org_id=org_id, mcptool_id__in=tool_ids
        ).values_list("mcptool_id", "agent_id")
    )


_AGENTS_BY_TOOL_FN_PER_PREFIX = {
    "configured-tool": _configured_tool_agents_by_tool,
    "python-code-tool": _python_tool_agents_by_tool,
    "mcp-tool": _mcp_tool_agents_by_tool,
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


def get_tool_usage_detail(prefix: str, tool_id: int, org_id: int) -> dict:
    """Return the "Where is this used?" detail for `prefix:tool_id`:
    `{"projects": [{"id", "name"}, ...], "staff": [{"id", "role"}, ...]}`.

    `projects` are the distinct Graphs reached from the tool's agents (same
    Crew -> CrewNode -> Graph traversal as `get_tools_usage`); `staff` are
    the Agents themselves. Raises `ToolNotFoundError` if the tool doesn't
    exist / isn't visible to `org_id`.
    """
    agent_ids = get_agent_ids_for_tool(prefix, tool_id, org_id)
    agent_graphs = _agent_graph_map(org_id, agent_ids)

    graph_ids: set[int] = set()
    for graphs in agent_graphs.values():
        graph_ids.update(graphs)

    staff = list(Agent.objects.filter(id__in=agent_ids).values("id", "role"))
    projects = list(Graph.objects.filter(id__in=graph_ids).values("id", "name"))
    return {"projects": projects, "staff": staff}


def _agents_by_tool(pairs) -> dict[int, set[int]]:
    agents_by_tool: dict[int, set[int]] = defaultdict(set)
    for tool_id, agent_id in pairs:
        agents_by_tool[tool_id].add(agent_id)
    return agents_by_tool


def _merge_agents_by_tool(agents_by_tool: dict[int, set[int]], pairs) -> None:
    for tool_id, agent_id in pairs:
        agents_by_tool.setdefault(tool_id, set()).add(agent_id)


def _agent_graph_map(org_id: int, agent_ids: set[int]) -> dict[int, set[int]]:
    """Map each relevant agent id to the set of Graph ids it reaches via
    Crew membership -> CrewNode -> Graph (all scoped to `org_id`)."""
    if not agent_ids:
        return {}

    # Agent -> Crew is the reverse of Crew.agents (no related_name -> "crew").
    # Crew -> CrewNode is the reverse of CrewNode.crew (no related_name ->
    # "crewnode"); CrewNode.graph is the one with related_name="crew_node_list".
    pairs = Agent.objects.filter(
        id__in=agent_ids,
        org_id=org_id,
        crew__org_id=org_id,
        crew__crewnode__graph__org_id=org_id,
    ).values_list("id", "crew__crewnode__graph_id")

    agent_graphs: dict[int, set[int]] = defaultdict(set)
    for agent_id, graph_id in pairs:
        agent_graphs[agent_id].add(graph_id)
    return agent_graphs


def _build_rows(
    prefix: str,
    tool_ids: list[int],
    agents_by_tool: dict[int, set[int]],
    agent_graphs: dict[int, set[int]],
    is_built_in,
) -> list[dict]:
    rows: list[dict] = []
    for tool_id in tool_ids:
        agent_ids = agents_by_tool.get(tool_id, set())
        graph_ids: set[int] = set()
        for agent_id in agent_ids:
            graph_ids.update(agent_graphs.get(agent_id, set()))
        rows.append(
            {
                "unique_name": f"{prefix}:{tool_id}",
                "projects_count": len(graph_ids),
                "staff_count": len(agent_ids),
                "is_built_in": bool(is_built_in(tool_id)),
            }
        )
    return rows
