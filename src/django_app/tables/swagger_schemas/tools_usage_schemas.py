from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse

from tables.serializers.serializers import ToolUsageDetailSerializer, ToolUsageSerializer

TOOLS_USAGE_GET = dict(
    summary="Tools usage aggregation",
    description=(
        "Returns raw usage counts for every tool visible to the active org, "
        "across all three tool kinds (registered/configured, python-code, mcp). "
        "For each tool: `projects_count` (distinct Graphs reached via the "
        "tool's agents -> their crews -> crew nodes), `staff_count` "
        "(distinct Agents referencing the tool), and `is_built_in` (EST-3277) "
        "so the FE can gate orphan-highlighting on `!is_built_in` — registered "
        "tools are always `is_built_in=true`, MCP tools are always "
        "`is_built_in=false`, and python-code tools reflect their own "
        "`built_in` flag. Does not exclude built-in or orphaned rows itself "
        "and does not return reference detail lists (EST-3270) — counts only."
    ),
    responses={
        200: OpenApiResponse(
            response=ToolUsageSerializer(many=True),
            description="Per-tool usage counts",
            examples=[
                OpenApiExample(
                    "Usage counts",
                    value=[
                        {
                            "unique_name": "configured-tool:5",
                            "projects_count": 2,
                            "staff_count": 3,
                            "is_built_in": True,
                        },
                        {
                            "unique_name": "python-code-tool:12",
                            "projects_count": 0,
                            "staff_count": 0,
                            "is_built_in": False,
                        },
                        {
                            "unique_name": "mcp-tool:7",
                            "projects_count": 1,
                            "staff_count": 0,
                            "is_built_in": False,
                        },
                    ],
                    response_only=True,
                ),
            ],
        ),
    },
)

TOOLS_USAGE_DETAIL_GET = dict(
    summary="Tool usage detail ('Where is this used?')",
    description=(
        "Returns the actual referencing Projects (Graphs) and Staff (Agents) "
        "for a single tool, identified by `unique_name` "
        "(`<prefix>:<id>`, prefix one of `configured-tool`, "
        "`python-code-tool`, `mcp-tool`) — the same agent/graph traversal as "
        "`/tools/usage/` but returning ids + names instead of counts. "
        "Does not exclude built-in tools (EST-3277)."
    ),
    parameters=[
        OpenApiParameter(
            name="unique_name",
            type=str,
            location=OpenApiParameter.QUERY,
            required=True,
            description="`<prefix>:<id>`, e.g. `configured-tool:5`.",
        ),
    ],
    responses={
        200: OpenApiResponse(
            response=ToolUsageDetailSerializer(),
            description="Projects and staff referencing the tool",
            examples=[
                OpenApiExample(
                    "Usage detail",
                    value={
                        "projects": [{"id": 12, "name": "My Project"}],
                        "staff": [{"id": 5, "role": "Researcher"}],
                    },
                    response_only=True,
                ),
            ],
        ),
        400: OpenApiResponse(
            description="Missing/malformed `unique_name` or unknown prefix."
        ),
        404: OpenApiResponse(description="Tool not found (or not visible to the active org)."),
    },
)
