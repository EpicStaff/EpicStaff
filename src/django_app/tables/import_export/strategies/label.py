from django.db.models import Q
from rbac.authorship import resolve_author

from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.schemas import ImportSettings
from tables.import_export.serializers.label import LabelImportSerializer
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.models.label_models import Label

# Only flow and tool labels travel in export files. Agent groups are never exported, so
# any other scope in a file is crafted or corrupt and is read as a flow label; trusting
# it would let a file create a nested agent label, which the database rejects.
_IMPORTABLE_SCOPES = {Label.Scope.FLOW, Label.Scope.TOOL}


def _imported_scope(data: dict) -> str:
    scope = data.get("scope")
    return scope if scope in _IMPORTABLE_SCOPES else Label.Scope.FLOW


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
        return super().import_entity(data, id_mapper, is_main, settings=settings, **kwargs)

    def find_existing(self, data: dict, id_mapper: IDMapper, org_id: int | None = None):
        old_parent_id = data.get("parent")
        parent_id = (
            id_mapper.get_or_none(EntityType.LABEL, old_parent_id) if old_parent_id else None
        )
        scope = _imported_scope(data)
        return (
            Label.objects.filter(name=data["name"], parent_id=parent_id, scope=scope)
            .filter(self.get_org_scope_q(org_id))
            .first()
        )

    def get_org_scope_q(self, org_id: int) -> Q:
        if org_id is None:
            return Q()
        return Q(org_id=org_id)

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> Label:
        org_id = kwargs.get("org_id")
        old_parent_id = data.get("parent")
        parent_id = (
            id_mapper.get_or_none(EntityType.LABEL, old_parent_id) if old_parent_id else None
        )
        scope = _imported_scope(data)
        label, _ = Label.objects.get_or_create(
            name=data["name"],
            parent_id=parent_id,
            org_id=org_id,
            scope=scope,
            defaults={
                "metadata": data.get("metadata") or {},
                "created_by": resolve_author(kwargs.get("user")),
            },
        )
        return label
