from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Text,
    Boolean,
    ForeignKey,
    UniqueConstraint,
    LargeBinary,
    Index,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()


class Provider(Base):
    """
    LLM/Embedding provider
    """

    __tablename__ = "tables_provider"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, unique=True, nullable=False)

    # Relationships
    embedding_models = relationship(
        "EmbeddingModel", back_populates="embedding_provider"
    )

    def __str__(self):
        return self.name


class EmbeddingModel(Base):
    """
    Available embedding model (text-embedding-3-small, etc.)
    """

    __tablename__ = "tables_embeddingmodel"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    predefined = Column(Boolean, default=False)
    embedding_provider_id = Column(
        Integer, ForeignKey("tables_provider.id"), nullable=True
    )
    deployment = Column(Text, nullable=True)
    base_url = Column(Text, nullable=True)
    is_visible = Column(Boolean, default=True)
    is_custom = Column(Boolean, default=False)

    # Relationships
    embedding_provider = relationship("Provider", back_populates="embedding_models")
    embedding_configs = relationship("EmbeddingConfig", back_populates="model")

    def __str__(self):
        return self.name


class EmbeddingConfig(Base):
    """
    Embedding configuration with API keys and task type.
    Used by RAG implementations to generate embeddings.
    """

    __tablename__ = "tables_embeddingconfig"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_id = Column(Integer, ForeignKey("tables_embeddingmodel.id"), nullable=True)
    custom_name = Column(Text, unique=True, nullable=False)
    task_type = Column(String(255), nullable=False, default="retrieval_doc")
    api_key = Column(Text, nullable=True)
    is_visible = Column(Boolean, default=True)

    # Relationships
    model = relationship("EmbeddingModel", back_populates="embedding_configs")

    def __str__(self):
        return self.custom_name


class SourceCollection(Base):
    """
    Top-level container for documents.
    Can have multiple RAG implementations (NaiveRag, GraphRag, etc.)
    """

    __tablename__ = "tables_sourcecollection"

    collection_id = Column(Integer, primary_key=True, autoincrement=True)
    collection_name = Column(String(255), nullable=True)
    collection_origin = Column(String(20), default="user")
    user_id = Column(String(120), default="dummy_user", nullable=True)
    status = Column(String(20), default="empty")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    documents = relationship(
        "DocumentMetadata",
        back_populates="source_collection",
        cascade="all, delete-orphan",
    )
    rag_types = relationship(
        "BaseRagType",
        back_populates="source_collection",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "collection_name", name="unique_collection_name_per_user"
        ),
    )

    def __str__(self):
        return self.collection_name or "Unnamed Collection"


class DocumentContent(Base):
    """
    Binary storage for file contents (max 20MB).
    Separated from metadata for efficient querying.
    """

    __tablename__ = "tables_documentcontent"

    id = Column(Integer, primary_key=True, autoincrement=True)
    content = Column(LargeBinary, comment="Binary file content (max 20MB)")

    # Relationships
    metadata_records = relationship(
        "DocumentMetadata", back_populates="document_content"
    )

    def __str__(self):
        return f"Content {self.id}"


class DocumentMetadata(Base):
    """
    Document metadata without RAG-specific chunking parameters.
    """

    __tablename__ = "tables_documentmetadata"

    document_id = Column(Integer, primary_key=True, autoincrement=True)
    file_name = Column(String(255), nullable=True)
    file_type = Column(String(10), nullable=True)
    file_size = Column(Integer, nullable=True, comment="Size in bytes")

    # Foreign Keys
    source_collection_id = Column(
        Integer, ForeignKey("tables_sourcecollection.collection_id"), nullable=True
    )
    document_content_id = Column(
        Integer, ForeignKey("tables_documentcontent.id"), nullable=True
    )

    # Relationships
    source_collection = relationship("SourceCollection", back_populates="documents")
    document_content = relationship(
        "DocumentContent", back_populates="metadata_records"
    )
    # RAG-specific relationships will be added in respective model files
    naive_rag_document_configs = relationship(
        "NaiveRagDocumentConfig",
        back_populates="document",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_documentmetadata_source_collection", "source_collection_id"),
    )

    def __str__(self):
        return self.file_name or "Unnamed Document"
