from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiResponse,
    inline_serializer,
)
from drf_spectacular.types import OpenApiTypes
from rest_framework import serializers as drf_serializers

from tables.serializers.model_serializers import (
    McpToolSerializer,
    PythonCodeToolSerializer,
)
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

_COPY_REQUEST = inline_serializer(
    name="ToolCopyRequest",
    fields={
        "name": drf_serializers.CharField(
            required=False,
            help_text=(
                "Optional name for the copied tool. If omitted, the original "
                "tool's name is reused with an auto-generated suffix on "
                "collision (e.g. \"My Tool (1)\")."
            ),
        ),
    },
)


def _copy_post_schema(
    *,
    model_name: str,
    response_serializer,
    built_in_note: str,
    error_400_description: str,
    error_400_example: dict | None,
) -> dict:
    responses = {
        201: OpenApiResponse(
            response=response_serializer,
            description=f"The newly created {model_name} copy.",
        ),
        401: UNAUTHORIZED_401_RESPONSE,
    }
    if error_400_example is not None:
        responses[400] = OpenApiResponse(
            response=OpenApiTypes.STR,
            description=error_400_description,
            examples=[
                OpenApiExample(
                    "Copy error",
                    value=error_400_example,
                    response_only=True,
                    status_codes=["400"],
                ),
            ],
        )
    return dict(
        summary=f"Copy a {model_name}",
        description=(
            f"Creates a duplicate of the `{model_name}` identified by the id "
            "in the URL, scoped to the active org. Accepts an optional "
            "`name` to override the name of the copy; if omitted, the "
            "original's name is reused with an auto-generated suffix on "
            f"collision (e.g. \"My Tool (1)\"). {built_in_note}"
        ),
        request=_COPY_REQUEST,
        responses=responses,
    )


PYTHON_CODE_TOOL_COPY_POST = _copy_post_schema(
    model_name="PythonCodeTool",
    response_serializer=PythonCodeToolSerializer,
    built_in_note="Built-in tools (`built_in=True`) cannot be copied and return a 400 error.",
    error_400_description="Built-in tools cannot be copied.",
    error_400_example={"message": "Cannot copy a built-in tool."},
)
MCP_TOOL_COPY_POST = _copy_post_schema(
    model_name="McpTool",
    response_serializer=McpToolSerializer,
    built_in_note="`McpTool` has no built-in concept, so any visible MCP tool can be copied.",
    error_400_description="Copy failed (e.g. unexpected server-side error).",
    error_400_example=None,
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
