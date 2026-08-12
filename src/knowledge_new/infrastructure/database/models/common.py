from common.utils import utcnow
from infrastructure.database.config import BaseModel
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship


class Provider(BaseModel):
    """An LLM or embedding model provider."""

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, unique=True, nullable=False)

    embedding_models = relationship("EmbeddingModel", back_populates="embedding_provider")

    __tablename__ = "tables_provider"

    def __str__(self):
        return self.name


class EmbeddingModel(BaseModel):
    """An embedding model offered by a `Provider`."""

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    predefined = Column(Boolean, default=False)
    deployment = Column(Text, nullable=True)
    base_url = Column(Text, nullable=True)
    is_visible = Column(Boolean, default=True)
    is_custom = Column(Boolean, default=False)

    embedding_provider_id = Column(Integer, ForeignKey("tables_provider.id"), nullable=True)

    embedding_provider = relationship("Provider", back_populates="embedding_models")
    embedding_configs = relationship("EmbeddingConfig", back_populates="model")

    __tablename__ = "tables_embeddingmodel"

    def __str__(self):
        return self.name


class EmbeddingConfig(BaseModel):
    """Credentials and task type for invoking an `EmbeddingModel`."""

    id = Column(Integer, primary_key=True, autoincrement=True)
    custom_name = Column(Text, unique=True, nullable=False)
    task_type = Column(String(255), nullable=False, default="retrieval_doc")
    api_key = Column(Text, nullable=True)
    is_visible = Column(Boolean, default=True)

    model_id = Column(Integer, ForeignKey("tables_embeddingmodel.id"), nullable=True)

    model = relationship("EmbeddingModel", back_populates="embedding_configs")

    __tablename__ = "tables_embeddingconfig"

    def __str__(self):
        return self.custom_name


class SourceCollection(BaseModel):
    """A user-owned set of documents."""

    collection_id = Column(Integer, primary_key=True, autoincrement=True)
    collection_name = Column(String(255), nullable=True)
    collection_origin = Column(String(20), default="user")
    user_id = Column(String(120), default="dummy_user", nullable=True)
    status = Column(String(20), default="empty")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

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

    __tablename__ = "tables_sourcecollection"
    __table_args__ = (
        UniqueConstraint("user_id", "collection_name", name="unique_collection_name_per_user"),
    )

    def __str__(self):
        return self.collection_name or "Unnamed Collection"


class DocumentContent(BaseModel):
    """Raw bytes of an uploaded file.

    Note:
        Holds up to 12 MB.
    """

    __tablename__ = "tables_documentcontent"

    id = Column(Integer, primary_key=True, autoincrement=True)
    content = Column(LargeBinary)

    metadata_records = relationship("DocumentMetadata", back_populates="document_content")

    def __str__(self):
        return f"Content {self.id}"


class DocumentMetadata(BaseModel):
    """Descriptive metadata for an uploaded file."""

    document_id = Column(Integer, primary_key=True, autoincrement=True)
    file_name = Column(String(255), nullable=True)
    file_type = Column(String(10), nullable=True)
    file_size = Column(Integer, nullable=True, comment="Size in bytes")

    source_collection_id = Column(
        Integer, ForeignKey("tables_sourcecollection.collection_id"), nullable=True
    )
    document_content_id = Column(Integer, ForeignKey("tables_documentcontent.id"), nullable=True)

    source_collection = relationship("SourceCollection", back_populates="documents")
    document_content = relationship("DocumentContent", back_populates="metadata_records")
    naive_rag_document_configs = relationship(
        "NaiveRagDocumentConfig",
        back_populates="document",
        cascade="all, delete-orphan",
    )

    __tablename__ = "tables_documentmetadata"
    __table_args__ = (Index("ix_documentmetadata_source_collection", "source_collection_id"),)

    def __str__(self):
        return self.file_name or "Unnamed Document"


class BaseRagType(BaseModel):
    """A RAG instance attached to a `SourceCollection`."""

    rag_type_id = Column(Integer, primary_key=True, autoincrement=True)
    rag_type = Column(String(30), nullable=False)

    source_collection_id = Column(
        Integer,
        ForeignKey("tables_sourcecollection.collection_id"),
        nullable=False,
    )

    source_collection = relationship("SourceCollection", back_populates="rag_types")

    __tablename__ = "tables_baseragtype"

    def __str__(self):
        return f"{self.rag_type} RAG (ID: {self.rag_type_id})"
