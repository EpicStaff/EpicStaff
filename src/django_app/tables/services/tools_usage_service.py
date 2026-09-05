"""Aggregates per-tool usage counts (surfaces) for the Tools page, plus the
per-tool reference DETAIL lookup for the "Where is this used?" modal.

Reports a single thing — surfaces attaching the tool — split into three
separate buckets, purely from which through-model family the row comes from
(no runtime-reachability semantics implied):

- `agent_surface` — a catalog `Surface` (via `SurfacePythonTool`/
  `SurfaceMcpTool`) whose `owner_agent` is set.
- `shared_surface` — a catalog `Surface` whose `owner_agent` is null.
- `inline` — an `InlineSurface` on a `TaskNode` (via
  `InlineSurfacePythonTool`/`InlineSurfaceMcpTool`) or an `AgentInlineSurface`
  on an `AgentNode` (via `AgentInlineSurfacePythonTool`/
  `AgentInlineSurfaceMcpTool`) — both collapse into this one bucket.

`mode="deny"` rows never count as usage — a deny row exists to *suppress* a
tool, so counting it would invert its meaning.

Deliberately query-shaped as a small, fixed number of bulk queries + Python
list merging (rather than annotate()-ing multiple Count(distinct=True)
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
    AgentInlineSurfaceMcpTool,
    AgentInlineSurfacePythonTool,
    InlineSurfaceMcpTool,
    InlineSurfacePythonTool,
    SurfaceMcpTool,
    SurfacePythonTool,
    ToolMode,
)
from tables.models import McpTool, PythonCodeTool

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

    surfaces_by_tool = _surfaces_by_tool(org_id, tool_ids, tool_class)

    return _build_rows(
        tool_ids,
        surfaces_by_tool,
        is_built_in=lambda tool_id: tool_built_in.get(tool_id, False),
    )


def _empty_buckets() -> dict[str, list[dict]]:
    return {"agent_surface": [], "shared_surface": [], "inline": []}


def _surfaces_by_tool(
    org_id: int, tool_ids: list[int], tool_class: type
) -> dict[int, dict[str, list[dict]]]:
    """Per-tool-id `{"agent_surface": [...], "shared_surface": [...],
    "inline": [...]}` buckets across the three attachment families. Each
    `mode="allow"` row is reported as its own entry; entries are
    intentionally NOT deduped (e.g. two different flow nodes both attaching
    the same tool inline produce two separate `inline` entries). Still ONE
    bulk query per through-model family — the catalog-surface query is fetched
    once and split into `agent_surface`/`shared_surface` in Python based on
    `owner_agent_id`; the two inline families both feed the single `inline`
    bucket."""
    surfaces_by_tool: dict[int, dict[str, list[dict]]] = defaultdict(_empty_buckets)

    for tool_id, bucket, entry in _catalog_surface_entries(org_id, tool_ids, tool_class):
        surfaces_by_tool[tool_id][bucket].append(entry)
    for tool_id, entry in _task_inline_surface_entries(org_id, tool_ids, tool_class):
        surfaces_by_tool[tool_id]["inline"].append(entry)
    for tool_id, entry in _agent_inline_surface_entries(org_id, tool_ids, tool_class):
        surfaces_by_tool[tool_id]["inline"].append(entry)

    return surfaces_by_tool


def _catalog_surface_entries(org_id: int, tool_ids: list[int], tool_class: type):
    """Yields `(tool_id, bucket, entry)` for catalog-surface rows — one bulk
    query, split by `owner_agent_id` into the `agent_surface`/`shared_surface`
    buckets in Python."""
    catalog_model = _CATALOG_TOOL_MODEL[tool_class]
    tool_field = _TOOL_FIELD[tool_class]

    rows = catalog_model.objects.filter(
        mode=ToolMode.ALLOW,
        surface__organization_id=org_id,
        **{f"{tool_field}__in": tool_ids},
    ).values_list(tool_field, "surface_id", "surface__name", "surface__owner_agent_id")

    for tool_id, surface_id, surface_name, owner_agent_id in rows:
        bucket = "agent_surface" if owner_agent_id is not None else "shared_surface"
        yield tool_id, bucket, {"id": surface_id, "name": surface_name}


def _task_inline_surface_entries(org_id: int, tool_ids: list[int], tool_class: type):
    """Yields `(tool_id, entry)` for task-node inline-surface rows."""
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

    for tool_id, graph_id, graph_name, node_name in rows:
        yield tool_id, {"id": graph_id, "name": f"{graph_name} - {node_name}"}


def _agent_inline_surface_entries(org_id: int, tool_ids: list[int], tool_class: type):
    """Yields `(tool_id, entry)` for agent-node inline-surface rows."""
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

    for tool_id, graph_id, graph_name, node_name in rows:
        yield tool_id, {"id": graph_id, "name": f"{graph_name} - {node_name}"}


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
    `{"agent_surface": [{"id", "name"}, ...], "shared_surface": [...],
    "inline": [...]}`. Raises `ToolNotFoundError` if the tool doesn't exist /
    isn't visible to `org_id`.
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
    docstring for the three-bucket shape (unchanged for MCP tools).
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
    `get_mcp_tool_usage_detail`: existence check + surface lookup,
    parameterized on the kind's own exists-check and tool_class."""
    if not exists_fn(tool_id, org_id):
        raise ToolNotFoundError(not_found_message)

    return _surfaces_by_tool(org_id, [tool_id], tool_class).get(
        tool_id, _empty_buckets()
    )


def _build_rows(
    tool_ids: list[int],
    surfaces_by_tool: dict[int, dict[str, list[dict]]],
    is_built_in,
) -> list[dict]:
    rows: list[dict] = []
    for tool_id in tool_ids:
        buckets = surfaces_by_tool.get(tool_id, _empty_buckets())
        rows.append(
            {
                "id": tool_id,
                "agent_surface_count": len(buckets["agent_surface"]),
                "shared_surface_count": len(buckets["shared_surface"]),
                "inline_count": len(buckets["inline"]),
                "is_built_in": bool(is_built_in(tool_id)),
            }
        )
    return rows
