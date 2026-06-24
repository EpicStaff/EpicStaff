from pydantic import BaseModel
from typing import Annotated, Literal, Union, List
from pydantic import Field, ConfigDict


# RAG Search Configuration Models
class BaseRagSearchConfig(BaseModel):
    """Base class for RAG-specific search parameters."""

    rag_type: str  # Discriminator field for polymorphism

    model_config = ConfigDict(from_attributes=True)


class NaiveRagSearchConfig(BaseRagSearchConfig):
    """Search parameters specific to naive RAG implementation."""

    rag_type: Literal["naive"] = "naive"
    search_limit: int = 3
    similarity_threshold: float = 0.2


class GraphRagBasicSearchParams(BaseModel):
    search_method: Literal["basic"] = "basic"
    prompt: str | None = None
    k: int = 10
    max_context_tokens: int = 12000


class GraphRagLocalSearchParams(BaseModel):
    search_method: Literal["local"] = "local"
    prompt: str | None = None
    text_unit_prop: float = 0.5
    community_prop: float = 0.15
    conversation_history_max_turns: int = 5
    top_k_entities: int = 10
    top_k_relationships: int = 10
    max_context_tokens: int = 12000
    community_level: int = 2


class GraphRagGlobalSearchParams(BaseModel):
    search_method: Literal["global_search"] = "global_search"
    dynamic_community_selection: bool = False
    map_prompt: str | None = None
    reduce_prompt: str | None = None
    knowledge_prompt: str | None = None
    max_context_tokens: int = 12000
    data_max_tokens: int = 12000
    map_max_length: int = 1000
    reduce_max_length: int = 2000
    dynamic_search_threshold: int = 1
    dynamic_search_keep_parent: bool = False
    dynamic_search_num_repeats: int = 1
    dynamic_search_use_summary: bool = False
    dynamic_search_max_level: int = 2


class GraphRagDriftSearchParams(BaseModel):
    search_method: Literal["drift_search"] = "drift_search"
    # Prompts
    prompt: str | None = None
    reduce_prompt: str | None = None
    # Token configuration
    data_max_tokens: int = 12000
    reduce_max_tokens: int | None = None
    reduce_max_completion_tokens: int | None = None
    primer_llm_max_tokens: int = 12000
    local_search_max_data_tokens: int = 12000
    local_search_llm_max_gen_tokens: int | None = None
    local_search_llm_max_gen_completion_tokens: int | None = None
    # Search behavior
    concurrency: int = 32
    drift_k_followups: int = 20
    primer_folds: int = 5
    n_depth: int = 3
    community_level: int = 2
    # Local search tuning
    local_search_text_unit_prop: float = 0.9
    local_search_community_prop: float = 0.1
    local_search_top_k_mapped_entities: int = 10
    local_search_top_k_relationships: int = 10
    # LLM generation
    reduce_temperature: float = 0.0
    local_search_temperature: float = 0.0
    local_search_top_p: float = 1.0
    local_search_n: int = 1


GraphSearchParams = Annotated[
    Union[
        GraphRagBasicSearchParams,
        GraphRagLocalSearchParams,
        GraphRagGlobalSearchParams,
        GraphRagDriftSearchParams,
    ],
    Field(discriminator="search_method"),
]


class GraphRagSearchConfig(BaseRagSearchConfig):
    """Search parameters specific to graph RAG implementation"""

    rag_type: Literal["graph"] = "graph"
    search_params: GraphSearchParams


RagSearchConfig = Annotated[
    Union[NaiveRagSearchConfig, GraphRagSearchConfig],
    Field(discriminator="rag_type"),
]


class BaseKnowledgeSearchMessage(BaseModel):
    """
    Base message for searching in a RAG implementation.

    Uses discriminated union for rag_search_config to automatically
    handle different RAG types (naive, graph, etc.) during serialization.
    """

    collection_id: int
    rag_id: int  # ID of specific RAG implementation (naive_rag_id, graph_rag_id, etc.)
    rag_type: Literal["naive", "graph"]  # Type of RAG ("naive", "graph", etc.)
    uuid: str
    query: str
    rag_search_config: (
        RagSearchConfig  # Discriminated union automatically handles subtypes
    )

    model_config = ConfigDict(from_attributes=True)


class KnowledgeChunkResponse(BaseModel):
    chunk_order: int
    chunk_similarity: float
    chunk_text: str
    chunk_source: str = ""

    model_config = ConfigDict(from_attributes=True)


class BaseKnowledgeSearchMessageResponse(BaseModel):
    rag_id: int  # ID of specific RAG implementation (naive_rag_id, graph_rag_id, etc.)
    rag_type: Literal["naive", "graph"]
    collection_id: int
    uuid: str
    retrieved_chunks: int
    query: str
    chunks: List[KnowledgeChunkResponse]
    rag_search_config: RagSearchConfig
    # Support backwards compatibility
    results: List[str] = []  # deprecated, use chunks instead
    token_usage: dict = {}

    model_config = ConfigDict(from_attributes=True)


class KnowledgeSearchMessage(BaseModel):
    collection_id: int
    uuid: str
    query: str
    search_limit: int | None
    similarity_threshold: float | None


class ProcessRagIndexingMessage(BaseModel):
    """
    Message for triggering RAG indexing (chunking + embedding) for a specific RAG implementation.

    Fields:
    - rag_id: ID of the specific RAG implementation (naive_rag_id for NaiveRag, etc.)
    - rag_type: Type of RAG ("naive", "graph", etc.)
    - collection_id: Source collection ID (for logging)
    """

    rag_id: int
    rag_type: Literal["naive", "graph"]
    collection_id: int


class ChunkDocumentMessage(BaseModel):
    chunking_job_id: str  # UUID
    rag_type: Literal["naive", "graph"]
    document_config_id: int


class ChunkDocumentMessageResponse(BaseModel):
    chunking_job_id: str  # UUID
    rag_type: Literal["naive", "graph"]
    document_config_id: int
    status: str  # "completed", "failed", "cancelled"
    chunk_count: int | None = None
    message: str | None = None
    elapsed_time: float | None = None
