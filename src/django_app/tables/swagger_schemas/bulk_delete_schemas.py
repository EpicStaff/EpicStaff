from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse

from tables.models.rbac_models.rbac_enums import ResourceType
from tables.serializers.serializers import (
    BulkDeleteRequestSerializer,
    BulkDeleteResultSerializer,
)
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

DRY_RUN_PARAMETER = OpenApiParameter(
    name="dry_run",
    type=OpenApiTypes.BOOL,
    location=OpenApiParameter.QUERY,
    required=False,
    default=False,
    description=(
        "Preview only: report what would be deleted and the usage that blocks "
        "the rest, without deleting anything. This is a **query parameter** — "
        "a `dry_run` field in the request body is ignored and the call runs as "
        "a real delete. An unparseable, blank (`?dry_run`, `?dry_run=`) or "
        "repeated value is rejected with 400."
    ),
)


def _empty_bucket(resource_type: ResourceType) -> dict:
    return {
        "resource_type": resource_type.value,
        "visible_count": 0,
        "visible_sample": [],
        "truncated": False,
    }


def _partial_example(bucket_types: tuple[ResourceType, ...]) -> OpenApiExample:
    """A 207 dry run with the buckets this entity really reports, in order.

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
        status_codes=["207"],
    )


def _bulk_delete_post_schema(
    *,
    model_name: str,
    gate: ResourceType,
    bucket_types: tuple[ResourceType, ...],
) -> dict:
    return dict(
        summary=f"Bulk delete {model_name}s",
        description=(
            f"Deletes the requested `{model_name}` rows the caller may delete, "
            "scoped to the active org, and reports every other id instead of "
            "failing the request. An id is **not found** when it does not "
            "exist, belongs to another org, or is not deletable — the three are "
            "indistinguishable by design. An id is **skipped** with "
            "`in_use_restricted` when something the caller cannot see "
            "references it; usage the caller *can* see does not block. "
            "Responds 200 when every id went as requested and 207 when any id "
            "was not found or skipped. `usage` is populated only on a dry run; "
            "a real delete returns it empty."
        ),
        parameters=[DRY_RUN_PARAMETER],
        request=BulkDeleteRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=BulkDeleteResultSerializer,
                description="Every requested id was deleted (or, on a dry run, would be).",
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
                ],
            ),
            207: OpenApiResponse(
                response=BulkDeleteResultSerializer,
                description=(
                    "Partial: at least one id was not found or was skipped. "
                    "The body reports the outcome for every id."
                ),
                examples=[_partial_example(bucket_types)],
            ),
            400: OpenApiResponse(
                response=OpenApiTypes.STR,
                description=(
                    "`ids` is missing, empty, over 500 long, or not a list of "
                    "positive integers — or `dry_run` is not a boolean, is "
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
        },
    )


GRAPH_BULK_DELETE_POST = _bulk_delete_post_schema(
    model_name="Graph",
    gate=ResourceType.FLOWS,
    bucket_types=(ResourceType.FLOWS,),
)
GRAPH_VERSION_BULK_DELETE_POST = _bulk_delete_post_schema(
    model_name="GraphVersion",
    gate=ResourceType.FLOWS,
    bucket_types=(),
)
LLM_CONFIG_BULK_DELETE_POST = _bulk_delete_post_schema(
    model_name="LLMConfig",
    gate=ResourceType.LLM_CONFIGS,
    bucket_types=(
        ResourceType.AGENTS,
        ResourceType.PROJECTS,
        ResourceType.FLOWS,
        ResourceType.KNOWLEDGE_SOURCES,
    ),
)
EMBEDDING_CONFIG_BULK_DELETE_POST = _bulk_delete_post_schema(
    model_name="EmbeddingConfig",
    gate=ResourceType.LLM_CONFIGS,
    bucket_types=(ResourceType.PROJECTS, ResourceType.KNOWLEDGE_SOURCES),
)
_REALTIME_CONFIG = dict(
    gate=ResourceType.LLM_CONFIGS, bucket_types=(ResourceType.AGENTS,)
)
OPENAI_REALTIME_CONFIG_BULK_DELETE_POST = _bulk_delete_post_schema(
    model_name="OpenAIRealtimeConfig", **_REALTIME_CONFIG
)
ELEVENLABS_REALTIME_CONFIG_BULK_DELETE_POST = _bulk_delete_post_schema(
    model_name="ElevenLabsRealtimeConfig", **_REALTIME_CONFIG
)
GEMINI_REALTIME_CONFIG_BULK_DELETE_POST = _bulk_delete_post_schema(
    model_name="GeminiRealtimeConfig", **_REALTIME_CONFIG
)
