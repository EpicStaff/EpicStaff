from typing import Annotated, Any, Literal

from pydantic import Field, field_serializer
from src.shared.enums.knowledge_new import (
    ChunkStrategyEnum,
    GraphSearchMethodEnum,
    RAGStrategy
)
from src.shared.models.base import ValueObject

__all__ = [
    "CancelRequest",
    "FoundChunk",
    "GraphBasicSearchConfig",
    "GraphDriftSearchConfig",
    "GraphGlobalSearchConfig",
    "GraphLocalSearchConfig",
    "GraphSearchConfig",
    "IndexRequest",
    "NaiveSearchConfig",
    "PrechunkRequest",
    "PrechunkResponse",
    "PreviewChunk",
    "SearchConfig",
    "SearchRequest",
    "SearchResponse",
]


class PreviewChunk(ValueObject):
    """A chunk of text produced before embedding."""

    text: str
    token_count: int | None = None
    overlap_start: int | None = None
    overlap_end: int | None = None


class FoundChunk(ValueObject):
    """A chunk returned from a search, with its ranking metadata."""

    order: int
    similarity: float
    text: str
    source: str = ""


class NaiveSearchConfig(ValueObject):
    """Configuration for naive vector-similarity search."""

    rag_strategy: Literal[RAGStrategy.NAIVE] = RAGStrategy.NAIVE
    search_limit: int = 3
    similarity_threshold: float = 0.2


class GraphBasicSearchConfig(ValueObject):
    rag_strategy: Literal[RAGStrategy.GRAPH] = RAGStrategy.GRAPH
    method: Literal[GraphSearchMethodEnum.BASIC] = GraphSearchMethodEnum.BASIC
    prompt: str | None = Field(
        description="The basic search prompt to use.",
        default=None,
    )
    k: int = Field(
        description="The number of text units to include in search context.",
        default=10,
    )
    max_context_tokens: int = Field(
        description="The maximum tokens.",
        default=12_000,
    )


class GraphLocalSearchConfig(ValueObject):
    rag_strategy: Literal[RAGStrategy.GRAPH] = RAGStrategy.GRAPH
    method: Literal[GraphSearchMethodEnum.LOCAL] = GraphSearchMethodEnum.LOCAL
    prompt: str | None = Field(
        description="The local search prompt to use.",
        default=None,
    )
    text_unit_prop: float = Field(
        description="The text unit proportion.",
        default=0.5,
    )
    community_prop: float = Field(
        description="The community proportion.",
        default=0.15,
    )
    conversation_history_max_turns: int = Field(
        description="The conversation history maximum turns.",
        default=5,
    )
    top_k_entities: int = Field(
        description="The top k mapped entities.",
        default=10,
    )
    top_k_relationships: int = Field(
        description="The top k mapped relations.",
        default=10,
    )
    max_context_tokens: int = Field(
        description="The maximum tokens.",
        default=12_000,
    )


class GraphGlobalSearchConfig(ValueObject):
    rag_strategy: Literal[RAGStrategy.GRAPH] = RAGStrategy.GRAPH
    method: Literal[GraphSearchMethodEnum.GLOBAL] = GraphSearchMethodEnum.GLOBAL
    map_prompt: str | None = Field(
        description="The global search mapper prompt to use.",
        default=None,
    )
    reduce_prompt: str | None = Field(
        description="The global search reducer to use.",
        default=None,
    )
    knowledge_prompt: str | None = Field(
        description="The global search general prompt to use.",
        default=None,
    )
    max_context_tokens: int = Field(
        description="The maximum context size in tokens.",
        default=12_000,
    )
    data_max_tokens: int = Field(
        description="The data llm maximum tokens.",
        default=12_000,
    )
    map_max_length: int = Field(
        description="The map llm maximum response length in words.",
        default=1000,
    )
    reduce_max_length: int = Field(
        description="The reduce llm maximum response length in words.",
        default=2000,
    )
    dynamic_search_threshold: int = Field(
        description="Rating threshold in include a community report",
        default=1,
    )
    dynamic_search_keep_parent: bool = Field(
        description="Keep parent community if any of the child communities are relevant",
        default=False,
    )
    dynamic_search_num_repeats: int = Field(
        description="Number of times to rate the same community report",
        default=1,
    )
    dynamic_search_use_summary: bool = Field(
        description="Use community summary instead of full_context",
        default=False,
    )
    dynamic_search_max_level: int = Field(
        description="The maximum level of community hierarchy to consider if none of the processed communities are relevant",
        default=2,
    )


