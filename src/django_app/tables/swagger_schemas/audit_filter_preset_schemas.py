from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse

from tables.import_export.enums import EntityType
from tables.models.audit_filter_preset_models import AuditPresetDomain
from tables.serializers.model_serializers.audit_filter_preset_serializers import (
    AuditFilterPresetCopySerializer,
)
from tables.serializers.serializers import BulkExportSerializer
from tables.swagger_schemas.common_schemas import (
    FLOW_WITH_TRIGGER_NODES_403_RESPONSE,
    UNAUTHORIZED_401_RESPONSE,
)

_PRESET_EXAMPLE = {
    "id": 1,
    "name": "My Filter",
    "filter_body": {"query": 'status = "failed"'},
}
_EXPORTED_PRESET_EXAMPLE = {**_PRESET_EXAMPLE, "domain": AuditPresetDomain.SESSIONS.value}

AUDIT_FILTER_PRESET_DOMAIN = {
    "parameters": [
        OpenApiParameter(
            name="domain",
            type=str,
            location=OpenApiParameter.QUERY,
            enum=AuditPresetDomain.values,
            default=AuditPresetDomain.SESSIONS.value,
            description=(
                "The Audit tab the presets belong to. Every action works only on this "
                "domain's presets and needs its read permission: `sessions` AUDIT:read, "
                "`user_actions` USER_AUDIT:read. Any other value is a 400. The "
                "`filter_body` keys follow the domain: `match_scope` is sessions-only."
            ),
        )
    ],
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
        "`{id, name, filter_body, domain}` object, matching the single-item shape "
        "`import` accepts. Same convention as Agent/Crew/Graph export. "
        "Visibility is not exported - an import reuses a preset with the same "
        "search or creates a private one. "
        "A colleague's private preset 404s."
    ),
    "responses": {
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="The preset, as a downloadable JSON file.",
            examples=[
                OpenApiExample("Exported", value=_EXPORTED_PRESET_EXAMPLE, response_only=True)
            ],
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
                    "Exported", value={"presets": [_EXPORTED_PRESET_EXAMPLE]}, response_only=True
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
        "claims. Every preset in the file must be of the requested `domain` "
        "(a file without `domain` holds sessions presets), or the import is a 400 "
        "and nothing is created. An entry with the same search (`filters`, `query`, `match_scope`) "
        "as one of the caller's own presets or any shared preset of the domain in the org is "
        "not created; that preset is reported under `reused`. Otherwise the "
        "preset is created private (My Presets) for the caller, even if the file "
        "carries `is_shared`; a name the caller already uses for one of their own "
        "presets (private or shared) is auto-numbered like `copy` (`My Filter (2)`). "
        "Colleagues' names do not count. Same raw "
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
                        EntityType.AUDIT_FILTER_PRESET.value: {
                            "total": 1,
                            "created": {"count": 1, "items": [_EXPORTED_PRESET_EXAMPLE]},
                            "reused": {"count": 0, "items": []},
                        },
                    },
                    response_only=True,
                ),
                OpenApiExample(
                    "Name already taken by one of the caller's own presets",
                    value={
                        EntityType.AUDIT_FILTER_PRESET.value: {
                            "total": 1,
                            "created": {
                                "count": 1,
                                "items": [{**_EXPORTED_PRESET_EXAMPLE, "name": "My Filter (2)"}],
                            },
                            "reused": {"count": 0, "items": []},
                        },
                    },
                    response_only=True,
                ),
            ],
        ),
        400: OpenApiResponse(
            description=(
                "Invalid file, wrong main entity, a preset of another domain, or a "
                "validation error on an item (e.g. missing `name`)."
            )
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        # Refused when the file carries a flow with trigger nodes and the caller lacks Use.
        403: FLOW_WITH_TRIGGER_NODES_403_RESPONSE,
    },
}
