class RagLookupService:
    """Finds the most relevant RAG implementation for a source collection."""

    @staticmethod
    def latest_rag(model, collection_id: int, pk_field: str):
        queryset = model.objects.filter(
            base_rag_type__source_collection_id=collection_id
        )
        completed = (
            queryset.filter(rag_status="completed").order_by(f"-{pk_field}").first()
        )
        if completed is not None:
            return completed

        return queryset.order_by(f"-{pk_field}").first()
