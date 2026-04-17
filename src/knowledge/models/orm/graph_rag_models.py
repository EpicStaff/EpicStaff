from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Text,
    Float,
    Boolean,
    ForeignKey,
    UniqueConstraint,
    Index,
    JSON,
)
from sqlalchemy.orm import relationship
from datetime import datetime

from .base_models import Base


class LLMModel(Base):
    """
    Available LLM model (gpt-4o, claude-3, etc.)
    Similar structure to EmbeddingModel.
    """

    __tablename__ = "tables_llmmodel"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    predefined = Column(Boolean, default=False)
    description = Column(Text, nullable=True)
    llm_provider_id = Column(Integer, ForeignKey("tables_provider.id"), nullable=True)
    base_url = Column(Text, nullable=True)
    deployment_id = Column(Text, nullable=True)
    api_version = Column(Text, nullable=True)
    is_visible = Column(Boolean, default=True)
    is_custom = Column(Boolean, default=False)

    # Relationships
    llm_provider = relationship("Provider")
    llm_configs = relationship("LLMConfig", back_populates="model")

    def __str__(self):
        return self.name


class LLMConfig(Base):
    """
    LLM configuration with API keys and generation parameters.
    Used by RAG implementations that need LLM (e.g., GraphRAG).
    """

    __tablename__ = "tables_llmconfig"

    id = Column(Integer, primary_key=True, autoincrement=True)
    custom_name = Column(Text, unique=True, nullable=False)
    model_id = Column(Integer, ForeignKey("tables_llmmodel.id"), nullable=True)

    # Generation parameters
    temperature = Column(Float, default=0.5, nullable=True)
    top_p = Column(Float, default=1.0, nullable=True)
    stop = Column(JSON, nullable=True)
    max_tokens = Column(Integer, nullable=True)
    presence_penalty = Column(Float, nullable=True)
    frequency_penalty = Column(Float, nullable=True)
    logit_bias = Column(JSON, nullable=True)
    response_format = Column(JSON, nullable=True)
    seed = Column(Integer, nullable=True)

    # API settings
    api_key = Column(Text, nullable=True)
    headers = Column(JSON, nullable=True, default=dict)
    extra_headers = Column(JSON, nullable=True, default=dict)
    timeout = Column(Float, nullable=True)

    is_visible = Column(Boolean, default=True)

    # Relationships
    model = relationship("LLMModel", back_populates="llm_configs")

    def __str__(self):
        return self.custom_name


class GraphRagIndexConfig(Base):
    """
    Unified index configuration for GraphRAG.
    Contains all settings for input, chunking, entity extraction, and clustering.

    Matches Django model: graph_rag_index_config table
    """

    __tablename__ = "graph_rag_index_config"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # --- Input Configuration ---
    file_type = Column(
        String(10),
        default="text",
        comment="Input file type to use (csv, text, json)",
    )

    # --- Chunking Configuration ---
    chunk_size = Column(
        Integer,
        default=1200,
        comment="The chunk size to use",
    )
    chunk_overlap = Column(
        Integer,
        default=100,
        comment="The chunk overlap to use",
    )
    chunk_strategy = Column(
        String(20),
        default="tokens",
        comment="The chunking strategy to use (tokens or sentence)",
    )

    # --- Entity Extraction Configuration ---
    entity_types = Column(
        JSON,
        default=lambda: ["organization", "person", "geo", "event"],
        comment="The entity extraction types to use",
    )
    max_gleanings = Column(
        Integer,
        default=1,
        comment="The maximum number of entity gleanings to use",
    )

    # --- Cluster Graph Configuration ---
    max_cluster_size = Column(
        Integer,
        default=10,
        comment="The maximum cluster size to use",
    )

    # Relationship back to GraphRag
    graph_rag = relationship("GraphRag", back_populates="index_config", uselist=False)

    def __str__(self):
        return (
            f"GraphRagIndexConfig(chunk_size={self.chunk_size}, "
            f"entity_types={len(self.entity_types) if self.entity_types else 0})"
        )


class GraphRag(Base):
    """
    Graph RAG implementation configuration.

    Matches Django model: graph_rag table

    Scope: Per-collection RAG configuration using Microsoft's GraphRAG library.
    """

    __tablename__ = "graph_rag"

    graph_rag_id = Column(Integer, primary_key=True, autoincrement=True)

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
    llm_id = Column(
        Integer,
        ForeignKey("tables_llmconfig.id"),
        nullable=True,
    )
    index_config_id = Column(
        Integer,
        ForeignKey("graph_rag_index_config.id"),
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
    llm = relationship("LLMConfig")
    index_config = relationship("GraphRagIndexConfig", back_populates="graph_rag")
    graph_rag_documents = relationship(
        "GraphRagDocument",
        back_populates="graph_rag",
        cascade="all, delete-orphan",
    )

    def __str__(self):
        return f"GraphRag {self.graph_rag_id}"


class GraphRagDocument(Base):
    """
    Link table connecting GraphRag to specific documents.

    Matches Django model: graph_rag_document table

    Purpose:
    - GraphRag can include a subset of documents from the collection
    - Allows adding/removing documents from GraphRag independently

    NOTE: Unlike NaiveRagDocumentConfig, this table does NOT have a status field.
    Document status is tracked at the DocumentMetadata level.
    """

    __tablename__ = "graph_rag_document"

    graph_rag_document_id = Column(Integer, primary_key=True, autoincrement=True)

    graph_rag_id = Column(
        Integer,
        ForeignKey("graph_rag.graph_rag_id"),
        nullable=False,
    )
    document_id = Column(
        Integer,
        ForeignKey("tables_documentmetadata.document_id"),
        nullable=False,
    )

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    graph_rag = relationship("GraphRag", back_populates="graph_rag_documents")
    document = relationship("DocumentMetadata")

    __table_args__ = (
        UniqueConstraint(
            "graph_rag_id",
            "document_id",
            name="unique_graph_rag_document",
        ),
        Index("ix_graphragdocument_graph_rag", "graph_rag_id"),
        Index("ix_graphragdocument_document", "document_id"),
    )

    def __str__(self):
        return f"GraphRagDocument({self.graph_rag_id}, {self.document_id})"
