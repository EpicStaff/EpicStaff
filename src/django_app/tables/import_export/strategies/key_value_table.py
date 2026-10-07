from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Q
from rest_framework import serializers

from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.serializers.key_value_table import KeyValueTableImportSerializer
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.models import KeyValueTable


class KeyValueTableStrategy(EntityImportExportStrategy):
    """Key-value tables travel with the flows whose Key-Value nodes use them.

    Strictly org-scoped: an import reuses the importing org's table with the same
    name (case-insensitive, as table names are unique per org) and otherwise creates
    one in that org. Only the definition is exported, never the entries.
    """

    entity_type = EntityType.KEY_VALUE_TABLE
    serializer_class = KeyValueTableImportSerializer

    def get_instance(self, entity_id: int) -> KeyValueTable | None:
        return KeyValueTable.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: KeyValueTable) -> dict:
        return {"id": instance.id, "name": instance.name}

    def extract_dependencies_from_instance(self, instance: KeyValueTable) -> dict:
        return {}

    def export_entity(self, instance: KeyValueTable) -> dict:
        return self.serializer_class(instance).data

    def get_org_scope_q(self, org_id: int) -> Q:
        if org_id is None:
            return Q()
        return Q(org_id=org_id)

    def find_existing(
        self, data: dict, id_mapper: IDMapper, org_id: int | None = None
    ) -> KeyValueTable | None:
        # Without an org there is no table a node could safely bind to.
        if org_id is None or not data.get("name"):
            return None
        return KeyValueTable.objects.filter(
            self.get_org_scope_q(org_id), name__iexact=data["name"]
        ).first()

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> Any:
        """Create the table in the importing org, whatever org the file came from.

        A plain import that loses a race to another request creating the same name
        reuses that table, as `find_existing` would have. A forced create (plugin
        install) never reuses an org's table.

        Raises:
            serializers.ValidationError: there is no importing org, the name is
                invalid, or a forced create finds the name already taken.
        """
        org_id = kwargs.get("org_id")
        if org_id is None:
            raise serializers.ValidationError(
                {"org": "A key-value table can only be imported into an organization."}
            )
        serializer = self.serializer_class(data=data)
        serializer.is_valid(raise_exception=True)
        name = serializer.validated_data["name"]
        try:
            # A savepoint, so a name conflict leaves the import's transaction usable.
            with transaction.atomic():
                return serializer.save(org_id=org_id)
        except IntegrityError:
            existing = KeyValueTable.objects.filter(org_id=org_id, name__iexact=name).first()
            if existing is None:
                raise
            if self.entity_type in kwargs.get("force_create_types", ()):
                raise serializers.ValidationError(
                    {"name": f"A key-value table named '{name}' already exists."}
                ) from None
            return existing
