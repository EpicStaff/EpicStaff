from typing import Any, Optional
from tables.models import WebhookTrigger
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.serializers.webhook import WebhookTriggerImportSerializer
from tables.import_export.id_mapper import IDMapper
from tables.import_export.enums import EntityType


class WebhookTriggerStrategy(EntityImportExportStrategy):
    entity_type = EntityType.WEBHOOK_TRIGGER
    serializer_class = WebhookTriggerImportSerializer

    def get_instance(self, entity_id: int) -> WebhookTrigger | None:
        return WebhookTrigger.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: WebhookTrigger) -> dict:
        return {"id": instance.id, "name": instance.path}

    def extract_dependencies_from_instance(self, instance):
        return {}

    def export_entity(self, instance: Any) -> dict:
        return self.serializer_class(instance).data

    def create_entity(self, data: dict, id_mapper: IDMapper) -> Any:
        serializer = self.serializer_class(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    def find_existing(self, data: dict, id_mapper: IDMapper) -> Optional[Any]:
        webhook_path = data.get("path")
        existing_webhook = WebhookTrigger.objects.filter(path=webhook_path).first()
        return existing_webhook
