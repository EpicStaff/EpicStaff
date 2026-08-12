from rest_framework import serializers

from tables.exceptions import KnowledgeNodeRunValidationError
from tables.services.rag_registry import resolve_rag_in_collection


class KnowledgeNodeValidator:
    """Validates a KnowledgeNode's RAG selection against its source_collection.

    Mirrors the agent path: a RAG is addressed by (source_collection, rag_type,
    rag_id) and must exist inside that collection. Lives here — not in the
    serializer — so the CRUD viewset and the bulk-save path validate identically.
    """

    def validate(self, rag_type: str | None, rag_id: int | None, source_collection):
        # rag_type alone (no concrete rag_id) is allowed: it remembers the last
        # selected RAG kind so the flow reopens on the right naive/graph tab. Only
        # a concrete selection (rag_id set) is validated against the collection.
        if rag_id is None:
            return
        if source_collection is None:
            raise serializers.ValidationError(
                {"source_collection": "Required when a RAG is selected."}
            )
        if rag_type is None:
            raise serializers.ValidationError(
                {"rag_type": "Required when rag_id is set."}
            )
        resolve_rag_in_collection(rag_type, rag_id, source_collection)

    def validate_serializer(self, serializer):
        """Validate the effective RAG selection from a serializer's validated data,
        falling back to the persisted instance for fields absent on a PATCH."""
        data = serializer.validated_data
        instance = serializer.instance
        rag_type = data.get("rag_type", getattr(instance, "rag_type", None))
        rag_id = data.get("rag_id", getattr(instance, "rag_id", None))
        source_collection = data.get(
            "source_collection", getattr(instance, "source_collection", None)
        )
        self.validate(rag_type, rag_id, source_collection)

    def validate_runnable(self, node_list) -> None:
        """Run-time completeness gate: a node must have a collection, a fully
        selected RAG, and something to search (query or a mapped input).

        Save stays permissive (empty nodes are allowed) -- this is enforced only
        before a run, so an incompletely configured node can't start a session.
        Collects every offending node and reports them together so the FE can
        highlight all of them at once."""
        invalid = {}
        for node in node_list:
            missing = []
            if node.source_collection_id is None:
                missing.append("source_collection")
            if node.rag_type is None or node.rag_id is None:
                missing.append("rag_type/rag_id")
            if not (node.query or "").strip() and not node.input_map:
                missing.append("query or input")
            if missing:
                invalid[f"{node.node_name} #{node.id}"] = missing
        if invalid:
            raise KnowledgeNodeRunValidationError(detail={"knowledge_nodes": invalid})
