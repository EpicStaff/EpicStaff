from sqlalchemy import (
    Column,
    Integer,
    String,
    ForeignKey,
)
from sqlalchemy.orm import relationship

from .base_models import Base
from .mixins import SoftDeleteColumnsMixin


class BaseRagType(SoftDeleteColumnsMixin, Base):
    """
    Common container for all RAG implementations.

    Purpose:
    - Stores shared metadata for all RAG types (naive, graph, etc.)
    - Links RAG implementations to their SourceCollection
    """

    __tablename__ = "tables_baseragtype"

    rag_type_id = Column(Integer, primary_key=True, autoincrement=True)
    rag_type = Column(String(30), nullable=False)  # "naive", "graph", etc.

    source_collection_id = Column(
        Integer,
        ForeignKey("tables_sourcecollection.collection_id"),
        nullable=False,
    )

    # Relationships
    source_collection = relationship("SourceCollection", back_populates="rag_types")

    # Concrete RAG implementations will add their own relationships
    # e.g., naive_rags, graph_rags, etc.

    def __str__(self):
        return f"{self.rag_type} RAG (ID: {self.rag_type_id})"
