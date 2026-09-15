from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiResponse

from tables.serializers.model_serializers.audit_filter_preset_serializers import (
    AuditFilterPresetCopySerializer,
)
from tables.serializers.serializers import BulkExportSerializer
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

_PRESET_EXAMPLE = {"id": 1, "name": "My Filter", "filter_body": {"query": 'status = "failed"'}}

AUDIT_FILTER_PRESET_COPY = dict(
    summary="Copy a saved preset",
    description=(
        "Clones the preset's `filter_body` under a new row. `name` is "
        "optional - if omitted, the original's own name is reused, "
        "auto-numbered (`My Filter` -> `My Filter #2`) the same way "
        "Crew/Agent/Graph copy already works if that name is taken."
    ),
    request=AuditFilterPresetCopySerializer,
    responses={
        201: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Preset copied.",
            examples=[
                OpenApiExample(
                    "Copied",
                    value={**_PRESET_EXAMPLE, "id": 2, "name": "My Filter #2"},
                    response_only=True,
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
    },
)

AUDIT_FILTER_PRESET_EXPORT_ONE = dict(
    summary="Export one saved preset by id",
    description=(
        "Downloads a single preset as a `.json` attachment - the bare "
        "`{id, name, filter_body}` object, matching the single-item shape "
        "`import` accepts. Same convention as Agent/Crew/Graph export."
    ),
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="The preset, as a downloadable JSON file.",
            examples=[OpenApiExample("Exported", value=_PRESET_EXAMPLE, response_only=True)],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
    },
)

AUDIT_FILTER_PRESET_EXPORT_ALL = dict(
    summary="Export a selection of the caller's own saved presets",
    description=(
        "Bulk counterpart to the single-preset export above - always "
        "returns the `{\"presets\": [...]}` batch shape (even for one id), "
        "matching what `import`'s batch mode accepts. `ids` is required "
        "and non-empty (same `BulkExportSerializer` GraphViewSet.bulk_export "
        "uses) - an id that isn't the caller's own, or doesn't exist, 400s "
        "the whole request rather than being silently dropped."
    ),
    request=BulkExportSerializer,
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="A `{presets: [...]}` batch, as a downloadable JSON file.",
            examples=[
                OpenApiExample("Exported", value={"presets": [_PRESET_EXAMPLE]}, response_only=True),
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="One or more requested ids don't exist (or aren't the caller's own).",
            examples=[
                OpenApiExample(
                    "Unknown id",
                    value={"message": "Some entity IDs do not exist"},
                    response_only=True,
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
    },
    examples=[
        OpenApiExample("Export a selection", value={"ids": [1, 2, 3]}, request_only=True),
    ],
)

AUDIT_FILTER_PRESET_IMPORT = dict(
    summary="Import a preset file (upload) - single object or a batch",
    description=(
        "Upload the exact `.json` file the single or bulk export endpoint "
        "produced - "
        "either the single-object shape or a `{\"presets\": [...]}` batch. "
        "`org`/`created_by` always come from the caller's own request, "
        "regardless of anything the imported file itself claims. Each "
        "item is processed independently: a name collision with an "
        "existing preset lands it in `skipped_duplicate` rather than "
        "failing the whole batch, and any other error lands it in `failed`."
    ),
    request={
        "multipart/form-data": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "format": "binary"},
            },
            "required": ["file"],
        }
    },
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="All items processed without error.",
            examples=[
                OpenApiExample(
                    "Imported",
                    value={
                        "created": [_PRESET_EXAMPLE],
                        "skipped_duplicate": [],
                        "failed": [],
                    },
                    response_only=True,
                ),
            ],
        ),
        207: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="At least one item failed - `created`/`skipped_duplicate` still reflect whatever did succeed.",
            examples=[
                OpenApiExample(
                    "Partial failure",
                    value={
                        "created": [],
                        "skipped_duplicate": ["My Filter"],
                        "failed": [],
                    },
                    response_only=True,
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
    },
)
