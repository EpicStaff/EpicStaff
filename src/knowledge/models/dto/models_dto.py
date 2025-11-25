from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict


class ProviderDTO(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class EmbeddingModelDTO(BaseModel):
    id: int
    name: str
    predefined: bool
    deployment: Optional[str]
    base_url: Optional[str]
    is_visible: bool
    embedding_provider: Optional[ProviderDTO] = None

    model_config = ConfigDict(from_attributes=True)


class EmbeddingConfigDTO(BaseModel):
    id: int
    custom_name: str
    task_type: str
    api_key: Optional[str]
    is_visible: bool
    model: Optional[EmbeddingModelDTO] = None

    model_config = ConfigDict(from_attributes=True)


class DocumentContentDTO(BaseModel):
    id: int
    content: bytes

    model_config = ConfigDict(from_attributes=True)


class DocumentMetadataDTO(BaseModel):
    document_id: int
    document_hash: Optional[str]
    file_name: Optional[str]
    file_type: Optional[str]
    chunk_strategy: str
    chunk_size: int
    chunk_overlap: int
    additional_params: dict
    status: str
    document_content: Optional[DocumentContentDTO] = None
    source_collection_id: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)


class ChunkDTO(BaseModel):
    id: int
    document_id: int
    text: str

    model_config = ConfigDict(from_attributes=True)


class DocumentEmbeddingDTO(BaseModel):
    embedding_id: UUID
    created_at: datetime
    vector: Optional[list[float]] = None

    document: Optional[DocumentMetadataDTO] = None
    chunk: Optional[ChunkDTO] = None

    model_config = ConfigDict(from_attributes=True)


class SourceCollectionDTO(BaseModel):
    collection_id: int
    collection_name: Optional[str]
    user_id: str
    status: str
    created_at: datetime

    embedder: Optional[EmbeddingConfigDTO] = None
    document_metadata: List[DocumentMetadataDTO] = []
    embeddings_coll: List[DocumentEmbeddingDTO] = []

    model_config = ConfigDict(from_attributes=True)


class KnowledgeChunkDTO(BaseModel):
    chunk_order: int
    chunk_similarity: float
    chunk_text: str
    chunk_source: str = ""


class KnowledgeQueryResultDTO(BaseModel):
    uuid: str
    collection_id: int
    retrieved_chunks: int
    similarity_threshold: float
    search_limit: int
    knowledge_query: str
    chunks: List[KnowledgeChunkDTO]
    # Support backwards compatibility
    results: List[str] = []  # deprecated, use chunks instead
