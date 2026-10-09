from rest_framework.exceptions import ValidationError

from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.serializers.audit_filter_preset import (
    AuditFilterPresetEntitySerializer,
)
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.models.audit_filter_preset_models import AuditFilterPreset
from tables.services.copy_services.audit_filter_preset_copy_service import next_free_preset_name


class AuditFilterPresetStrategy(EntityImportExportStrategy):
    entity_type = EntityType.AUDIT_FILTER_PRESET
    serializer_class = AuditFilterPresetEntitySerializer

    def get_instance(self, entity_id: int):
        return AuditFilterPreset.objects.filter(id=entity_id).first()

    def extract_dependencies_from_instance(self, instance: AuditFilterPreset) -> dict:
        return {}

    def get_preview_data(self, instance: AuditFilterPreset) -> dict:
        return {
            "id": instance.id,
            "name": instance.name,
            "filter_body": instance.filter_body,
        }

    def export_entity(self, instance: AuditFilterPreset) -> dict:
        return AuditFilterPresetEntitySerializer(instance).data

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> AuditFilterPreset:
        """Always create a private preset, never reuse one.

        A name the importer already uses for one of their own presets (private or shared)
        gets the copy numbering; colleagues' names do not collide.
        """
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValidationError({"name": "This field is required."})
        # Strip like the serializer's CharField does, so the collision check sees the stored name.
        name = name.strip()
        org_id = kwargs.get("org_id")
        created_by = kwargs.get("user")

        free_name = next_free_preset_name(org_id, created_by.id, name)
        serializer = self.serializer_class(data={**data, "name": free_name})
        serializer.is_valid(raise_exception=True)
        return serializer.save(org_id=org_id, created_by=created_by)
