from typing import Optional

from tables.models import TelegramTriggerNode, WebhookTrigger
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.serializers.telegram_trigger_node import (
    TelegramTriggerNodeImportSerializer,
    TelegramTriggerNodeFieldImportSerializer,
)
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper


class TelegramTriggerNodeStrategy(EntityImportExportStrategy):
    entity_type = EntityType.TELEGRAM_TRIGGER_NODE
    serializer_class = TelegramTriggerNodeImportSerializer

    def get_instance(self, entity_id: int) -> Optional[TelegramTriggerNode]:
        return TelegramTriggerNode.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: TelegramTriggerNode) -> dict:
        return {"id": instance.id, "graph": instance.graph_id}

    def extract_dependencies_from_instance(self, instance: TelegramTriggerNode) -> dict:
        deps = {EntityType.GRAPH: [instance.graph_id]}
        if instance.webhook_trigger_id:
            deps[EntityType.WEBHOOK_TRIGGER] = [instance.webhook_trigger_id]
        return deps

    def export_entity(self, instance: TelegramTriggerNode) -> dict:
        return self.serializer_class(instance).data

    def create_entity(
        self, data: dict, id_mapper: IDMapper, **kwargs
    ) -> TelegramTriggerNode:
        graph_id = id_mapper.get_or_none(EntityType.GRAPH, data.pop("graph", None))
        fields_data = data.pop("fields", [])
        old_trigger_id = data.pop("webhook_trigger", None)
        new_trigger_id = id_mapper.get_or_none(
            EntityType.WEBHOOK_TRIGGER, old_trigger_id
        )
        webhook_trigger = WebhookTrigger.objects.filter(id=new_trigger_id).first()

        serializer = self.serializer_class(
            data={
                **data,
                "graph": graph_id,
                "webhook_trigger_id": getattr(webhook_trigger, "id", None),
            }
        )
        serializer.is_valid(raise_exception=True)
        node = serializer.save()

        fields_serializer = TelegramTriggerNodeFieldImportSerializer(
            data=fields_data, many=True
        )
        fields_serializer.is_valid(raise_exception=True)
        fields_serializer.save(telegram_trigger_node=node)

        return node
