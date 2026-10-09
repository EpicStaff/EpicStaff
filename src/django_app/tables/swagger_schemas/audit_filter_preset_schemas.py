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
        "Clones a preset the caller can see (their own, or any shared preset of "
        "the active org) into a new row owned by the caller. `is_shared` "
        "(default `false`) decides whether the copy lands in My Presets or "
        "Shared Presets, whatever the original's visibility. `name` is "
        "optional - if omitted, the original's own name is reused, "
        "auto-numbered (`My Filter` -> `My Filter (2)`) if the caller already "
        "has a preset (private or shared) with that name in the org; colleagues' "
        "names do not count. A colleague's private preset 404s."
    ),
    "request": AuditFilterPresetCopySerializer,
    "responses": {
        201: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Preset copied.",
            examples=[
                OpenApiExample(
                    "Copied",
                    value={
                        **_PRESET_EXAMPLE,
                        "id": 2,
                        "name": "My Filter (2)",
                        "is_shared": False,
                        "is_owner": True,
                        "created_by_name": "John Smith",
                    },
                    response_only=True,
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            description="No such preset visible to the caller (another org, or a colleague's private preset)."
        ),
    },
}

AUDIT_FILTER_PRESET_EXPORT_ONE = {
    "summary": "Export one saved preset by id",
    "description": (
        "Downloads a single preset as a `.json` attachment - the bare "
        "`{id, name, filter_body}` object, matching the single-item shape "
        "`import` accepts. Same convention as Agent/Crew/Graph export. "
        "Visibility is not exported - an import always creates private presets. "
        "A colleague's private preset 404s."
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
        "uses) - an id outside the active org, a colleague's private preset, "
        "or one that doesn't exist, 400s "
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
            description="One or more requested ids aren't visible to the caller in the active org.",
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
        "claims. Every preset is created private (My Presets) for the caller, "
        "even if the file carries `is_shared`; a name the caller already uses for "
        "one of their own presets (private or shared) is auto-numbered like `copy` "
        "(`My Filter (2)`), never reused. Colleagues' names do not count. Same raw "
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
                    "Name already taken by one of the caller's own presets",
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
