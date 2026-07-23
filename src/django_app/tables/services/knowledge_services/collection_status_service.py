from typing import List

from tables.models.knowledge_models import BaseRagType, SourceCollection
from src.shared.models import derive_collection_status


class CollectionStatusService:
    """
    Derives the SourceCollection-level status (CollectionStatus vocabulary:
    empty/uploading/completed/warning/failed) at read time by aggregating the
    rag_status of every RAG implementation (NaiveRag, GraphRag, ...) attached
    to the collection.

    This is the single reusable place for the collection_status mapping on
    the Django side. It calls the same `derive_collection_status` function
    the knowledge worker uses for RagIndexingProgressMessage.collection_status
    (src/knowledge/rag/naive_rag_strategy.py), so the wire contract is
    identical across both the SSE progress stream and the REST serializers.

    Deliberately NOT written back to SourceCollection.status - see
    SourceCollection.update_collection_status() for why (would race with the
    knowledge worker's own DB writes during indexing).

    Traverses `collection.documents`, `collection.rag_types`,
    `base_rag_type.naive_rags` and `base_rag_type.graph_rags` via the ORM
    cache rather than issuing new queries, so callers that
    prefetch_related() those paths (see SourceCollectionViewSet.get_queryset)
    pay no extra query cost per collection.
    """

    @staticmethod
    def get_collection_status(collection: SourceCollection) -> str:
        has_documents = len(collection.documents.all()) > 0

        rag_statuses: List[str] = []
        for base_rag_type in collection.rag_types.all():
            if base_rag_type.rag_type == BaseRagType.RagType.NAIVE:
                rag_statuses.extend(
                    naive_rag.rag_status for naive_rag in base_rag_type.naive_rags.all()
                )
            elif base_rag_type.rag_type == BaseRagType.RagType.GRAPH:
                rag_statuses.extend(
                    graph_rag.rag_status for graph_rag in base_rag_type.graph_rags.all()
                )

        return derive_collection_status(rag_statuses, has_documents)
