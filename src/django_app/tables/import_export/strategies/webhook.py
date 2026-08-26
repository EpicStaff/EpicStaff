from typing import Any, Optional

from django.db.models import Q

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

    def get_org_scope_q(self, org_id: int) -> Q:
        # WebhookTrigger is org-scoped directly via OrgScopedModel (org_id is
        # NOT NULL at the DB layer, see migration 0206_webhook_trigger_org_not_null).
        if org_id is None:
            return Q()
        return Q(org_id=org_id)

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> Any:
        org_id = kwargs.get("org_id")
        serializer = self.serializer_class(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer.save(org_id=org_id)

    def find_existing(
        self, data: dict, id_mapper: IDMapper, org_id: int = None
    ) -> Optional[Any]:
        webhook_path = data.get("path")
        existing_webhook = (
            WebhookTrigger.objects.filter(path=webhook_path)
            .filter(self.get_org_scope_q(org_id))
            .first()
        )
        return existing_webhook
