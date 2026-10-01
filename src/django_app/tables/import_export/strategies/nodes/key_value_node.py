from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.serializers.key_value_node import KeyValueNodeImportSerializer
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.models import KeyValueNode
from tables.services.key_value_table_service import KeyValueTableService


class KeyValueNodeStrategy(EntityImportExportStrategy):
    entity_type = EntityType.KEY_VALUE_NODE
    serializer_class = KeyValueNodeImportSerializer

    def get_instance(self, entity_id: int) -> KeyValueNode | None:
        return KeyValueNode.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: KeyValueNode) -> dict:
        return {"id": instance.id, "graph": instance.graph_id}

    def extract_dependencies_from_instance(self, instance: KeyValueNode) -> dict:
        return {EntityType.GRAPH: [instance.graph_id]}

    def export_entity(self, instance: KeyValueNode) -> dict:
        return self.serializer_class(instance).data

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> KeyValueNode:
        graph_id = id_mapper.get_or_none(EntityType.GRAPH, data.pop("graph", None))
        table_id = data.pop("key_value_table", None)
        table_name = data.pop("key_value_table_name", None)
        serializer = self.serializer_class(data={**data, "graph": graph_id})
        serializer.is_valid(raise_exception=True)
        # Node strategies receive no org kwargs; the org is the imported graph's.
        org_id = serializer.validated_data["graph"].org_id
        table = KeyValueTableService().resolve_reference(
            org_id,
            table_id,
            table_name,
            mode=serializer.validated_data.get("mode", KeyValueNode.Mode.READ),
            user=kwargs.get("user"),
        )
        return serializer.save(key_value_table=table)
