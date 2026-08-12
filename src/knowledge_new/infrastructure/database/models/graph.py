from common.utils import utcnow
from infrastructure.database.config import BaseModel
from sqlalchemy import (
    ARRAY,
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship


class LLMModel(BaseModel):
    """An LLM offered by a `Provider`."""

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    predefined = Column(Boolean, default=False)
    description = Column(Text, nullable=True)
    base_url = Column(Text, nullable=True)
    deployment_id = Column(Text, nullable=True)
    api_version = Column(Text, nullable=True)
    is_visible = Column(Boolean, default=True)
    is_custom = Column(Boolean, default=False)

    llm_provider_id = Column(Integer, ForeignKey("tables_provider.id"), nullable=True)

    llm_provider = relationship("Provider")
    llm_configs = relationship("LLMConfig", back_populates="model")

    __tablename__ = "tables_llmmodel"

    def __str__(self):
        return self.name


class LLMConfig(BaseModel):
    """Generation parameters and credentials for invoking an `LLMModel`."""

    id = Column(Integer, primary_key=True, autoincrement=True)
    custom_name = Column(Text, unique=True, nullable=False)
    temperature = Column(Float, default=0.5, nullable=True)
    top_p = Column(Float, default=1.0, nullable=True)
    stop = Column(JSON, nullable=True)
    max_tokens = Column(Integer, nullable=True)
    presence_penalty = Column(Float, nullable=True)
    frequency_penalty = Column(Float, nullable=True)
    logit_bias = Column(JSON, nullable=True)
    response_format = Column(JSON, nullable=True)
    seed = Column(Integer, nullable=True)
    api_key = Column(Text, nullable=True)
    headers = Column(JSON, nullable=True, default=dict)
    extra_headers = Column(JSON, nullable=True, default=dict)
    timeout = Column(Float, nullable=True)
    is_visible = Column(Boolean, default=True)

    model_id = Column(Integer, ForeignKey("tables_llmmodel.id"), nullable=True)

    model = relationship("LLMModel", back_populates="llm_configs")

    __tablename__ = "tables_llmconfig"

    def __str__(self):
        return self.custom_name


class GraphRagIndexConfig(BaseModel):
    """Indexing parameters for a `GraphRag`."""

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_type = Column(String(10), default="text")
    chunk_size = Column(Integer, default=1200)
    chunk_overlap = Column(Integer, default=100)
    chunk_strategy = Column(String(20), default="tokens")
    entity_types = Column(JSON, default=lambda: ["organization", "person", "geo", "event"])
    max_gleanings = Column(Integer, default=1)
    max_cluster_size = Column(Integer, default=10)

    graph_rag = relationship("GraphRag", back_populates="index_config", uselist=False)

    __tablename__ = "graph_rag_index_config"

    def __str__(self):
        return (
            f"GraphRagIndexConfig(chunk_size={self.chunk_size}, "
            f"entity_types={len(self.entity_types) if self.entity_types else 0})"
        )


class GraphRag(BaseModel):
    """A GraphRAG build over a collection."""

    graph_rag_id = Column(Integer, primary_key=True, autoincrement=True)
    rag_status = Column(String(20), default="new")
    error_message = Column(Text, nullable=True)
    outdated_reasons = Column(JSON, nullable=False, default=dict)
    indexing_document_config_ids = Column(ARRAY(Integer), nullable=False, server_default="{}")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    indexed_at = Column(DateTime, nullable=True)

    base_rag_type_id = Column(Integer, ForeignKey("tables_baseragtype.rag_type_id"), nullable=False)
    embedder_id = Column(Integer, ForeignKey("tables_embeddingconfig.id"), nullable=True)
    llm_id = Column(Integer, ForeignKey("tables_llmconfig.id"), nullable=True)
    index_config_id = Column(Integer, ForeignKey("graph_rag_index_config.id"), nullable=True)

    base_rag_type = relationship("BaseRagType")
    embedder = relationship("EmbeddingConfig")
    llm = relationship("LLMConfig")
    index_config = relationship("GraphRagIndexConfig", back_populates="graph_rag")
    graph_rag_documents = relationship(
        "GraphRagDocument",
        back_populates="graph_rag",
        cascade="all, delete-orphan",
    )

    __tablename__ = "graph_rag"

    def __str__(self):
        return f"GraphRag {self.graph_rag_id}"


class GraphRagDocument(BaseModel):
    """A document included in a `GraphRag` build."""

    graph_rag_document_id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=utcnow)
    status = Column(String, default="new")

    graph_rag_id = Column(Integer, ForeignKey("graph_rag.graph_rag_id"), nullable=False)
    document_id = Column(Integer, ForeignKey("tables_documentmetadata.document_id"), nullable=False)

    graph_rag = relationship("GraphRag", back_populates="graph_rag_documents")
    document = relationship("DocumentMetadata")

    __tablename__ = "graph_rag_document"
    __table_args__ = (
        UniqueConstraint("graph_rag_id", "document_id", name="unique_graph_rag_document"),
        Index("ix_graphragdocument_graph_rag", "graph_rag_id"),
        Index("ix_graphragdocument_document", "document_id"),
    )

    def __str__(self):
        return f"GraphRagDocument({self.graph_rag_id}, {self.document_id})"
