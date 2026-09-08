from typing import Optional

from tables.exceptions import RagException
from tables.models import KnowledgeNode
from tables.models.knowledge_models import (
    KNOWLEDGE_NODE_SEARCH_CONFIG_MODELS,
    SourceCollection,
)
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.serializers.knowledge_node import (
    KnowledgeNodeImportSerializer,
)
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.services.rag_registry import resolve_rag_in_collection


class KnowledgeNodeStrategy(EntityImportExportStrategy):
    entity_type = EntityType.KNOWLEDGE_NODE
    serializer_class = KnowledgeNodeImportSerializer

    _CONFIG_MODELS = KNOWLEDGE_NODE_SEARCH_CONFIG_MODELS

    def get_instance(self, entity_id: int) -> Optional[KnowledgeNode]:
        return KnowledgeNode.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: KnowledgeNode) -> dict:
        return {"id": instance.id, "graph": instance.graph_id}

    def extract_dependencies_from_instance(self, instance: KnowledgeNode) -> dict:
        return {EntityType.GRAPH: [instance.graph_id]}

    def export_entity(self, instance: KnowledgeNode) -> dict:
        return self.serializer_class(instance).data

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> KnowledgeNode:
        graph_id = id_mapper.get_or_none(EntityType.GRAPH, data.pop("graph", None))

        configs = {key: data.pop(key, None) for key in self._CONFIG_MODELS}

        source_collection = SourceCollection.objects.filter(
            pk=data.get("source_collection"), org_id=kwargs.get("org_id")
        ).first()
        if source_collection is None:
            data["source_collection"] = None

        rag_type = data.get("rag_type")
        rag_id = data.get("rag_id")
        rag_ok = False
        if source_collection is not None and rag_type and rag_id is not None:
            try:
                resolve_rag_in_collection(rag_type, rag_id, source_collection)
                rag_ok = True
            except RagException:
                rag_ok = False
        if not rag_ok:
            data["rag_type"] = None
            data["rag_id"] = None

        serializer = self.serializer_class(data={**data, "graph": graph_id})
        serializer.is_valid(raise_exception=True)
        node = serializer.save()

        for key, model in self._CONFIG_MODELS.items():
            config_data = configs.get(key)
            if config_data:
                model.objects.create(knowledge_node=node, **config_data)

        return node
