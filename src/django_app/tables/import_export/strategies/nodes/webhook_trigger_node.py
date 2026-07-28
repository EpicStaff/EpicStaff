from typing import Optional

from tables.models import WebhookTriggerNode, WebhookTrigger
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.serializers.webhook_trigger_node import (
    WebhookTriggerNodeImportSerializer,
)
from tables.import_export.serializers.python_tools import PythonCodeImportSerializer
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper


class WebhookTriggerNodeStrategy(EntityImportExportStrategy):
    entity_type = EntityType.WEBHOOK_TRIGGER_NODE
    serializer_class = WebhookTriggerNodeImportSerializer

    def get_instance(self, entity_id: int) -> Optional[WebhookTriggerNode]:
        return WebhookTriggerNode.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: WebhookTriggerNode) -> dict:
        return {"id": instance.id, "graph": instance.graph_id}

    def extract_dependencies_from_instance(self, instance: WebhookTriggerNode) -> dict:
        deps = {EntityType.GRAPH: [instance.graph_id]}
        if instance.webhook_trigger_id:
            deps[EntityType.WEBHOOK_TRIGGER] = [instance.webhook_trigger_id]
        return deps

    def export_entity(self, instance: WebhookTriggerNode) -> dict:
        return self.serializer_class(instance).data

    def create_entity(
        self, data: dict, id_mapper: IDMapper, **kwargs
    ) -> WebhookTriggerNode:
        graph_id = id_mapper.get_or_none(EntityType.GRAPH, data.pop("graph", None))
        python_code_data = data.pop("python_code", None)
        old_trigger_id = data.pop("webhook_trigger", None)
        new_trigger_id = id_mapper.get_or_none(
            EntityType.WEBHOOK_TRIGGER, old_trigger_id
        )
        webhook_trigger = WebhookTrigger.objects.filter(id=new_trigger_id).first()

        python_code_serializer = PythonCodeImportSerializer(data=python_code_data)
        python_code_serializer.is_valid(raise_exception=True)
        python_code = python_code_serializer.save()

        serializer = self.serializer_class(
            data={
                **data,
                "graph": graph_id,
                "python_code_id": python_code.id,
                "webhook_trigger_id": getattr(webhook_trigger, "id", None),
            }
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save()
