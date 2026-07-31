from typing import Optional

from tables.models import KnowledgeNode
from tables.models.knowledge_models import (
    KnowledgeNodeGraphRagBasicSearchConfig,
    KnowledgeNodeGraphRagLocalSearchConfig,
    KnowledgeNodeNaiveRagSearchConfig,
)
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.serializers.knowledge_node import (
    KnowledgeNodeImportSerializer,
)
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper


class KnowledgeNodeStrategy(EntityImportExportStrategy):
    entity_type = EntityType.KNOWLEDGE_NODE
    serializer_class = KnowledgeNodeImportSerializer

    # export key -> node-bound config model. Same extension point as the bulk
    # saveable: a new graph search method adds one entry here.
    _CONFIG_MODELS = {
        "naive_search_config": KnowledgeNodeNaiveRagSearchConfig,
        "graph_basic_search_config": KnowledgeNodeGraphRagBasicSearchConfig,
        "graph_local_search_config": KnowledgeNodeGraphRagLocalSearchConfig,
    }

    def get_instance(self, entity_id: int) -> Optional[KnowledgeNode]:
        return KnowledgeNode.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: KnowledgeNode) -> dict:
        return {"id": instance.id, "graph": instance.graph_id}

    def extract_dependencies_from_instance(self, instance: KnowledgeNode) -> dict:
        return {EntityType.GRAPH: [instance.graph_id]}

    def export_entity(self, instance: KnowledgeNode) -> dict:
        return self.serializer_class(instance).data

    def create_entity(
        self, data: dict, id_mapper: IDMapper, **kwargs
    ) -> KnowledgeNode:
        graph_id = id_mapper.get_or_none(EntityType.GRAPH, data.pop("graph", None))
        # source_collection / rag_type are org-scoped knowledge entities outside
        # the flow export graph — their raw ids are preserved (same-DB round-trip).
        configs = {key: data.pop(key, None) for key in self._CONFIG_MODELS}

        serializer = self.serializer_class(data={**data, "graph": graph_id})
        serializer.is_valid(raise_exception=True)
        node = serializer.save()

        for key, model in self._CONFIG_MODELS.items():
            config_data = configs.get(key)
            if config_data:
                model.objects.create(knowledge_node=node, **config_data)

        return node
