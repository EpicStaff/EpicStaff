from typing import Optional

from tables.models import DecisionTableNode
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.serializers.decision_table_node import (
    DecisionTableNodeImportSerializer,
    ConditionGroupImportSerializer,
    ConditionImportSerializer,
)
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper


class DecisionTableNodeStrategy(EntityImportExportStrategy):
    entity_type = EntityType.DECISION_TABLE_NODE
    serializer_class = DecisionTableNodeImportSerializer

    def get_instance(self, entity_id: int) -> Optional[DecisionTableNode]:
        return DecisionTableNode.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: DecisionTableNode) -> dict:
        return {"id": instance.id, "graph": instance.graph_id}

    def extract_dependencies_from_instance(self, instance: DecisionTableNode) -> dict:
        return {EntityType.GRAPH: [instance.graph_id]}

    def export_entity(self, instance: DecisionTableNode) -> dict:
        return self.serializer_class(instance).data

    def create_entity(
        self, data: dict, id_mapper: IDMapper, **kwargs
    ) -> DecisionTableNode:
        graph_id = id_mapper.get_or_none(EntityType.GRAPH, data.pop("graph", None))
        condition_groups_data = data.pop("condition_groups", [])

        serializer = self.serializer_class(data={**data, "graph": graph_id})
        serializer.is_valid(raise_exception=True)
        node = serializer.save()

        for group_data in condition_groups_data:
            conditions_data = group_data.pop("conditions", [])
            group_data["decision_table_node_id"] = node.id

            group_serializer = ConditionGroupImportSerializer(data=group_data)
            group_serializer.is_valid(raise_exception=True)
            condition_group = group_serializer.save()

            for condition_data in conditions_data:
                condition_serializer = ConditionImportSerializer(data=condition_data)
                condition_serializer.is_valid(raise_exception=True)
                condition_serializer.save(condition_group=condition_group)

        return node
