from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiResponse

from tables.import_export.enums import EntityType
from tables.serializers.model_serializers.audit_filter_preset_serializers import (
    AuditFilterPresetCopySerializer,
)
from tables.serializers.transfer_job_serializers import (
    ExportJobCreatedSerializer,
    ExportJobCreateSerializer,
)
from tables.swagger_schemas.common_schemas import (
    FLOW_WITH_TRIGGER_NODES_403_RESPONSE,
    UNAUTHORIZED_401_RESPONSE,
)

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

AUDIT_FILTER_PRESET_EXPORT_JOBS = {
    "summary": "Queue an export of a selection of saved presets",
    "description": (
        "Starts a background export job of the presets in `ids` and answers 202 "
        "with its `job_id`; poll `GET /api/transfer-jobs/{id}/` and download the "
        "`.zip` (`export.json` inside) once it completes. Every id must be a preset "
        "the caller can see in the active org (their own, or a shared one): any "
        "other id - another org's, a colleague's private preset, or none at all - "
        "404s the whole request with `export_entities_not_found`. Visibility is not "
        "exported - an import reuses a preset with the same search or creates a "
        "private one."
    ),
    "request": ExportJobCreateSerializer,
    "responses": {
        202: ExportJobCreatedSerializer,
        404: OpenApiResponse(
            description="`export_entities_not_found`: an id is no preset the caller can see."
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        429: OpenApiResponse(description="`too_many_jobs`: wait for an export to finish."),
    },
    "examples": [
        OpenApiExample("Export a selection", value={"ids": [1, 2, 3]}, request_only=True),
    ],
}

AUDIT_FILTER_PRESET_IMPORT = {
    "summary": "Import a preset file (upload) - single object or a batch",
    "description": (
        "Upload the `.zip` an export job produced, or the `.json` of an older "
        'export - either the single-object shape or a `{"presets": '
        "[...]}` batch. `org`/`created_by` always come from the caller's "
        "own request, regardless of anything the imported file itself "
        "claims. An entry with the same search (`filters`, `query`, `match_scope`) "
        "as one of the caller's own presets or any shared preset in the org is "
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
                            "created": {"count": 1, "items": [_PRESET_EXAMPLE]},
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
        # Refused when the file carries a flow with trigger nodes and the caller lacks Use.
        403: FLOW_WITH_TRIGGER_NODES_403_RESPONSE,
    },
}
