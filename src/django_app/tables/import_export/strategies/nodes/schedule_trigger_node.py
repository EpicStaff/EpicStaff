from typing import Optional

from tables.models.graph_models import ScheduleTriggerNode
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.serializers.graph import ScheduleTriggerNodeImportSerializer
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper


class ScheduleTriggerNodeStrategy(EntityImportExportStrategy):
    entity_type = EntityType.SCHEDULE_TRIGGER_NODE
    serializer_class = ScheduleTriggerNodeImportSerializer

    def get_instance(self, entity_id: int) -> Optional[ScheduleTriggerNode]:
        return ScheduleTriggerNode.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: ScheduleTriggerNode) -> dict:
        return {"id": instance.id, "graph": instance.graph_id}

    def extract_dependencies_from_instance(self, instance: ScheduleTriggerNode) -> dict:
        return {EntityType.GRAPH: [instance.graph_id]}

    def export_entity(self, instance: ScheduleTriggerNode) -> dict:
        return self.serializer_class(instance).data

    def create_entity(
        self, data: dict, id_mapper: IDMapper, **kwargs
    ) -> ScheduleTriggerNode:
        graph_id = id_mapper.get_or_none(EntityType.GRAPH, data.pop("graph", None))
        # Activation state (is_active / current_runs / next_run_date_time) is
        # reset by the serializer's create() so an imported flow never starts
        # firing on its own.
        serializer = self.serializer_class(data={**data, "graph": graph_id})
        serializer.is_valid(raise_exception=True)
        return serializer.save()
