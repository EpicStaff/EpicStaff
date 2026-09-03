import json

from rest_framework.exceptions import ValidationError

from tables.import_export.services.export_service import ExportService
from tables.import_export.services.import_service import ImportService, ImportSettings
from tables.import_export.services.inspect_service import InspectService
from tables.import_export.version_conversions.base import VersionConverter
from tables.import_export.registry import entity_registry
from tables.import_export.constants import MAIN_ENTITY_KEY
from tables.import_export.export_format_strategies import JsonExportFormatStrategy
from tables.services.rbac.permission_resolver import PermissionResolver


class ViewSetImportExportService:
    def __init__(
        self, entity_type, export_prefix, filename_attr, format_strategies=None
    ):
        self.entity_type = entity_type
        self.export_prefix = export_prefix
        self.filename_attr = filename_attr
        self.export_service = ExportService(entity_registry)
        self.import_service = ImportService(entity_registry)
        self.format_strategies = format_strategies or {
            "json": JsonExportFormatStrategy()
        }

    def export_entity(self, instance, fmt: str = "json", org_id: int | None = None):
        data = self.export_service.export_entities(
            self.entity_type, [instance.pk], org_id=org_id
        )
        if fmt not in self.format_strategies:
            raise ValidationError(
                f"Unsupported export format: '{fmt}'. Supported: {list(self.format_strategies)}"
            )
        strategy = self.format_strategies[fmt]
        base_name = str(getattr(instance, self.filename_attr, "object"))
        return strategy.render(data, self.entity_type, self.export_prefix, base_name)

    def bulk_export(self, entity_ids, fmt: str = "json", org_id: int | None = None):
        data = self.export_service.export_entities(
            self.entity_type, entity_ids, org_id=org_id
        )
        if fmt not in self.format_strategies:
            raise ValidationError(
                f"Unsupported export format: '{fmt}'. Supported: {list(self.format_strategies)}"
            )
        strategy = self.format_strategies[fmt]
        base_name = f"bulk_{len(entity_ids)}"
        return strategy.render(data, self.entity_type, self.export_prefix, base_name)

    def _parse_and_validate(self, file) -> dict:
        try:
            data = json.load(file)
        except json.JSONDecodeError:
            raise ValidationError("Invalid JSON file")

        if not isinstance(data, dict):
            raise ValidationError("Invalid import file: expected a JSON object")

        if data.get(MAIN_ENTITY_KEY) is None:
            raise ValidationError(f"Missing '{MAIN_ENTITY_KEY}' in import file")

        main_entity = data[MAIN_ENTITY_KEY]
        if main_entity != self.entity_type:
            raise ValidationError(
                f"Provided wrong entity. Got: {main_entity}. Expected: {self.entity_type.value}"
            )

        return VersionConverter.convert(data)

    def import_entity(
        self, file, user, settings: ImportSettings = None, org_id: int = None
    ):
        data = self._parse_and_validate(file)

        effective_permissions = PermissionResolver().resolve(user=user, org_id=org_id)
        id_mapper, registry = self.import_service.import_data(
            data,
            self.entity_type,
            settings=settings,
            org_id=org_id,
            user=user,
            effective_permissions=effective_permissions,
        )
        summary = id_mapper.get_detailed_summary(registry)

        return summary

    def inspect_entity(self, file, org_id: int | None = None) -> dict:
        data = self._parse_and_validate(file)
        return InspectService().inspect(data, org_id=org_id)
