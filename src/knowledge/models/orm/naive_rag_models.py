from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Text,
    ForeignKey,
    UniqueConstraint,
    Index,
    JSON,
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from pgvector.sqlalchemy import Vector
import uuid
from datetime import datetime

from .base_models import Base


class NaiveRag(Base):
    """
    Naive RAG implementation configuration.

    Scope: Per-collection RAG configuration

    Database Structure:
    - This is a separate, independent table: tables_naiverag
    - Links to BaseRagType via ForeignKey (base_rag_type_id)
    - Stores RAG-specific configuration (embedder, status)

    Relationships:
    - Links to one BaseRagType (common metadata container)
    - Has one EmbeddingConfig (embedder)
    - Has many NaiveRagDocumentConfig (per-document configurations)

    Example:
    - BaseRagType(id=1, rag_type="naive", collection_id=10)
    - NaiveRag(id=5, base_rag_type_id=1, embedder_id=3)
    """

    __tablename__ = "tables_naiverag"

    naive_rag_id = Column(Integer, primary_key=True, autoincrement=True)

    base_rag_type_id = Column(
        Integer,
        ForeignKey("tables_baseragtype.rag_type_id"),
        nullable=False,
    )
    embedder_id = Column(
        Integer,
        ForeignKey("tables_embeddingconfig.id"),
        nullable=True,
    )

    rag_status = Column(
        String(20), default="new"
    )  # new, processing, completed, warning, failed

    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    indexed_at = Column(DateTime, nullable=True)

    # Relationships
    base_rag_type = relationship("BaseRagType")
    embedder = relationship("EmbeddingConfig")
    naive_rag_configs = relationship(
        "NaiveRagDocumentConfig",
        back_populates="naive_rag",
        cascade="all, delete-orphan",
    )

    def __str__(self):
        return f"NaiveRag {self.naive_rag_id}"


class NaiveRagDocumentConfig(Base):
    """
    Per-document RAG configuration with chunking parameters.

    Scope: Document-level chunking configuration within a NaiveRag implementation.
    Each document can have different chunking strategies within the same NaiveRag.

    Relationships:
    - Belongs to one NaiveRag
    - Belongs to one DocumentMetadata
    - Has many NaiveRagChunk (chunks generated from this configuration)
    - Has many NaiveRagEmbedding (embeddings for chunks)

    NOTE: One document can have multiple configs (one per RAG implementation)
    but only one config per (naive_rag, document) combination.
    """

    __tablename__ = "tables_naiveragdocumentconfig"

    naive_rag_document_id = Column(Integer, primary_key=True, autoincrement=True)

    naive_rag_id = Column(
        Integer,
        ForeignKey("tables_naiverag.naive_rag_id"),
        nullable=False,
    )
    document_id = Column(
        Integer,
        ForeignKey("tables_documentmetadata.document_id"),
        nullable=False,
    )

    # Chunking parameters (moved from DocumentMetadata)
    chunk_strategy = Column(
        String(20), default="token"
    )  # token, character, markdown, html, json, csv
    chunk_size = Column(
        Integer, default=1000, comment="Size of each chunk (tokens or characters)"
    )
    chunk_overlap = Column(
        Integer, default=150, comment="Overlap between consecutive chunks"
    )
    additional_params = Column(
        JSON,
        default=dict,
        comment="Strategy-specific params (e.g., separators, headers)",
    )

    status = Column(
        String(20), default="new"
    )  # new, chunking, chunked, indexing, completed, warning, failed

    created_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)

    # Relationships
    naive_rag = relationship("NaiveRag", back_populates="naive_rag_configs")
    document = relationship(
        "DocumentMetadata", back_populates="naive_rag_document_configs"
    )
    chunks = relationship(
        "NaiveRagChunk",
        back_populates="naive_rag_document_config",
        cascade="all, delete-orphan",
    )
    preview_chunks = relationship(
        "NaiveRagPreviewChunk",
        back_populates="naive_rag_document_config",
        cascade="all, delete-orphan",
    )
    embeddings = relationship(
        "NaiveRagEmbedding",
        back_populates="naive_rag_document_config",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_naiveragdocconfig_naive_rag_status", "naive_rag_id", "status"),
        Index("ix_naiveragdocconfig_document", "document_id"),
        UniqueConstraint(
            "naive_rag_id",
            "document_id",
            name="unique_document_per_naive_rag",
        ),
    )

    def __str__(self):
        return f"NaiveRagDocumentConfig {self.naive_rag_document_id}"


