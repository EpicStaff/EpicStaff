from typing import Any

from django.db.models import Q

from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.serializers.webhook import WebhookTriggerImportSerializer
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.models import WebhookTrigger
from tables.services.webhook_trigger_service import (
    find_available_path,
    organization_suffixed_path,
)


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
        # find_existing already reused this org's trigger under the path or its
        # org-suffixed rename, so a path that is still taken belongs to another
        # org and cannot be shared.
        data = {**data, "path": find_available_path(data.get("path"), org_id)}
        serializer = self.serializer_class(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer.save(org_id=org_id)

    def find_existing(
        self, data: dict, id_mapper: IDMapper, org_id: int | None = None
    ) -> Any | None:
        """Reuse the importing org's trigger for this path, if it has one.

        The exact path wins. Otherwise the org may hold the trigger an earlier
        import created under `-org<org_id>` because another org had the path;
        reusing it keeps re-imports from minting `-org<org_id>-2`, `-3`, ...
        Only triggers owned by the importing org are ever returned.
        """
        webhook_path = data.get("path")
        org_triggers = WebhookTrigger.objects.filter(self.get_org_scope_q(org_id))
        existing_webhook = org_triggers.filter(path=webhook_path).first()
        if existing_webhook is not None or org_id is None or not webhook_path:
            return existing_webhook
        return org_triggers.filter(path=organization_suffixed_path(webhook_path, org_id)).first()
