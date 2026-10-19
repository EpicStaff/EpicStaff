from django.db.models import Case, Q, When
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
        """Reuse a preset with the same search, otherwise create a private one.

        A preset in the org that the importer authored, or that anyone shared, with the
        same `filters`, `query` and `match_scope` is reused and mapped as not created, so
        the import summary reports it under "reused". A colleague's private preset never
        matches. A created preset whose name the importer already uses gets the copy
        numbering; colleagues' names do not collide.
        """
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValidationError({"name": "This field is required."})
        # Strip like the serializer's CharField does, so the collision check sees the stored name.
        name = name.strip()
        org_id = kwargs.get("org_id")
        created_by = kwargs.get("user")

        # Validate before matching, so a malformed entry is rejected rather than reused.
        serializer = self.serializer_class(data={**data, "name": name})
        serializer.is_valid(raise_exception=True)

        existing = self._find_same_search(
            serializer.validated_data["filter_body"], org_id, created_by.id
        )
        if existing is not None:
            # ImportService keeps a mapping the strategy registered itself.
            id_mapper.map(self.entity_type, data["id"], existing.id, was_created=False)
            return existing

        # A numbered name always fits the column, so the validation above still holds.
        free_name = next_free_preset_name(org_id, created_by.id, name)
        return serializer.save(name=free_name, org_id=org_id, created_by=created_by)

    def _find_same_search(
        self, filter_body: dict, org_id: int, user_id: int
    ) -> AuditFilterPreset | None:
        search_key = _search_key(filter_body)
        # A colleague's private preset is excluded: matching it would reveal it exists.
        candidates = AuditFilterPreset.objects.filter(org_id=org_id).filter(
            Q(created_by_id=user_id) | Q(is_shared=True)
        )
        # The importer's own preset wins over a colleague's shared one with the same search.
        candidates = candidates.order_by(Case(When(created_by_id=user_id, then=0), default=1), "id")
        # NOTE: Python scan over the org's visible presets; move the key into SQL if an
        # org ever holds thousands of them.
        for candidate in candidates:
            if _search_key(candidate.filter_body) == search_key:
                return candidate
        return None


def _search_key(filter_body: dict) -> tuple:
    """Return what makes two presets run the same search; ui_state, cursor and size do not.

    A blank `query` counts as no query, as the auditor treats it. `match_scope` is
    compared literally: the UI always writes it in full.
    """
    query = filter_body.get("query")
    if isinstance(query, str):
        query = query.strip() or None
    return (filter_body.get("filters"), query, filter_body.get("match_scope"))
