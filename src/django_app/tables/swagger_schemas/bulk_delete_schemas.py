from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiResponse
from rbac.models.enums import ResourceType

from tables.serializers.serializers import (
    BulkDeleteQuerySerializer,
    BulkDeleteRequestSerializer,
    BulkDeleteResultSerializer,
)
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

CROSS_ORG_CASCADE_409_RESPONSE = OpenApiResponse(
    response=OpenApiTypes.STR,
    description=(
        "`cross_org_cascade`: deleting a row would change another organization's "
        "rows. Nothing was deleted; the whole request is rolled back rather than "
        "reported per id. The message names neither the row nor the organization."
    ),
    examples=[
        OpenApiExample(
            "Cross-org cascade",
            value={
                "status_code": 409,
                "code": "cross_org_cascade",
                "message": (
                    "This item is linked to data it can't be deleted with. "
                    "Nothing was deleted. Contact an administrator."
                ),
            },
            response_only=True,
            status_codes=["409"],
        ),
    ],
)


def _empty_bucket(resource_type: ResourceType) -> dict:
    return {
        "resource_type": resource_type.value,
        "visible_count": 0,
        "visible_sample": [],
        "truncated": False,
    }


def _dry_run_example(bucket_types: tuple[ResourceType, ...]) -> OpenApiExample:
    """A 200 dry run with the buckets this entity really reports, in order.

    Every id gets one bucket per referencing resource type, so an entity with
    no referencing sources reports `[]` and can never be blocked.
    """
    buckets = [_empty_bucket(resource_type) for resource_type in bucket_types]
    value = {
        "dry_run": True,
        "deleted_count": 0,
        "deleted_ids": [],
        "deletable_ids": [1],
        "not_found_ids": [99],
        "skipped": [],
        "usage": {"1": {"blocked": False, "by_resource_type": buckets}},
    }
    if bucket_types:
        # A caller who cannot see the reference learns only that id 2 is blocked.
        value["skipped"] = [{"id": 2, "reason": "in_use_restricted"}]
        value["usage"]["2"] = {"blocked": True, "by_resource_type": buckets}
    return OpenApiExample(
        "Dry run with a blocked id" if bucket_types else "Dry run with an unknown id",
        value=value,
        response_only=True,
        status_codes=["200"],
    )


def _partial_example(bucket_types: tuple[ResourceType, ...]) -> OpenApiExample:
    """A 207 real delete: one id deleted, the others not found or skipped."""
    value = {
        "dry_run": False,
        "deleted_count": 1,
        "deleted_ids": [1],
        "deletable_ids": [1],
        "not_found_ids": [99],
        "skipped": [],
        "usage": {},
    }
    if bucket_types:
        value["skipped"] = [{"id": 2, "reason": "in_use_restricted"}]
    return OpenApiExample(
        "Deleted with a blocked id" if bucket_types else "Deleted with an unknown id",
        value=value,
        response_only=True,
        status_codes=["207"],
    )


def _bulk_delete_post_schema(
    *,
    model_name: str,
    gate: ResourceType,
    bucket_types: tuple[ResourceType, ...],
    extra_responses: dict[int, OpenApiResponse] | None = None,
) -> dict:
    return {
        "summary": f"Bulk delete {model_name}s",
        "description": (
            f"Deletes the requested `{model_name}` rows the caller may delete, "
            "scoped to the active org, and reports every other id instead of "
            "failing the request. An id is **not found** when it does not "
            "exist, belongs to another org, or is not deletable — the three are "
            "indistinguishable by design. An id is **skipped** with "
            "`in_use_restricted` when something the caller cannot see "
            "references it; usage the caller *can* see does not block. "
            "A real delete responds 200 when every id went as requested and 207 "
            "when any id was not found or skipped; a dry run always responds 200. "
            "`usage` is populated only on a dry run; "
            "a real delete returns it empty."
        ),
        "parameters": [BulkDeleteQuerySerializer],
        "request": BulkDeleteRequestSerializer,
        "responses": {
            200: OpenApiResponse(
                response=BulkDeleteResultSerializer,
                description=(
                    "A real delete removed every requested id, or a dry run "
                    "reported what would happen to each id."
                ),
                examples=[
                    OpenApiExample(
                        "Deleted",
                        value={
                            "dry_run": False,
                            "deleted_count": 2,
                            "deleted_ids": [1, 2],
                            "deletable_ids": [1, 2],
                            "not_found_ids": [],
                            "skipped": [],
                            "usage": {},
                        },
                        response_only=True,
                        status_codes=["200"],
                    ),
                    _dry_run_example(bucket_types),
                ],
            ),
            207: OpenApiResponse(
                response=BulkDeleteResultSerializer,
                description=(
                    "Partial real delete: at least one id was not found or was "
                    "skipped. The body reports the outcome for every id."
                ),
                examples=[_partial_example(bucket_types)],
            ),
            400: OpenApiResponse(
                response=OpenApiTypes.STR,
                description=(
                    "`ids` is missing, empty, over 500 long, or not a list of "
                    "positive integers; the body holds a key other than `ids` "
                    "(`dry_run` included); or `?dry_run` is not a boolean, is "
                    "blank, or is repeated."
                ),
            ),
            401: UNAUTHORIZED_401_RESPONSE,
            403: OpenApiResponse(
                response=OpenApiTypes.STR,
                description=(
                    f"The caller lacks `DELETE` on the `{gate.value}` resource "
                    "type in the active org."
                ),
            ),
            **(extra_responses or {}),
        },
    }


GRAPH_BULK_DELETE_POST = _bulk_delete_post_schema(
    model_name="Graph",
    gate=ResourceType.FLOWS,
    bucket_types=(ResourceType.FLOWS,),
    extra_responses={409: CROSS_ORG_CASCADE_409_RESPONSE},
)
GRAPH_VERSION_BULK_DELETE_POST = _bulk_delete_post_schema(
    model_name="GraphVersion",
    gate=ResourceType.FLOWS,
    bucket_types=(),
    extra_responses={409: CROSS_ORG_CASCADE_409_RESPONSE},
)
LLM_CONFIG_BULK_DELETE_POST = _bulk_delete_post_schema(
    model_name="LLMConfig",
    gate=ResourceType.LLM_CONFIGS,
    bucket_types=(
        ResourceType.AGENTS,
        ResourceType.FLOWS,
        ResourceType.KNOWLEDGE_SOURCES,
    ),
)
EMBEDDING_CONFIG_BULK_DELETE_POST = _bulk_delete_post_schema(
    model_name="EmbeddingConfig",
    gate=ResourceType.LLM_CONFIGS,
    bucket_types=(ResourceType.KNOWLEDGE_SOURCES,),
)
_REALTIME_CONFIG = {"gate": ResourceType.LLM_CONFIGS, "bucket_types": (ResourceType.AGENTS,)}
OPENAI_REALTIME_CONFIG_BULK_DELETE_POST = _bulk_delete_post_schema(
    model_name="OpenAIRealtimeConfig", **_REALTIME_CONFIG
)
ELEVENLABS_REALTIME_CONFIG_BULK_DELETE_POST = _bulk_delete_post_schema(
    model_name="ElevenLabsRealtimeConfig", **_REALTIME_CONFIG
)
GEMINI_REALTIME_CONFIG_BULK_DELETE_POST = _bulk_delete_post_schema(
    model_name="GeminiRealtimeConfig", **_REALTIME_CONFIG
)
