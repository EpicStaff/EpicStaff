from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    inline_serializer,
)
from drf_spectacular.types import OpenApiTypes
from rest_framework import serializers as drf_serializers

from tables.serializers.model_serializers import (
    McpToolSerializer,
    PythonCodeToolSerializer,
)
from tables.serializers.serializers import BulkExportSerializer
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

TOOL_ORDERING_PARAMETER = OpenApiParameter(
    name="ordering",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    enum=["favorite"],
    description=(
        "Set to `favorite` to sort the current user's favorited tools "
        "first. Omit for default ordering (unchanged)."
    ),
)

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

def _favorite_post_schema(*, model_name: str) -> dict:
    return dict(
        summary=f"Favorite a {model_name}",
        description=(
            f"Marks the `{model_name}` identified by the id in the URL as a "
            "favorite for the current user. This is a personal preference — "
            "it is per-user, not shared across the org — and does not affect "
            "other users' favorites. Idempotent: calling this again on a "
            "tool that is already favorited succeeds without error."
        ),
        request=None,
        responses={
            200: OpenApiResponse(description="Tool favorited (or already was)."),
            401: UNAUTHORIZED_401_RESPONSE,
        },
    )


def _favorite_delete_schema(*, model_name: str) -> dict:
    return dict(
        summary=f"Unfavorite a {model_name}",
        description=(
            f"Removes the `{model_name}` identified by the id in the URL from "
            "the current user's favorites. This is a personal preference — "
            "it is per-user, not shared across the org — and does not affect "
            "other users' favorites. Idempotent: calling this again on a "
            "tool that is not currently favorited succeeds without error."
        ),
        request=None,
        responses={
            200: OpenApiResponse(description="Tool unfavorited (or already wasn't)."),
            401: UNAUTHORIZED_401_RESPONSE,
        },
    )


PYTHON_CODE_TOOL_FAVORITE_POST = _favorite_post_schema(model_name="PythonCodeTool")
PYTHON_CODE_TOOL_FAVORITE_DELETE = _favorite_delete_schema(model_name="PythonCodeTool")
MCP_TOOL_FAVORITE_POST = _favorite_post_schema(model_name="McpTool")
MCP_TOOL_FAVORITE_DELETE = _favorite_delete_schema(model_name="McpTool")

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


def _export_get_schema(*, model_name: str) -> dict:
    return dict(
        summary=f"Export a {model_name}",
        description=(
            f"Downloads a single `{model_name}` (identified by the id in the "
            "URL) as a JSON bundle file, scoped to the active org. The "
            f"response is a raw file download — not a `{model_name}` "
            "representation — shaped like "
            f'`{{"{model_name}": [{{...}}], "Label": [...], '
            f'"main_entity": "{model_name}", "version": <int>}}`, suitable '
            "for later re-import via the `import` action."
        ),
        request=None,
        responses={
            200: OpenApiTypes.BINARY,
            401: UNAUTHORIZED_401_RESPONSE,
        },
    )


def _bulk_export_post_schema(*, model_name: str) -> dict:
    return dict(
        summary=f"Bulk export {model_name}s",
        description=(
            f"Downloads multiple `{model_name}` rows (identified by `ids`, "
            "scoped to the active org) as a single JSON bundle file. The "
            f"response is a raw file download — not a list of `{model_name}` "
            "representations — shaped like "
            f'`{{"{model_name}": [{{...}}], "Label": [...], '
            f'"main_entity": "{model_name}", "version": <int>}}`, suitable '
            "for later re-import via the `import` action."
        ),
        request=BulkExportSerializer,
        responses={
            200: OpenApiTypes.BINARY,
            400: OpenApiResponse(
                response=OpenApiTypes.STR,
                description="One or more requested `ids` do not exist (or are not visible to the active org).",
                examples=[
                    OpenApiExample(
                        "Missing ids",
                        value={"message": "Some entity IDs do not exist"},
                        response_only=True,
                        status_codes=["400"],
                    ),
                ],
            ),
            401: UNAUTHORIZED_401_RESPONSE,
        },
    )


def _import_post_schema(*, model_name: str) -> dict:
    return dict(
        summary=f"Import {model_name}(s)",
        description=(
            f"Imports one or more `{model_name}` rows from a JSON bundle file "
            "previously produced by the `export`/`bulk-export` actions "
            "(multipart form upload), scoped to the active org. "
            "`import_labels` controls whether labels included in the bundle "
            "are also created/attached (defaults to `true`). The response is "
            "an import summary — a dict keyed by entity type name, each with "
            "`total`/`created`/`reused` counts and previews — not a "
            f"`{model_name}` representation."
        ),
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "format": "binary"},
                    "import_labels": {"type": "boolean", "default": True},
                },
                "required": ["file"],
            }
        },
        responses={
            200: OpenApiResponse(
                description=(
                    "Import summary: a dict keyed by entity type name, each "
                    "with `total`, `created` (`count` + `items`), and "
                    "`reused` (`count` + `items`)."
                ),
            ),
            401: UNAUTHORIZED_401_RESPONSE,
        },
    )


PYTHON_CODE_TOOL_EXPORT_GET = _export_get_schema(model_name="PythonCodeTool")
PYTHON_CODE_TOOL_BULK_EXPORT_POST = _bulk_export_post_schema(model_name="PythonCodeTool")
PYTHON_CODE_TOOL_IMPORT_POST = _import_post_schema(model_name="PythonCodeTool")

MCP_TOOL_EXPORT_GET = _export_get_schema(model_name="McpTool")
MCP_TOOL_BULK_EXPORT_POST = _bulk_export_post_schema(model_name="McpTool")
MCP_TOOL_IMPORT_POST = _import_post_schema(model_name="McpTool")
