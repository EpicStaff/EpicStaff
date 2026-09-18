from typing import Optional

from tables.models import SubGraphNode
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.serializers.subgraph_node import SubgraphNodeImportSerializer
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper


class SubgraphNodeStrategy(EntityImportExportStrategy):
    entity_type = EntityType.SUBGRAPH_NODE
    serializer_class = SubgraphNodeImportSerializer

    def get_instance(self, entity_id: int) -> Optional[SubGraphNode]:
        return SubGraphNode.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: SubGraphNode) -> dict:
        return {"id": instance.id, "graph": instance.graph_id}

    def extract_dependencies_from_instance(self, instance: SubGraphNode) -> dict:
        deps = {EntityType.GRAPH: [instance.graph_id]}
        if instance.subgraph_id:
            deps[EntityType.GRAPH] = list({instance.graph_id, instance.subgraph_id})
        return deps

    def export_entity(self, instance: SubGraphNode) -> dict:
        return self.serializer_class(instance).data

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> SubGraphNode:
        graph_id = id_mapper.get_or_none(EntityType.GRAPH, data.pop("graph", None))
        subgraph_id = id_mapper.get_or_none(
            EntityType.GRAPH, data.pop("subgraph", None)
        )
        serializer = self.serializer_class(
            data={**data, "graph": graph_id, "subgraph": subgraph_id}
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save()
