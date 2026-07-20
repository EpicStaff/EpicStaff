from typing import Optional

from tables.models.graph_models import CodeAgentNode
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.serializers.code_agent_node import (
    CodeAgentNodeImportSerializer,
)
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper


class CodeAgentNodeStrategy(EntityImportExportStrategy):
    entity_type = EntityType.CODE_AGENT_NODE
    serializer_class = CodeAgentNodeImportSerializer

    def get_instance(self, entity_id: int) -> Optional[CodeAgentNode]:
        return CodeAgentNode.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: CodeAgentNode) -> dict:
        return {"id": instance.id, "graph": instance.graph_id}

    def extract_dependencies_from_instance(self, instance: CodeAgentNode) -> dict:
        deps = {EntityType.GRAPH: [instance.graph_id]}
        if instance.llm_config_id:
            deps[EntityType.LLM_CONFIG] = [instance.llm_config_id]
        return deps

    def export_entity(self, instance: CodeAgentNode) -> dict:
        return self.serializer_class(instance).data

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> CodeAgentNode:
        graph_id = id_mapper.get_or_none(EntityType.GRAPH, data.pop("graph", None))
        old_llm_config_id = data.pop("llm_config", None)
        data["llm_config"] = id_mapper.get_or_none(
            EntityType.LLM_CONFIG, old_llm_config_id
        )
        serializer = self.serializer_class(data={**data, "graph": graph_id})
        serializer.is_valid(raise_exception=True)
        return serializer.save()
