from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiResponse

from tables.import_export.enums import EntityType
from tables.serializers.model_serializers.audit_filter_preset_serializers import (
    AuditFilterPresetCopySerializer,
)
from tables.serializers.serializers import BulkExportSerializer
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

_PRESET_EXAMPLE = {
    "id": 1,
    "name": "My Filter",
    "filter_body": {"query": 'status = "failed"'},
}

AUDIT_FILTER_PRESET_COPY = {
    "summary": "Copy a saved preset",
    "description": (
        "Clones any preset of the active org into a new row owned by the "
        "caller. `name` is "
        "optional - if omitted, the original's own name is reused, "
        "auto-numbered (`My Filter` -> `My Filter (2)`, the first free "
        "number in the org) if that name is taken."
    ),
    "request": AuditFilterPresetCopySerializer,
    "responses": {
        201: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Preset copied.",
            examples=[
                OpenApiExample(
                    "Copied",
                    value={**_PRESET_EXAMPLE, "id": 2, "name": "My Filter (2)", "is_owner": True},
                    response_only=True,
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
    },
}

AUDIT_FILTER_PRESET_EXPORT_ONE = {
    "summary": "Export one saved preset by id",
    "description": (
        "Downloads a single preset as a `.json` attachment - the bare "
        "`{id, name, filter_body}` object, matching the single-item shape "
        "`import` accepts. Same convention as Agent/Crew/Graph export."
    ),
    "responses": {
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="The preset, as a downloadable JSON file.",
            examples=[OpenApiExample("Exported", value=_PRESET_EXAMPLE, response_only=True)],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
    },
}

AUDIT_FILTER_PRESET_EXPORT_ALL = {
    "summary": "Export a selection of the active org's saved presets",
    "description": (
        "Bulk counterpart to the single-preset export above - always "
        'returns the `{"presets": [...]}` batch shape (even for one id), '
        "matching what `import`'s batch mode accepts. `ids` is required "
        "and non-empty (same `BulkExportSerializer` GraphViewSet.bulk_export "
        "uses) - an id outside the active org, or one that doesn't exist, 400s "
        "the whole request rather than being silently dropped."
    ),
    "request": BulkExportSerializer,
    "responses": {
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="A `{presets: [...]}` batch, as a downloadable JSON file.",
            examples=[
                OpenApiExample(
                    "Exported", value={"presets": [_PRESET_EXAMPLE]}, response_only=True
                ),
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="One or more requested ids don't exist in the active org.",
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
    "examples": [
        OpenApiExample("Export a selection", value={"ids": [1, 2, 3]}, request_only=True),
    ],
}

AUDIT_FILTER_PRESET_IMPORT = {
    "summary": "Import a preset file (upload) - single object or a batch",
    "description": (
        "Upload the exact `.json` file the single or bulk export endpoint "
        'produced - either the single-object shape or a `{"presets": '
        "[...]}` batch. `org`/`created_by` always come from the caller's "
        "own request, regardless of anything the imported file itself "
        "claims. Every preset is created for the caller; a name already taken in "
        "the org is auto-numbered like `copy` (`My Filter (2)`), never reused. Same raw "
        "`IDMapper.get_detailed_summary()` shape `GraphViewSet.partial_import` "
        "returns, keyed by entity type (`AuditFilterPreset`, since presets "
        "are always a single-entity-type import)."
    ),
    "request": {
        "multipart/form-data": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "format": "binary"},
            },
            "required": ["file"],
        }
    },
    "responses": {
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Import summary, keyed by entity type.",
            examples=[
                OpenApiExample(
                    "Imported",
                    value={
                        EntityType.AUDIT_FILTER_PRESET: {
                            "total": 1,
                            "created": {"count": 1, "items": [_PRESET_EXAMPLE]},
                            "reused": {"count": 0, "items": []},
                        },
                    },
                    response_only=True,
                ),
                OpenApiExample(
                    "Name already taken in the org",
                    value={
                        EntityType.AUDIT_FILTER_PRESET: {
                            "total": 1,
                            "created": {
                                "count": 1,
                                "items": [{**_PRESET_EXAMPLE, "name": "My Filter (2)"}],
                            },
                            "reused": {"count": 0, "items": []},
                        },
                    },
                    response_only=True,
                ),
            ],
        ),
        400: OpenApiResponse(
            description="Invalid file, wrong main entity, or a validation error on an item (e.g. missing `name`)."
        ),
        401: UNAUTHORIZED_401_RESPONSE,
    },
}
