from django.db.models import Q
from rest_framework.exceptions import ValidationError

from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.schemas import ImportSettings
from tables.import_export.serializers.audit_filter_preset import (
    AuditFilterPresetEntitySerializer,
)
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.models.audit_filter_preset_models import AuditFilterPreset


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

    def get_org_scope_q(self, org_id: int) -> Q:
        if org_id is None:
            return Q()
        return Q(org_id=org_id)

    def find_existing(
        self,
        data: dict,
        id_mapper: IDMapper,
        org_id: int = None,
        created_by=None,
    ):
        name = data.get("name")
        if not name:
            raise ValidationError({"name": "This field is required."})

        qs = AuditFilterPreset.objects.filter(name=name).filter(
            self.get_org_scope_q(org_id)
        )
        if created_by is not None:
            qs = qs.filter(created_by=created_by)
        return qs.first()

    def import_entity(
        self,
        data: dict,
        id_mapper: IDMapper,
        is_main: bool = False,
        settings: ImportSettings = None,
        **kwargs,
    ):
        old_id = data.get("id")
        if old_id and id_mapper.has_mapping(self.entity_type, old_id):
            existing_id = id_mapper.get(self.entity_type, old_id)
            return self.get_instance(existing_id)

        org_id = kwargs.get("org_id")
        created_by = kwargs.get("user")

        existing = self.find_existing(
            data, id_mapper, org_id=org_id, created_by=created_by
        )
        if existing is not None:
            instance, was_created = existing, False
        else:
            instance = self.create_entity(
                data, id_mapper, org_id=org_id, created_by=created_by
            )
            was_created = True

        if old_id is not None:
            id_mapper.map(self.entity_type, old_id, instance.id, was_created)

        return instance

    def create_entity(
        self, data: dict, id_mapper: IDMapper, **kwargs
    ) -> AuditFilterPreset:
        return AuditFilterPreset.objects.create(
            org_id=kwargs.get("org_id"),
            created_by=kwargs.get("created_by"),
            name=data["name"],
            filter_body=data.get("filter_body") or {},
        )