class NaiveRagChunk(Base):
    """
    Individual text chunk generated from a document using NaiveRag strategy.

    Scope: Chunk-level text storage
    Each chunk belongs to one NaiveRagDocumentConfig and has one embedding.

    Relationships:
    - Belongs to one NaiveRagDocumentConfig
    - Has one NaiveRagEmbedding (via OneToOne relationship)
    """

    __tablename__ = "tables_naiveragchunk"

    chunk_id = Column(Integer, primary_key=True, autoincrement=True)

    naive_rag_document_config_id = Column(
        Integer,
        ForeignKey("tables_naiveragdocumentconfig.naive_rag_document_id"),
        nullable=False,
    )

    text = Column(Text, nullable=False)
    chunk_index = Column(
        Integer, nullable=False, comment="Order of this chunk in the document"
    )
    token_count = Column(Integer, nullable=True)
    overlap_start_index = Column(Integer, nullable=True)
    overlap_end_index = Column(Integer, nullable=True)
    chunk_metadata = Column(
        "metadata",
        JSON,
        default=dict,
        comment="Chunk-specific metadata (page numbers, sections, etc.)",
    )

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    naive_rag_document_config = relationship(
        "NaiveRagDocumentConfig", back_populates="chunks"
    )
    embedding = relationship(
        "NaiveRagEmbedding",
        back_populates="chunk",
        uselist=False,  # OneToOne
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index(
            "ix_naiveragchunk_config_index",
            "naive_rag_document_config_id",
            "chunk_index",
        ),
        UniqueConstraint(
            "naive_rag_document_config_id",
            "chunk_index",
            name="unique_chunk_index_per_naive_rag_document_config",
        ),
    )

    def __str__(self):
        return f"NaiveRagChunk {self.chunk_id} (index: {self.chunk_index})"


class NaiveRagEmbedding(Base):
    """
    Vector embedding for a NaiveRag chunk.

    Scope: Embedding storage for semantic search
    Each embedding is linked to one chunk and one document config.

    Relationships:
    - Belongs to one NaiveRagDocumentConfig
    - Belongs to one NaiveRagChunk (OneToOne)

    NOTE: Vector dimensions are flexible based on embedder model.
    """

    __tablename__ = "tables_naiveragembedding"

    embedding_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    naive_rag_document_config_id = Column(
        Integer,
        ForeignKey("tables_naiveragdocumentconfig.naive_rag_document_id"),
        nullable=False,
    )
    chunk_id = Column(
        Integer,
        ForeignKey("tables_naiveragchunk.chunk_id"),
        nullable=False,
        unique=True,  # OneToOne with chunk
    )

    vector = Column(
        Vector(dim=None), nullable=True, comment="Flexible dimensions based on embedder"
    )

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    naive_rag_document_config = relationship(
        "NaiveRagDocumentConfig", back_populates="embeddings"
    )
    chunk = relationship("NaiveRagChunk", back_populates="embedding")

    __table_args__ = (
        Index("ix_naiveragembedding_config", "naive_rag_document_config_id"),
    )

    def __str__(self):
        return f"NaiveRagEmbedding {self.embedding_id}"


class NaiveRagPreviewChunk(Base):
    """
    Temporary preview chunks for testing different chunking parameters.
    """

    __tablename__ = "tables_naiveragpreviewchunk"

    preview_chunk_id = Column(Integer, primary_key=True, autoincrement=True)

    naive_rag_document_config_id = Column(
        Integer,
        ForeignKey("tables_naiveragdocumentconfig.naive_rag_document_id"),
        nullable=False,
    )

    text = Column(Text, nullable=False)
    chunk_index = Column(
        Integer, nullable=False, comment="Order of this chunk in the document"
    )
    token_count = Column(Integer, nullable=True)
    overlap_start_index = Column(Integer, nullable=True)
    overlap_end_index = Column(Integer, nullable=True)
    chunk_metadata = Column(
        "metadata",
        JSON,
        default=dict,
        comment="Chunk-specific metadata (page numbers, sections, etc.)",
    )

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    naive_rag_document_config = relationship(
        "NaiveRagDocumentConfig", back_populates="preview_chunks"
    )

    __table_args__ = (
        Index(
            "ix_naiveragpreviewchunk_config_index",
            "naive_rag_document_config_id",
            "chunk_index",
        ),
    )

    def __str__(self):
        return (
            f"NaiveRagPreviewChunk {self.preview_chunk_id} (index: {self.chunk_index})"
        )
