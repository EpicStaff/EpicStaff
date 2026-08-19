from tables.serializers.knowledge_serializers import NestedSearchConfigSerializer
from tables.services.graph_bulk_save_service.factories.base import NodeSaveableFactory
from tables.services.graph_bulk_save_service.saveables import KnowledgeNodeSaveable


class KnowledgeNodeSaveableFactory(NodeSaveableFactory):
    """
    Factory for KnowledgeNode.
    """

    def preprocess_data(self, data: dict, payload_temp_ids: set) -> tuple[dict, dict]:
        raw = data.pop("search_configs", None)
        if not raw:
            return data, {"search_configs": None}

        nested = NestedSearchConfigSerializer(data=raw)
        if not nested.is_valid():
            return data, {"preprocess_errors": [{"search_configs": nested.errors}]}
        return data, {"search_configs": nested.validated_data}

    def build(self, serializer, extra: dict, instance=None):
        return KnowledgeNodeSaveable(
            serializer, extra.get("search_configs"), instance=instance
        )
