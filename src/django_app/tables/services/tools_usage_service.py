"""Aggregates per-tool usage counts (agents/surfaces) for the Tools page's, plus the per-tool reference
DETAIL lookup for the "Where is this used?" modal.

Note: `InlineSurface`/`AgentInlineSurface` entries count toward `surfaces_count`/
`surfaces` but are deliberately excluded from `agents_count`/`agents` — see the
comment above `_agents_by_tool`'s reachability-path merge for why.

- Catalog `Surface` (via `SurfacePythonTool`/`SurfaceMcpTool`) — reached by an
  `AgentDefinition` as the surface's `owner_agent` (agent-specific surface),
  or — for a shared surface (`owner_agent` null) — via an
  `AgentDefaultSurface` assignment OR a direct `TaskNode.surface_list`/
  `AgentNode.surface_list` M2M attachment on a node whose `agent_definition`
  is set. All three are independent, additive reachability paths for the
  same catalog surface (see `surface-tool-attachment-contract` in
  `wiki/topics/agent-definitions.md`).
- `InlineSurface` on a `TaskNode` (via `InlineSurfacePythonTool`/
  `InlineSurfaceMcpTool`).
- `AgentInlineSurface` on an `AgentNode` (via
  `AgentInlineSurfacePythonTool`/`AgentInlineSurfaceMcpTool`).

`mode="deny"` rows never count as usage — a deny row exists to *suppress* a
tool, so counting it would invert its meaning.

Deliberately query-shaped as a small, fixed number of bulk queries + Python
set/dict merging (rather than annotate()-ing multiple Count(distinct=True)
aggregates in one query, which silently multiplies rows across independent
reverse joins) and rather than a per-tool query loop.

Split per tool kind (python-code-tool / mcp-tool) rather than dispatched
through a shared `unique_name` prefix — each kind has its own usage/
usage-detail actions on its own ViewSet, scoped to plain numeric ids instead
of `<prefix>:<id>` strings.
"""

from collections import defaultdict

from django.db.models import Q

from agents.models import (
    AgentDefaultSurface,
    AgentDefinition,
    AgentInlineSurfaceMcpTool,
    AgentInlineSurfacePythonTool,
    InlineSurfaceMcpTool,
    InlineSurfacePythonTool,
    SurfaceMcpTool,
    SurfacePythonTool,
    ToolMode,
)
from tables.models import McpTool, PythonCodeTool
from tables.models.graph_models import AgentNode, TaskNode

_CATALOG_TOOL_MODEL = {
    PythonCodeTool: SurfacePythonTool,
    McpTool: SurfaceMcpTool,
}
_TASK_INLINE_TOOL_MODEL = {
    PythonCodeTool: InlineSurfacePythonTool,
    McpTool: InlineSurfaceMcpTool,
}
_AGENT_INLINE_TOOL_MODEL = {
    PythonCodeTool: AgentInlineSurfacePythonTool,
    McpTool: AgentInlineSurfaceMcpTool,
}
_TOOL_FIELD = {
    PythonCodeTool: "python_tool_id",
    McpTool: "mcp_tool_id",
}


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
    return _get_tool_usage(org_id, tool_built_in, PythonCodeTool)


def _get_mcp_tool_usage(org_id: int, id_q: dict) -> list[dict]:
    tool_built_in = dict.fromkeys(
        McpTool.objects.filter(org_id=org_id, **id_q).values_list("id", flat=True),
        False,
    )
    return _get_tool_usage(org_id, tool_built_in, McpTool)


def _get_tool_usage(
    org_id: int,
    tool_built_in: dict[int, bool],
    tool_class: type,
) -> list[dict]:
    """Shared aggregation body for `_get_python_code_tool_usage`/
    `_get_mcp_tool_usage`: given the per-kind `{tool_id: is_built_in}` map
    (already scoped/filtered by the caller), builds the usage rows."""
    tool_ids = list(tool_built_in.keys())

    agents_by_tool = _agents_by_tool(org_id, tool_ids, tool_class)
    surfaces_by_tool = _surfaces_by_tool(org_id, tool_ids, tool_class)

    return _build_rows(
        tool_ids,
        agents_by_tool,
        surfaces_by_tool,
        is_built_in=lambda tool_id: tool_built_in.get(tool_id, False),
    )


