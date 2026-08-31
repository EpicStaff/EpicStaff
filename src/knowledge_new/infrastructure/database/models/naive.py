import uuid

from common.utils import utcnow
from domain.enums import DocumentErrorCode
from infrastructure.database.config import BaseModel
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import relationship


class NaiveRag(BaseModel):
    """A naive vector-similarity RAG build over a collection."""

    naive_rag_id = Column(Integer, primary_key=True, autoincrement=True)
    rag_status = Column(String(20), default="new")
    error_message = Column(Text, nullable=True)
    outdated_reasons = Column(JSON, nullable=False, default=dict)
    indexing_document_config_ids = Column(ARRAY(Integer), nullable=False, server_default="{}")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    indexed_at = Column(DateTime, nullable=True)

    base_rag_type_id = Column(Integer, ForeignKey("tables_baseragtype.rag_type_id"), nullable=False)
    embedder_id = Column(Integer, ForeignKey("tables_embeddingconfig.id"), nullable=True)

    base_rag_type = relationship("BaseRagType")
    embedder = relationship("EmbeddingConfig")
    naive_rag_configs = relationship(
        "NaiveRagDocumentConfig",
        back_populates="naive_rag",
        cascade="all, delete-orphan",
    )

    __tablename__ = "tables_naiverag"

    def __str__(self):
        return f"NaiveRag {self.naive_rag_id}"


class NaiveRagDocumentConfig(BaseModel):
    """Chunking parameters for one document within a `NaiveRag`."""

    naive_rag_document_id = Column(Integer, primary_key=True, autoincrement=True)
    chunk_strategy = Column(String(20), default="token")
    chunk_size = Column(Integer, default=1000)
    chunk_overlap = Column(Integer, default=150)
    additional_params = Column(JSON, default=dict)
    status = Column(String(20), default="new")
    created_at = Column(DateTime, default=utcnow)
    completed_at = Column(
        "processed_at", DateTime, nullable=True
    )  # need to change this name in django models

    naive_rag_id = Column(Integer, ForeignKey("tables_naiverag.naive_rag_id"), nullable=False)
    document_id = Column(Integer, ForeignKey("tables_documentmetadata.document_id"), nullable=False)
    error_message = Column(Text, nullable=True)
    error_code = Column(String(32), nullable=False, default=DocumentErrorCode.NONE)
    failed_at = Column(DateTime, nullable=True)
    indexed_chunk_strategy = Column(String(20), nullable=True)
    indexed_chunk_size = Column(Integer, nullable=True)
    indexed_chunk_overlap = Column(Integer, nullable=True)
    indexed_additional_params = Column(JSON, nullable=True)

    naive_rag = relationship("NaiveRag", back_populates="naive_rag_configs")
    document = relationship("DocumentMetadata", back_populates="naive_rag_document_configs")
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

    __tablename__ = "tables_naiveragdocumentconfig"
    __table_args__ = (
        Index("ix_naiveragdocconfig_naive_rag_status", "naive_rag_id", "status"),
        Index("ix_naiveragdocconfig_document", "document_id"),
        UniqueConstraint("naive_rag_id", "document_id", name="unique_document_per_naive_rag"),
    )

    def __str__(self):
        return f"NaiveRagDocumentConfig {self.naive_rag_document_id}"


class NaiveRagChunk(BaseModel):
    """A stored chunk of a document's text."""

    chunk_id = Column(Integer, primary_key=True, autoincrement=True)
    text = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    token_count = Column(Integer, nullable=True)
    overlap_start_index = Column(Integer, nullable=True)
    overlap_end_index = Column(Integer, nullable=True)
    chunk_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    naive_rag_document_config_id = Column(
        Integer,
        ForeignKey("tables_naiveragdocumentconfig.naive_rag_document_id"),
        nullable=False,
    )

    naive_rag_document_config = relationship("NaiveRagDocumentConfig", back_populates="chunks")
    embedding = relationship(
        "NaiveRagEmbedding",
        back_populates="chunk",
        uselist=False,  # OneToOne
        cascade="all, delete-orphan",
    )

    __tablename__ = "tables_naiveragchunk"
    __table_args__ = (
        Index("ix_naiveragchunk_config_index", "naive_rag_document_config_id", "chunk_index"),
        UniqueConstraint(
            "naive_rag_document_config_id",
            "chunk_index",
            name="unique_chunk_index_per_naive_rag_document_config",
        ),
    )

    def __str__(self):
        return f"NaiveRagChunk {self.chunk_id} (index: {self.chunk_index})"


class NaiveRagEmbedding(BaseModel):
    """The embedding vector of a `NaiveRagChunk`."""

    embedding_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vector = Column(Vector(dim=None), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    naive_rag_document_config_id = Column(
        Integer,
        ForeignKey("tables_naiveragdocumentconfig.naive_rag_document_id"),
        nullable=False,
    )
    chunk_id = Column(
        Integer,
        ForeignKey("tables_naiveragchunk.chunk_id"),
        nullable=False,
        unique=True,  # OneToOne
    )

    naive_rag_document_config = relationship("NaiveRagDocumentConfig", back_populates="embeddings")
    chunk = relationship("NaiveRagChunk", back_populates="embedding")

    __tablename__ = "tables_naiveragembedding"
    __table_args__ = (Index("ix_naiveragembedding_config", "naive_rag_document_config_id"),)

    def __str__(self):
        return f"NaiveRagEmbedding {self.embedding_id}"


class NaiveRagPreviewChunk(BaseModel):
    """A provisional chunk for previewing chunking parameters."""

    preview_chunk_id = Column(Integer, primary_key=True, autoincrement=True)
    text = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    token_count = Column(Integer, nullable=True)
    overlap_start_index = Column(Integer, nullable=True)
    overlap_end_index = Column(Integer, nullable=True)
    chunk_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=utcnow)

    naive_rag_document_config_id = Column(
        Integer,
        ForeignKey("tables_naiveragdocumentconfig.naive_rag_document_id"),
        nullable=False,
    )

    naive_rag_document_config = relationship(
        "NaiveRagDocumentConfig",
        back_populates="preview_chunks",
    )

    __tablename__ = "tables_naiveragpreviewchunk"
    __table_args__ = (
        Index(
            "ix_naiveragpreviewchunk_config_index",
            "naive_rag_document_config_id",
            "chunk_index",
        ),
    )

    def __str__(self):
        return f"NaiveRagPreviewChunk {self.preview_chunk_id} (index: {self.chunk_index})"
