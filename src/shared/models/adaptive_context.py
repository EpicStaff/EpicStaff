"""HTTP-boundary DTOs for the Adaptive Context Management endpoints.

These schemas describe the request/response shapes of the
`/api/{naive,graph}-rag/suggest-search-params/` endpoints .
 They are intentionally kept separate from
`shared/models/knowledge.py`, which holds the wire-format for the Redis /
RabbitMQ message bus consumed by the search workers. Mixing both concerns
in a single module would couple HTTP-layer evolution (new fields, default
changes) to the message-bus contract, making backwards-compatible changes
harder than they need to be.

The existing search parameter models (`NaiveRagSearchConfig`,
`GraphRag*SearchParams`) are reused as-is for the `suggested_params`
field — the suggest endpoints emit exactly the same Pydantic objects the
save-side serializers and search workers already understand.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .knowledge import (
    GraphRagBasicSearchParams,
    GraphRagDriftSearchParams,
    GraphRagGlobalSearchParams,
    GraphRagLocalSearchParams,
    NaiveRagSearchConfig,
)


SuggestedSearchParams = (
    NaiveRagSearchConfig
    | GraphRagBasicSearchParams
    | GraphRagLocalSearchParams
    | GraphRagGlobalSearchParams
    | GraphRagDriftSearchParams
)


GraphSearchMethod = Literal["basic", "local", "global_search", "drift_search"]


class CollectionMetrics(BaseModel):
    """Aggregate statistics about a knowledge collection's indexed content."""

    total_documents: int = Field(ge=0)
    total_chunks: int = Field(ge=0)
    avg_chunk_size: float = Field(ge=0)


class NaiveRagSuggestRequest(BaseModel):
    """Request body for `POST /api/naive-rag/suggest-search-params/`."""

    model_config = ConfigDict(extra="forbid")

    knowledge_collection_id: int = Field(gt=0)
    llm_config_id: int = Field(gt=0)
    user_custom_params: dict | None = None


class GraphRagSuggestRequest(BaseModel):
    """Request body for `POST /api/graph-rag/suggest-search-params/`."""

    model_config = ConfigDict(extra="forbid")

    knowledge_collection_id: int = Field(gt=0)
    search_method: GraphSearchMethod
    llm_config_id: int = Field(gt=0)
    user_custom_params: dict | None = None


class SuggestResponse(BaseModel):
    """Response body for both suggest endpoints.

    `clamped_fields` lists token field names whose values were lowered to
    fit the LLM's safe budget. When `llm_resolution_warning` is non-null
    (litellm did not recognise the model), `clamped_fields` is typically
    empty: in untrusted-ctx mode we pass user overrides through unchanged
    and rely on the save-side MAX_TOKEN_FIELD_VALUE ceiling as the last guard.

    `recommended_search_method` is populated only by the Graph RAG suggest
    endpoint — it advises which of the four methods
    (basic/local/global_search/drift_search) is optimal for the collection's
    size, independent of the `search_method` the caller asked params for.
    Always null on the Naive endpoint (naive has no method choice).
    """

    metrics: CollectionMetrics
    resolved_llm_name: str | None = None
    llm_resolution_warning: str | None = None
    effective_llm_context_window: int = Field(gt=0)
    safe_token_budget: int = Field(gt=0)
    clamped_fields: list[str] = Field(default_factory=list)
    suggested_params: SuggestedSearchParams
    recommended_search_method: GraphSearchMethod | None = None