def _agents_by_tool(
    org_id: int, tool_ids: list[int], tool_class: type
) -> dict[int, set[int]]:
    """Distinct `AgentDefinition` ids reached through an allow-mode catalog
    surface attachment for each tool id, merging three reachability paths:
    the surface's own `owner_agent` (agent-specific surface) and, for a
    shared surface (`owner_agent` null), every `AgentDefinition` it's
    assigned to via `AgentDefaultSurface` OR attached to directly through a
    `TaskNode.surface_list`/`AgentNode.surface_list` M2M row (an independent
    attachment mechanism used at runtime by
    `agents.services.node_surface_service.build_combined_surface`). Deduped
    by agent id.

    Deliberately excludes `InlineSurface`/`AgentInlineSurface` entries: those
    surfaces belong to a flow node (`TaskNode`/`AgentNode`), not to any
    `AgentDefinition`, so they don't represent agent-reachability even
    though they DO count toward `surfaces_count`/`surfaces` (see
    `_surfaces_by_tool`)."""
    catalog_model = _CATALOG_TOOL_MODEL[tool_class]
    tool_field = _TOOL_FIELD[tool_class]

    rows = list(
        catalog_model.objects.filter(
            mode=ToolMode.ALLOW,
            surface__organization_id=org_id,
            **{f"{tool_field}__in": tool_ids},
        ).values_list(tool_field, "surface_id", "surface__owner_agent_id")
    )
    if not rows:
        return {}

    agents_by_tool: dict[int, set[int]] = defaultdict(set)
    surface_ids_by_tool: dict[int, set[int]] = defaultdict(set)
    all_surface_ids: set[int] = set()
    for tool_id, surface_id, owner_agent_id in rows:
        surface_ids_by_tool[tool_id].add(surface_id)
        all_surface_ids.add(surface_id)
        if owner_agent_id is not None:
            agents_by_tool[tool_id].add(owner_agent_id)

    agents_by_surface: dict[int, set[int]] = defaultdict(set)
    for surface_id, agent_id in AgentDefaultSurface.objects.filter(
        surface_id__in=all_surface_ids,
        agent_definition__organization_id=org_id,
    ).values_list("surface_id", "agent_definition_id"):
        agents_by_surface[surface_id].add(agent_id)

    for surface_id, agent_id in TaskNode.objects.filter(
        surface_list__id__in=all_surface_ids,
        agent_definition_id__isnull=False,
        graph__org_id=org_id,
    ).values_list("surface_list__id", "agent_definition_id"):
        agents_by_surface[surface_id].add(agent_id)

    for surface_id, agent_id in AgentNode.objects.filter(
        surface_list__id__in=all_surface_ids,
        agent_definition_id__isnull=False,
        graph__org_id=org_id,
    ).values_list("surface_list__id", "agent_definition_id"):
        agents_by_surface[surface_id].add(agent_id)

    for tool_id, surface_ids in surface_ids_by_tool.items():
        for surface_id in surface_ids:
            agents_by_tool[tool_id].update(agents_by_surface.get(surface_id, ()))

    return agents_by_tool


def _surfaces_by_tool(
    org_id: int, tool_ids: list[int], tool_class: type
) -> dict[int, list[dict]]:
    """Distinct surface/flow-node entries across the three attachment
    families for each tool id. Unlike `_agents_by_tool`, entries are NOT
    deduped across families/rows — each through-row is its own distinct
    surface or node (at most one row per `(owner, tool)` per the model's
    `UniqueConstraint`)."""
    surfaces_by_tool: dict[int, list[dict]] = defaultdict(list)
    for entries_by_tool in (
        _catalog_surface_entries_by_tool(org_id, tool_ids, tool_class),
        _task_inline_surface_entries_by_tool(org_id, tool_ids, tool_class),
        _agent_inline_surface_entries_by_tool(org_id, tool_ids, tool_class),
    ):
        for tool_id, entries in entries_by_tool.items():
            surfaces_by_tool[tool_id].extend(entries)
    return surfaces_by_tool


def _catalog_surface_entries_by_tool(
    org_id: int, tool_ids: list[int], tool_class: type
) -> dict[int, list[dict]]:
    catalog_model = _CATALOG_TOOL_MODEL[tool_class]
    tool_field = _TOOL_FIELD[tool_class]

    rows = catalog_model.objects.filter(
        mode=ToolMode.ALLOW,
        surface__organization_id=org_id,
        **{f"{tool_field}__in": tool_ids},
    ).values_list(tool_field, "surface_id", "surface__name")

    entries_by_tool: dict[int, list[dict]] = defaultdict(list)
    for tool_id, surface_id, surface_name in rows:
        entries_by_tool[tool_id].append(
            {"kind": "surface", "id": surface_id, "name": surface_name}
        )
    return entries_by_tool


