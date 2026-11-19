from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiResponse
from tables.serializers.search_config_serializers import (
    GraphRagSuggestInputSerializer,
    NaiveRagSuggestInputSerializer,
    SuggestOutputSerializer,
)

NAIVE_RAG_SUGGEST_409_RESPONSE = OpenApiResponse(
    response=OpenApiTypes.STR,
    description=(
        "`rag_index_not_ready`: the collection's NaiveRag has not finished indexing. "
        "Run indexing and retry once `rag_status` is `completed`."
    ),
    examples=[
        OpenApiExample(
            "Index not ready",
            value={
                "status_code": 409,
                "code": "rag_index_not_ready",
                "message": (
                    "NaiveRAG index for collection 1 not ready. "
                    "Run indexing and wait for rag_status='completed'."
                ),
            },
            response_only=True,
            status_codes=["409"],
        ),
    ],
)

GRAPH_RAG_SUGGEST_409_RESPONSE = OpenApiResponse(
    response=OpenApiTypes.STR,
    description=(
        "`graph_rag_llm_not_configured`: the collection's GraphRag has no LLM config "
        "(for example, its LLM config was deleted); set one and retry. Reported before "
        "the index status. `rag_index_not_ready`: the GraphRag has not finished "
        "indexing. `rag_error`: the knowledge service could not return the index "
        "metrics; retry shortly."
    ),
    examples=[
        OpenApiExample(
            "LLM not configured",
            value={
                "status_code": 409,
                "code": "graph_rag_llm_not_configured",
                "message": "GraphRag for collection 1 has no LLM config.",
            },
            response_only=True,
            status_codes=["409"],
        ),
        OpenApiExample(
            "Index not ready",
            value={
                "status_code": 409,
                "code": "rag_index_not_ready",
                "message": (
                    "GraphRAG index for collection 1 not ready. "
                    "Run indexing and wait for rag_status='completed'."
                ),
            },
            response_only=True,
            status_codes=["409"],
        ),
        OpenApiExample(
            "Metrics temporarily unavailable",
            value={
                "status_code": 409,
                "code": "rag_error",
                "message": (
                    "GraphRAG metrics for collection 1 are temporarily unavailable. Retry shortly."
                ),
            },
            response_only=True,
            status_codes=["409"],
        ),
    ],
)

NAIVE_RAG_SUGGEST_PARAMS_POST = {
    "operation_id": "naive_rag_suggest_search_params",
    "summary": "Suggest NaiveRag search params for a collection",
    "description": (
        "Stateless. Computes adaptive `search_limit` and "
        "`similarity_threshold` for a NaiveRag collection from the corpus "
        "(chunk count). No LLM is involved — the `effective_llm_context_window` "
        "and `safe_token_budget` response fields are null. Pass overrides via "
        "`user_custom_params` to lock specific fields."
    ),
    "request": NaiveRagSuggestInputSerializer,
    "responses": {200: SuggestOutputSerializer, 409: NAIVE_RAG_SUGGEST_409_RESPONSE},
    "examples": [
        OpenApiExample(
            "Minimal — use all suggested defaults",
            value={
                "knowledge_collection_id": 1,
            },
            request_only=True,
        ),
        OpenApiExample(
            "With user overrides",
            value={
                "knowledge_collection_id": 1,
                "user_custom_params": {
                    "search_limit": 7,
                    "similarity_threshold": 0.25,
                },
            },
            request_only=True,
        ),
    ],
}

GRAPH_RAG_SUGGEST_PARAMS_POST = {
    "operation_id": "graph_rag_suggest_search_params",
    "summary": "Suggest GraphRag search params for a collection",
    "description": (
        "Stateless. Computes adaptive params for one of the four Graph "
        "RAG search methods (`basic`, `local`, `global`, "
        "`drift`). The context window is sized against the collection's own "
        "GraphRag.llm (the search-synthesis LLM), resolved server-side — no "
        "`llm_config_id` is required. Token fields are clamped to "
        "`safe_token_budget` unless the LLM model could not be resolved "
        "by litellm (see `llm_resolution_warning`). Requires the GraphRag to have "
        "an LLM config."
    ),
    "request": GraphRagSuggestInputSerializer,
    "responses": {200: SuggestOutputSerializer, 409: GRAPH_RAG_SUGGEST_409_RESPONSE},
    "examples": [
        OpenApiExample(
            "Basic search — defaults",
            value={
                "knowledge_collection_id": 1,
                "search_method": "basic",
            },
            request_only=True,
        ),
        OpenApiExample(
            "Local search with text-unit override",
            value={
                "knowledge_collection_id": 1,
                "search_method": "local",
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
                "search_method": "global",
            },
            request_only=True,
        ),
        OpenApiExample(
            "Drift search",
            value={
                "knowledge_collection_id": 1,
                "search_method": "drift",
            },
            request_only=True,
        ),
    ],
}
