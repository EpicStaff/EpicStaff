from tables.services.graph_bulk_save_service.factories.base import NodeSaveableFactory
from tables.services.graph_bulk_save_service.saveables import KnowledgeNodeSaveable


class KnowledgeNodeSaveableFactory(NodeSaveableFactory):
    """
    Factory for KnowledgeNode.

    preprocess_data() pops the three nested search-config blocks before the
    serializer runs (they are reverse OneToOne relations, not model fields, so
    the serializer would silently drop them). KnowledgeNodeSaveable persists them.

    Adding a new graph search method: add its payload key here and its config
    model to KnowledgeNodeSaveable._CONFIG_MODELS — nothing else changes.
    """

    _CONFIG_KEYS = (
        "naive_search_config",
        "graph_basic_search_config",
        "graph_local_search_config",
    )

    def preprocess_data(self, data: dict, payload_temp_ids: set) -> tuple[dict, dict]:
        nested_configs = {key: data.pop(key, None) for key in self._CONFIG_KEYS}
        return data, {"nested_configs": nested_configs}

    def build(self, serializer, extra: dict, instance=None):
        return KnowledgeNodeSaveable(
            serializer, extra.get("nested_configs"), instance=instance
        )
