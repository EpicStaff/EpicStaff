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


GraphSearchParams = Annotated[
    Union[GraphRagBasicSearchParams, GraphRagLocalSearchParams],
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


# Collection status wire-contract vocabulary.
# Mirrors Django's SourceCollection.SourceCollectionStatus TextChoices values
# (src/django_app/tables/models/knowledge_models/collection_models.py).
# Kept here as plain strings (not an importable Django enum) so this module
# stays framework-agnostic and usable from both django_app and the knowledge
# worker.
COLLECTION_STATUS_EMPTY = "empty"
COLLECTION_STATUS_UPLOADING = "uploading"
COLLECTION_STATUS_COMPLETED = "completed"
COLLECTION_STATUS_WARNING = "warning"
COLLECTION_STATUS_FAILED = "failed"

# rag_status values (NaiveRag/GraphRag) that mean "still in flight".
# Includes "chunked" because the knowledge worker's document-status
# aggregation can currently surface it as an intermediate NaiveRag-level
# rag_status (see NaiveRAGStrategy.update_naive_rag_status).
_RAG_STATUSES_IN_PROGRESS = {"new", "processing", "chunked", "indexing", "chunking"}


def derive_collection_status(rag_statuses: list[str], has_documents: bool) -> str:
    """
    Derive the SourceCollection-level status from the rag_status of every RAG
    implementation (NaiveRag, GraphRag, ...) attached to the collection.

    This is the single source of truth for the collection_status wire
    contract. It is consumed by:
    - The Django REST serializers (SourceCollectionListSerializer /
      SourceCollectionDetailSerializer), via
      tables.services.knowledge_services.collection_status_service.CollectionStatusService.
    - The knowledge worker's SSE progress events
      (RagIndexingProgressMessage.collection_status), via NaiveRAGStrategy.

    Both call sites must feed it the same rag_status vocabulary so the wire
    contract stays identical across layers.

    Mapping:
    - no documents -> empty
    - any RAG still new/processing/chunked/indexing/chunking -> uploading
    - all RAGs completed -> completed
    - all RAGs failed -> failed
    - mixed completed/failed, or any explicit warning -> warning
    """
    if not has_documents:
        return COLLECTION_STATUS_EMPTY

    statuses = set(rag_statuses)

    if not statuses:
        # Has documents, but no RAG configuration has been created yet.
        return COLLECTION_STATUS_UPLOADING

    if statuses & _RAG_STATUSES_IN_PROGRESS:
        return COLLECTION_STATUS_UPLOADING

    if statuses == {"completed"}:
        return COLLECTION_STATUS_COMPLETED

    if statuses == {"failed"}:
        return COLLECTION_STATUS_FAILED

    # Remaining terminal combinations: mixed completed/failed, or any
    # explicit warning.
    return COLLECTION_STATUS_WARNING


class RagIndexingProgressMessage(BaseModel):
    """
    Progress event published by the knowledge worker while indexing a RAG
    implementation (chunking + embedding), streamed to the frontend via the
    Django SSE endpoint `source-collections/subscribe/<collection_id>/`.

    Published on channel `knowledge:indexing:progress`.
    """

    collection_id: int
    rag_id: int  # ID of specific RAG implementation (naive_rag_id, graph_rag_id, etc.)
    rag_type: str
    document_config_id: int | None = None
    doc_status: str | None = None  # per-document rag-style status, if applicable
    done: int = 0
    total: int = 0
    collection_status: (
        str  # CollectionStatus vocabulary value, see derive_collection_status
    )
    error: str | None = None

    model_config = ConfigDict(from_attributes=True)
