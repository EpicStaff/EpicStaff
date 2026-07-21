"""HTTP-boundary DTOs for the Adaptive Context Management endpoints.

Kept separate from `shared/models/knowledge.py` (the Redis message contract)
so HTTP-layer evolution stays decoupled from the message bus. The existing
search-param models are reused as-is for `suggested_params`.
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

GraphSearchMethod = Literal["basic", "local", "global", "drift"]


class CollectionMetrics(BaseModel):
    total_documents: int = Field(ge=0)
    total_chunks: int = Field(ge=0)
    avg_chunk_size: float = Field(ge=0)


class NaiveRagSuggestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_collection_id: int = Field(gt=0)
    llm_config_id: int = Field(gt=0)
    user_custom_params: dict | None = None


class GraphRagSuggestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_collection_id: int = Field(gt=0)
    search_method: GraphSearchMethod
    llm_config_id: int = Field(gt=0)
    user_custom_params: dict | None = None


class SuggestResponse(BaseModel):
    metrics: CollectionMetrics
    resolved_llm_name: str | None = None
    llm_resolution_warning: str | None = None
    effective_llm_context_window: int = Field(gt=0)
    safe_token_budget: int = Field(gt=0)
    clamped_fields: list[str] = Field(default_factory=list)
    suggested_params: SuggestedSearchParams
    recommended_search_method: GraphSearchMethod | None = None
