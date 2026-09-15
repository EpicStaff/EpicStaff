from drf_spectacular.utils import OpenApiExample

from tables.serializers.search_config_serializers import (
    GraphRagSuggestInputSerializer,
    NaiveRagSuggestInputSerializer,
    SuggestOutputSerializer,
)

NAIVE_RAG_SUGGEST_PARAMS_POST = dict(
    operation_id="naive_rag_suggest_search_params",
    summary="Suggest NaiveRag search params for a collection",
    description=(
        "Stateless. Computes adaptive `search_limit` and "
        "`similarity_threshold` for a NaiveRag collection from the corpus "
        "(chunk count). No LLM is involved — the `effective_llm_context_window` "
        "and `safe_token_budget` response fields are null. Pass overrides via "
        "`user_custom_params` to lock specific fields."
    ),
    request=NaiveRagSuggestInputSerializer,
    responses={200: SuggestOutputSerializer},
    examples=[
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
)

GRAPH_RAG_SUGGEST_PARAMS_POST = dict(
    operation_id="graph_rag_suggest_search_params",
    summary="Suggest GraphRag search params for a collection",
    description=(
        "Stateless. Computes adaptive params for one of the four Graph "
        "RAG search methods (`basic`, `local`, `global`, "
        "`drift`). The context window is sized against the collection's own "
        "GraphRag.llm (the search-synthesis LLM), resolved server-side — no "
        "`llm_config_id` is required. Token fields are clamped to "
        "`safe_token_budget` unless the LLM model could not be resolved "
        "by litellm (see `llm_resolution_warning`)."
    ),
    request=GraphRagSuggestInputSerializer,
    responses={200: SuggestOutputSerializer},
    examples=[
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
)
