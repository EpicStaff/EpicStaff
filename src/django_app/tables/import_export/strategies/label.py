from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.serializers.label import LabelImportSerializer
from tables.import_export.id_mapper import IDMapper
from tables.import_export.enums import EntityType
from tables.import_export.schemas import ImportSettings
from tables.models.label_models import Label


class LabelStrategy(EntityImportExportStrategy):
    entity_type = EntityType.LABEL
    serializer_class = LabelImportSerializer

    def get_instance(self, entity_id: int):
        return Label.objects.filter(id=entity_id).first()

    def extract_dependencies_from_instance(self, instance: Label):
        if instance.parent_id:
            return {EntityType.LABEL: [instance.parent_id]}
        return {}

    def get_preview_data(self, instance: Label) -> dict:
        return {"id": instance.id, "name": instance.name}

    def export_entity(self, instance: Label) -> dict:
        return LabelImportSerializer(instance).data

    def import_entity(
        self, data, id_mapper, is_main=False, settings: ImportSettings = None, **kwargs
    ):
        if settings is not None and not settings.import_labels:
            return None
        return super().import_entity(
            data, id_mapper, is_main, settings=settings, **kwargs
        )

    def find_existing(self, data: dict, id_mapper: IDMapper):
        old_parent_id = data.get("parent")
        parent_id = (
            id_mapper.get_or_none(EntityType.LABEL, old_parent_id)
            if old_parent_id
            else None
        )
        return Label.objects.filter(name=data["name"], parent_id=parent_id).first()

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> Label:
        old_parent_id = data.get("parent")
        parent_id = (
            id_mapper.get_or_none(EntityType.LABEL, old_parent_id)
            if old_parent_id
            else None
        )
        label, _ = Label.objects.get_or_create(
            name=data["name"],
            parent_id=parent_id,
            defaults={"metadata": data.get("metadata") or {}},
        )
        return label
