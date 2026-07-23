from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiResponse,
    inline_serializer,
)
from drf_spectacular.types import OpenApiTypes
from rest_framework import serializers as drf_serializers

from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

_BULK_DELETE_REQUEST = inline_serializer(
    name="ToolBulkDeleteRequest",
    fields={
        "ids": drf_serializers.ListField(child=drf_serializers.IntegerField()),
    },
)

PYTHON_CODE_TOOL_BULK_DELETE_POST = dict(
    summary="Bulk delete Python-code tools",
    description=(
        "Deletes multiple `PythonCodeTool` rows (scoped to the active org) in a "
        "single atomic transaction. Built-in tools (`built_in=True`) are always "
        "excluded from deletion — silently skipped, not rejected — so the "
        "response `deleted` count only reflects rows actually removed. `ids` "
        "in the response always echoes the full requested list, regardless of "
        "which ids were actually found/deleted/skipped."
    ),
    request=_BULK_DELETE_REQUEST,
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Deletion completed (built-in ids silently skipped).",
            examples=[
                OpenApiExample(
                    "Deleted",
                    value={"deleted": 2, "ids": [1, 2, 3]},
                    response_only=True,
                    status_codes=["200"],
                ),
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="`ids` is missing, not a list, or contains non-integer values.",
            examples=[
                OpenApiExample(
                    "Invalid ids",
                    value={"detail": "ids must be a list of integers."},
                    response_only=True,
                    status_codes=["400"],
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
    },
)

MCP_TOOL_BULK_DELETE_POST = dict(
    summary="Bulk delete MCP tools",
    description=(
        "Deletes multiple `McpTool` rows (scoped to the active org) in a "
        "single atomic transaction. `McpTool` has no built-in concept, so "
        "every matching requested id is deleted."
    ),
    request=_BULK_DELETE_REQUEST,
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="MCP tools successfully deleted.",
            examples=[
                OpenApiExample(
                    "Deleted",
                    value={"deleted": 3, "ids": [1, 2, 3]},
                    response_only=True,
                    status_codes=["200"],
                ),
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="`ids` is missing, not a list, or contains non-integer values.",
            examples=[
                OpenApiExample(
                    "Invalid ids",
                    value={"detail": "ids must be a list of integers."},
                    response_only=True,
                    status_codes=["400"],
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
    },
)
