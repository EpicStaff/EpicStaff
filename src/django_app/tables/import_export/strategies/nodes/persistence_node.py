from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.serializers.persistence_node import PersistenceNodeImportSerializer
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.models import PersistenceNode
from tables.services.persistence_table_service import PersistenceTableService


class PersistenceNodeStrategy(EntityImportExportStrategy):
    entity_type = EntityType.PERSISTENCE_NODE
    serializer_class = PersistenceNodeImportSerializer

    def get_instance(self, entity_id: int) -> PersistenceNode | None:
        return PersistenceNode.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: PersistenceNode) -> dict:
        return {"id": instance.id, "graph": instance.graph_id}

    def extract_dependencies_from_instance(self, instance: PersistenceNode) -> dict:
        return {EntityType.GRAPH: [instance.graph_id]}

    def export_entity(self, instance: PersistenceNode) -> dict:
        return self.serializer_class(instance).data

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> PersistenceNode:
        graph_id = id_mapper.get_or_none(EntityType.GRAPH, data.pop("graph", None))
        table_id = data.pop("persistence_table", None)
        table_name = data.pop("persistence_table_name", None)
        serializer = self.serializer_class(data={**data, "graph": graph_id})
        serializer.is_valid(raise_exception=True)
        # Node strategies receive no org kwargs; the org is the imported graph's.
        org_id = serializer.validated_data["graph"].org_id
        table = PersistenceTableService().resolve_reference(org_id, table_id, table_name)
        return serializer.save(persistence_table=table)
