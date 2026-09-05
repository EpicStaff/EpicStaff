from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiResponse,
    inline_serializer,
)
from rest_framework import serializers as drf_serializers
from rest_framework.settings import api_settings

from tables.serializers.serializers import (
    ToolUsageDetailSerializer,
    ToolUsageSerializer,
)

_USAGE_REQUEST = inline_serializer(
    name="ToolUsageRequest",
    fields={
        "ids": drf_serializers.ListField(
            child=drf_serializers.IntegerField(), required=False
        ),
    },
)


def _usage_post_schema(*, tool_kind: str, model_name: str, example_id: int) -> dict:
    return dict(
        summary=f"{model_name} usage aggregation",
        description=(
            f"Returns raw usage counts for `{model_name}` rows visible to the "
            "active org, computed against the surfaces attaching the tool. "
            "For each tool: `agent_surface_count` (catalog surfaces with a "
            "non-null `owner_agent`), `shared_surface_count` (catalog "
            "surfaces with a null `owner_agent`), `inline_count` (task-node "
            "and agent-node inline surfaces combined) — see the usage-detail "
            "endpoint for the per-entry breakdown — and `is_built_in` so the "
            "FE can gate orphan-highlighting on `!is_built_in`. "
            "`mode=\"deny\"` attachments never count. Does not exclude "
            "built-in or orphaned rows itself and does not return reference "
            "detail lists — counts only.\n\n"
            "Optional `ids` in the request body: a list of numeric ids to "
            "scope the response to only those tools, e.g. after the FE "
            "paginates its own tools list. Omitted or empty returns all rows "
            "for the active org (default, backward-compatible behavior). "
            f"Maximum number of ids is {api_settings.PAGE_SIZE}."
        ),
        request=_USAGE_REQUEST,
        responses={
            200: OpenApiResponse(
                response=ToolUsageSerializer(many=True),
                description="Per-tool usage counts",
                examples=[
                    OpenApiExample(
                        "Usage counts",
                        value=[
                            {
                                "id": example_id,
                                "agent_surface_count": 0,
                                "shared_surface_count": 0,
                                "inline_count": 0,
                                "is_built_in": False,
                            },
                        ],
                        response_only=True,
                    ),
                ],
            ),
            400: OpenApiResponse(
                response=OpenApiTypes.STR,
                description=(
                    f"`ids` is not a list of integers, or more than {api_settings.PAGE_SIZE} ids given."
                ),
            ),
        },
    )


def _usage_detail_get_schema(*, model_name: str) -> dict:
    return dict(
        summary=f"{model_name} usage detail ('Where is this used?')",
        description=(
            f"Returns the actual referencing Surfaces for a single "
            f"`{model_name}`, identified by its id in the URL — the same "
            "traversal as the usage aggregation endpoint but returning ids + "
            "names instead of counts, split into three separate lists: "
            "`agent_surface` (a catalog `Surface` with a non-null "
            "`owner_agent`), `shared_surface` (a catalog `Surface` with a "
            "null `owner_agent`), and `inline` (a `TaskNode`/`AgentNode` "
            "inline surface, `id` is the owning graph's id). Does not "
            "exclude built-in tools."
        ),
        responses={
            200: OpenApiResponse(
                response=ToolUsageDetailSerializer(),
                description="Surfaces referencing the tool",
                examples=[
                    OpenApiExample(
                        "Usage detail",
                        value={
                            "agent_surface": [
                                {"id": 5, "name": "Research Bundle"},
                            ],
                            "shared_surface": [
                                {"id": 6, "name": "Shared Bundle"},
                            ],
                            "inline": [
                                {"id": 8, "name": "My Flow - task_node_3"},
                            ],
                        },
                        response_only=True,
                    ),
                ],
            ),
            404: OpenApiResponse(
                description="Tool not found (or not visible to the active org)."
            ),
        },
    )


PYTHON_CODE_TOOL_USAGE_POST = _usage_post_schema(
    tool_kind="python-code-tool", model_name="PythonCodeTool", example_id=12
)
PYTHON_CODE_TOOL_USAGE_DETAIL_GET = _usage_detail_get_schema(
    model_name="PythonCodeTool"
)

MCP_TOOL_USAGE_POST = _usage_post_schema(
    tool_kind="mcp-tool", model_name="McpTool", example_id=7
)
MCP_TOOL_USAGE_DETAIL_GET = _usage_detail_get_schema(model_name="McpTool")