class GraphDriftSearchConfig(ValueObject):
    rag_strategy: Literal[RAGStrategy.GRAPH] = RAGStrategy.GRAPH
    method: Literal[GraphSearchMethodEnum.DRIFT] = GraphSearchMethodEnum.DRIFT
    prompt: str | None = Field(
        description="The drift search prompt to use.",
        default=None,
    )
    reduce_prompt: str | None = Field(
        description="The drift search reduce prompt to use.",
        default=None,
    )
    data_max_tokens: int = Field(
        description="The data llm maximum tokens.",
        default=12_000,
    )
    reduce_max_tokens: int | None = Field(
        description="The reduce llm maximum tokens response to produce.",
        default=None,
    )
    reduce_temperature: float = Field(
        description="The temperature to use for token generation in reduce.",
        default=0,
    )
    reduce_max_completion_tokens: int | None = Field(
        description="The reduce llm maximum tokens response to produce.",
        default=None,
    )
    concurrency: int = Field(
        description="The number of concurrent requests.",
        default=32,
    )
    drift_k_followups: int = Field(
        description="The number of top global results to retrieve.",
        default=20,
    )
    primer_folds: int = Field(
        description="The number of folds for search priming.",
        default=5,
    )
    primer_llm_max_tokens: int = Field(
        description="The maximum number of tokens for the LLM in primer.",
        default=12_000,
    )
    n_depth: int = Field(
        description="The number of drift search steps to take.",
        default=3,
    )
    local_search_text_unit_prop: float = Field(
        description="The proportion of search dedicated to text units.",
        default=0.9,
    )
    local_search_community_prop: float = Field(
        description="The proportion of search dedicated to community properties.",
        default=0.1,
    )
    local_search_top_k_mapped_entities: int = Field(
        description="The number of top K entities to map during local search.",
        default=10,
    )
    local_search_top_k_relationships: int = Field(
        description="The number of top K relationships to map during local search.",
        default=10,
    )
    local_search_max_data_tokens: int = Field(
        description="The maximum context size in tokens for local search.",
        default=12_000,
    )
    local_search_temperature: float = Field(
        description="The temperature to use for token generation in local search.",
        default=0,
    )
    local_search_top_p: float = Field(
        description="The top-p value to use for token generation in local search.",
        default=1,
    )
    local_search_n: int = Field(
        description="The number of completions to generate in local search.",
        default=1,
    )
    local_search_llm_max_gen_tokens: int | None = Field(
        description="The maximum number of generated tokens for the LLM in local search.",
        default=None,
    )
    local_search_llm_max_gen_completion_tokens: int | None = Field(
        description="The maximum number of generated tokens for the LLM in local search.",
        default=None,
    )


GraphSearchConfig = Annotated[
    GraphBasicSearchConfig
    | GraphLocalSearchConfig
    | GraphGlobalSearchConfig
    | GraphDriftSearchConfig,
    Field(discriminator="method"),
]

SearchConfig = Annotated[GraphSearchConfig | NaiveSearchConfig, Field(discriminator="rag_strategy")]


class ChunkingConfig(ValueObject):
    """Parameters controlling how a document is chunked."""

    chunk_strategy: ChunkStrategyEnum
    chunk_size: int
    chunk_overlap: int
    extra: dict = Field(default_factory=dict)


class PrechunkRequest(ValueObject):
    """Request to pre-chunk a document for a RAG collection."""

    rag_strategy: RAGStrategy
    rag_id: int
    document_id: int
    chunk_strategy: str
    chunk_size: int
    chunk_overlap: int
    extra: dict = Field(default_factory=dict)


class PrechunkResponse(ValueObject):
    """Preview chunks produced for a `PrechunkRequest`."""

    request: PrechunkRequest
    chunks: list[PreviewChunk]


class IndexRequest(ValueObject):
    """Request to index a RAG collection's documents."""

    rag_id: int
    rag_strategy: RAGStrategy
    document_ids: frozenset[int]

    @field_serializer("document_ids")
    def _serialize_document_ids(self, value: frozenset[int]) -> list[int]:
        return list(value)


class SearchRequest(ValueObject):
    """Request to search a RAG collection."""

    rag_id: int
    query: str
    search_config: SearchConfig


class SearchResponse(ValueObject):
    """Chunks matched for a `SearchRequest`."""

    request: SearchRequest
    result: list[FoundChunk] | str


class CancelRequest(ValueObject):
    target_request: dict[str, Any]
