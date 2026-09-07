"""Single source of truth mapping a RAG type name to its implementation model.

Both the agent assignment path and the KnowledgeNode resolve a RAG by the same
coordinates the knowledge service searches by — (collection, impl id, rag type) —
so they share this registry. A new RAG type is one entry here.
"""

from tables.exceptions import (
    RagCollectionMismatchException,
    UnknownRagTypeException,
)
from tables.models.knowledge_models.graphrag_models import GraphRag
from tables.models.knowledge_models.naive_rag_models import NaiveRag


class RagTypeDescriptor:
    __slots__ = ("model", "id_field")

    def __init__(self, model, id_field: str):
        self.model = model
        self.id_field = id_field


RAG_TYPE_REGISTRY: dict[str, RagTypeDescriptor] = {
    "naive": RagTypeDescriptor(NaiveRag, "naive_rag_id"),
    "graph": RagTypeDescriptor(GraphRag, "graph_rag_id"),
}


def resolve_rag_in_collection(rag_type: str, rag_id: int, source_collection):
    """Return the RAG impl identified by rag_id inside source_collection.

    Raises UnknownRagTypeException for an unregistered type and
    RagCollectionMismatchException when no RAG with this id lives in the collection.
    """
    descriptor = RAG_TYPE_REGISTRY.get(rag_type)
    if descriptor is None:
        raise UnknownRagTypeException(rag_type)

    rag = (
        descriptor.model.objects.select_related("base_rag_type")
        .filter(
            **{descriptor.id_field: rag_id},
            base_rag_type__source_collection=source_collection,
        )
        .first()
    )
    if rag is None:
        raise RagCollectionMismatchException(
            rag_type,
            rag_id,
            getattr(source_collection, "collection_id", source_collection),
        )
    return rag
