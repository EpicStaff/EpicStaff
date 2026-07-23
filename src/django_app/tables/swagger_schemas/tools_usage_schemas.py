from drf_spectacular.utils import OpenApiExample, OpenApiResponse

from tables.serializers.serializers import ToolUsageSerializer

TOOLS_USAGE_GET = dict(
    summary="Tools usage aggregation",
    description=(
        "Returns raw usage counts for every tool visible to the active org, "
        "across all three tool kinds (registered/configured, python-code, mcp). "
        "For each tool: `projects_count` (distinct Graphs reached via the "
        "tool's agents -> their crews -> crew nodes) and `staff_count` "
        "(distinct Agents referencing the tool). Does not exclude orphaned "
        "or built-in tools (EST-3277) and does not return reference detail "
        "lists (EST-3270) — counts only."
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
                        },
                        {
                            "unique_name": "python-code-tool:12",
                            "projects_count": 0,
                            "staff_count": 0,
                        },
                        {
                            "unique_name": "mcp-tool:7",
                            "projects_count": 1,
                            "staff_count": 0,
                        },
                    ],
                    response_only=True,
                ),
            ],
        ),
    },
)
