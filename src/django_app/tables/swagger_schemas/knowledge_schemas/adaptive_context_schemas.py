from drf_spectacular.utils import OpenApiExample

from tables.serializers.adaptive_context_serializers import (
    ErrorResponseSerializer,
    GraphRagSuggestRequestSerializer,
    NaiveRagSuggestRequestSerializer,
    SuggestResponseSerializer,
    ValidationErrorResponseSerializer,
)

NAIVE_RAG_SUGGEST_PARAMS_POST = dict(
    operation_id="naive_rag_suggest_search_params",
    summary="Suggest NaiveRag search params for a collection + LLM",
    description=(
        "Stateless. Computes adaptive `search_limit` and "
        "`similarity_threshold` for a NaiveRag collection sized for the "
        "target LLM's context window. Pass overrides via "
        "`user_custom_params` to lock specific fields."
    ),
    request=NaiveRagSuggestRequestSerializer,
    responses={
        200: SuggestResponseSerializer,
        400: ValidationErrorResponseSerializer,
        404: ErrorResponseSerializer,
        500: ErrorResponseSerializer,
    },
    examples=[
        OpenApiExample(
            "Minimal — use all suggested defaults",
            value={
                "knowledge_collection_id": 1,
                "llm_config_id": 1,
            },
            request_only=True,
        ),
        OpenApiExample(
            "With user overrides",
            value={
                "knowledge_collection_id": 1,
                "llm_config_id": 1,
                "user_custom_params": {
                    "search_limit": 7,
                    "similarity_threshold": 0.25,
                },
            },
            request_only=True,
        ),
    ],
)

GRAPH_RAG_SUGGEST_PARAMS_POST = dict(
    operation_id="graph_rag_suggest_search_params",
    summary="Suggest GraphRag search params for a collection + LLM",
    description=(
        "Stateless. Computes adaptive params for one of the four Graph "
        "RAG search methods (`basic`, `local`, `global_search`, "
        "`drift_search`). Token fields are clamped to "
        "`safe_token_budget` unless the LLM model could not be resolved "
        "by litellm (see `llm_resolution_warning`)."
    ),
    request=GraphRagSuggestRequestSerializer,
    responses={
        200: SuggestResponseSerializer,
        400: ValidationErrorResponseSerializer,
        404: ErrorResponseSerializer,
        409: ErrorResponseSerializer,
        500: ErrorResponseSerializer,  # GraphRagArtifactMissingException + unexpected
    },
    examples=[
        OpenApiExample(
            "Basic search — defaults",
            value={
                "knowledge_collection_id": 1,
                "search_method": "basic",
                "llm_config_id": 1,
            },
            request_only=True,
        ),
        OpenApiExample(
            "Local search with text-unit override",
            value={
                "knowledge_collection_id": 1,
                "search_method": "local",
                "llm_config_id": 1,
                "user_custom_params": {
                    "text_unit_prop": 0.7,
                    "top_k_entities": 12,
                },
            },
            request_only=True,
        ),
        OpenApiExample(
            "Global search",
            value={
                "knowledge_collection_id": 1,
                "search_method": "global_search",
                "llm_config_id": 1,
            },
            request_only=True,
        ),
        OpenApiExample(
            "Drift search",
            value={
                "knowledge_collection_id": 1,
                "search_method": "drift_search",
                "llm_config_id": 1,
            },
            request_only=True,
        ),
    ],
)