def _task_inline_surface_entries_by_tool(
    org_id: int, tool_ids: list[int], tool_class: type
) -> dict[int, list[dict]]:
    inline_model = _TASK_INLINE_TOOL_MODEL[tool_class]
    tool_field = _TOOL_FIELD[tool_class]

    rows = inline_model.objects.filter(
        mode=ToolMode.ALLOW,
        inline_surface__task_node__graph__org_id=org_id,
        **{f"{tool_field}__in": tool_ids},
    ).values_list(
        tool_field,
        "inline_surface__task_node__graph_id",
        "inline_surface__task_node__graph__name",
        "inline_surface__task_node__node_name",
    )

    entries_by_tool: dict[int, list[dict]] = defaultdict(list)
    for tool_id, graph_id, graph_name, node_name in rows:
        entries_by_tool[tool_id].append(
            {
                "kind": "flow_node",
                "id": graph_id,
                "name": f"{graph_name} - {node_name}",
            }
        )
    return entries_by_tool


def _agent_inline_surface_entries_by_tool(
    org_id: int, tool_ids: list[int], tool_class: type
) -> dict[int, list[dict]]:
    agent_inline_model = _AGENT_INLINE_TOOL_MODEL[tool_class]
    tool_field = _TOOL_FIELD[tool_class]

    rows = agent_inline_model.objects.filter(
        mode=ToolMode.ALLOW,
        agent_inline_surface__agent_node__graph__org_id=org_id,
        **{f"{tool_field}__in": tool_ids},
    ).values_list(
        tool_field,
        "agent_inline_surface__agent_node__graph_id",
        "agent_inline_surface__agent_node__graph__name",
        "agent_inline_surface__agent_node__node_name",
    )

    entries_by_tool: dict[int, list[dict]] = defaultdict(list)
    for tool_id, graph_id, graph_name, node_name in rows:
        entries_by_tool[tool_id].append(
            {
                "kind": "flow_node",
                "id": graph_id,
                "name": f"{graph_name} - {node_name}",
            }
        )
    return entries_by_tool


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
    `{"agents": [{"id", "name"}, ...], "surfaces": [{"id", "name", "kind"}, ...]}`.
    Raises `ToolNotFoundError` if the tool doesn't exist / isn't visible to
    `org_id`.
    """
    return _get_tool_usage_detail(
        tool_id,
        org_id,
        exists_fn=_python_tool_exists,
        tool_class=PythonCodeTool,
        not_found_message=f"python-code-tool:{tool_id} not found",
    )


def get_mcp_tool_usage_detail(tool_id: int, org_id: int) -> dict:
    """MCP-tool counterpart of `get_python_code_tool_usage_detail`. See its
    docstring for the `agents`/`surfaces` semantics (unchanged for MCP tools).
    """
    return _get_tool_usage_detail(
        tool_id,
        org_id,
        exists_fn=_mcp_tool_exists,
        tool_class=McpTool,
        not_found_message=f"mcp-tool:{tool_id} not found",
    )


def _get_tool_usage_detail(
    tool_id: int,
    org_id: int,
    exists_fn,
    tool_class: type,
    not_found_message: str,
) -> dict:
    """Shared body for `get_python_code_tool_usage_detail`/
    `get_mcp_tool_usage_detail`: existence check + agent/surface lookups,
    parameterized on the kind's own exists-check and tool_class."""
    if not exists_fn(tool_id, org_id):
        raise ToolNotFoundError(not_found_message)

    agent_ids = _agents_by_tool(org_id, [tool_id], tool_class).get(tool_id, set())
    agents = list(
        AgentDefinition.objects.filter(
            id__in=agent_ids, organization_id=org_id
        ).values("id", "name")
    )

    surfaces = _surfaces_by_tool(org_id, [tool_id], tool_class).get(tool_id, [])
    return {"agents": agents, "surfaces": surfaces}


def _build_rows(
    tool_ids: list[int],
    agents_by_tool: dict[int, set[int]],
    surfaces_by_tool: dict[int, list[dict]],
    is_built_in,
) -> list[dict]:
    rows: list[dict] = []
    for tool_id in tool_ids:
        agent_ids = agents_by_tool.get(tool_id, set())
        surfaces = surfaces_by_tool.get(tool_id, [])
        rows.append(
            {
                "id": tool_id,
                "agents_count": len(agent_ids),
                "surfaces_count": len(surfaces),
                "is_built_in": bool(is_built_in(tool_id)),
            }
        )
    return rows
