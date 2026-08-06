from tables.services.graph_bulk_save_service.factories.base import NodeSaveableFactory
from tables.services.graph_bulk_save_service.saveables import KnowledgeNodeSaveable


class KnowledgeNodeSaveableFactory(NodeSaveableFactory):
    """
    Factory for KnowledgeNode.
    """

    def preprocess_data(self, data: dict, payload_temp_ids: set) -> tuple[dict, dict]:
        search_configs = data.pop("search_configs", None) or {}
        graph = search_configs.get("graph") or {}
        if graph.get("search_method"):
            data["search_method"] = graph["search_method"]
        nested_configs = {
            "naive_search_config": search_configs.get("naive"),
            "graph_basic_search_config": graph.get("basic"),
            "graph_local_search_config": graph.get("local"),
        }
        return data, {"nested_configs": nested_configs}

    def build(self, serializer, extra: dict, instance=None):
        return KnowledgeNodeSaveable(
            serializer, extra.get("nested_configs"), instance=instance
        )
