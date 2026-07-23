"""Aggregates per-tool usage counts (staff/projects) for the Tools page's
opt-in "Show usage & orphans" view (EST-3264).

Deliberately query-shaped as a small, fixed number of bulk queries + Python
set merging (rather than annotate()-ing multiple Count(distinct=True)
aggregates in one query, which silently multiplies rows across independent
reverse joins) and rather than a per-tool query loop.
"""

from collections import defaultdict

from tables.models import (
    Agent,
    AgentConfiguredTools,
    AgentMcpTools,
    AgentPythonCodeTools,
    AgentPythonCodeToolConfigs,
    McpTool,
    PythonCodeTool,
    Tool,
)


def get_tools_usage(org_id: int) -> list[dict]:
    """Return one usage row per tool (registered/python-code/mcp) visible to
    `org_id`: `{"unique_name": str, "projects_count": int, "staff_count": int}`.

    Registered `Tool` rows are global (no org column) and are always
    included; `PythonCodeTool`/`McpTool` are scoped to `org_id`.
    """
    tool_ids = list(Tool.objects.values_list("id", flat=True))
    python_tool_ids = list(
        PythonCodeTool.objects.filter(org_id=org_id).values_list("id", flat=True)
    )
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
        *_build_rows("configured-tool", tool_ids, configured_agents, agent_graphs),
        *_build_rows(
            "python-code-tool", python_tool_ids, python_agents, agent_graphs
        ),
        *_build_rows("mcp-tool", mcp_tool_ids, mcp_agents, agent_graphs),
    ]


def _agents_by_tool_per_kind(
    org_id: int,
    tool_ids: list[int],
    python_tool_ids: list[int],
    mcp_tool_ids: list[int],
) -> tuple[dict[int, set[int]], dict[int, set[int]], dict[int, set[int]]]:
    """Build the `tool_id -> {agent_id, ...}` map for each of the 3 tool
    kinds. Python-code tools merge two join paths (direct + via config)."""
    configured_agents = _agents_by_tool(
        AgentConfiguredTools.objects.filter(
            agent__org_id=org_id, toolconfig__tool_id__in=tool_ids
        ).values_list("toolconfig__tool_id", "agent_id")
    )
    python_agents = _agents_by_tool(
        AgentPythonCodeTools.objects.filter(
            agent__org_id=org_id, pythoncodetool_id__in=python_tool_ids
        ).values_list("pythoncodetool_id", "agent_id")
    )
    _merge_agents_by_tool(
        python_agents,
        AgentPythonCodeToolConfigs.objects.filter(
            agent__org_id=org_id,
            pythoncodetoolconfig__tool_id__in=python_tool_ids,
        ).values_list("pythoncodetoolconfig__tool_id", "agent_id"),
    )
    mcp_agents = _agents_by_tool(
        AgentMcpTools.objects.filter(
            agent__org_id=org_id, mcptool_id__in=mcp_tool_ids
        ).values_list("mcptool_id", "agent_id")
    )
    return configured_agents, python_agents, mcp_agents


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
            }
        )
    return rows
