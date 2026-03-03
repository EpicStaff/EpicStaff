from copy import deepcopy

from tables.models import McpTool
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.serializers.mcp_tools import McpToolImportSerializer
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.utils import (
    ensure_unique_identifier,
    create_filters,
)


class McpToolStrategy(EntityImportExportStrategy):
    entity_type = EntityType.MCP_TOOL
    serializer_class = McpToolImportSerializer

    def get_instance(self, entity_id: int):
        return McpTool.objects.filter(id=entity_id).first()

    def extract_dependencies_from_instance(self, instance):
        return {}

    def export_entity(self, instance: McpTool) -> dict:
        return self.serializer_class(instance).data

    def create_entity(self, data: dict, id_mapper: IDMapper) -> McpTool:
        if "name" in data:
            existing_names = McpTool.objects.values_list("name", flat=True)
            data["name"] = ensure_unique_identifier(
                base_name=data["name"],
                existing_names=existing_names,
            )

        serializer = self.serializer_class(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    def find_existing(self, data: dict, id_mapper: IDMapper) -> McpTool:
        data_copy = deepcopy(data)
        data_copy.pop("id", None)

        filters, null_filters = create_filters(data_copy)
        existing = McpTool.objects.filter(**filters, **null_filters).first()
        return existing
