from copy import deepcopy

from django.db.models import Q

from tables.models import McpTool
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.utils import attach_tool_labels
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

    def get_preview_data(self, instance: McpTool) -> dict:
        return {"id": instance.id, "name": instance.name}

    def extract_dependencies_from_instance(self, instance):
        return {EntityType.LABEL: list(instance.labels.values_list("id", flat=True))}

    def extract_org_scoped_dependencies(
        self, instance: McpTool, org_id: int
    ) -> dict[str, list[int]]:
        return {
            EntityType.LABEL: list(
                instance.labels.filter(org_id=org_id).values_list("id", flat=True)
            )
        }

    def export_entity(self, instance: McpTool) -> dict:
        data = self.serializer_class(instance).data
        data["labels"] = list(instance.labels.values_list("id", flat=True))
        return data

    def export_entity_org_scoped(self, instance: McpTool, org_id: int) -> dict:
        data = self.serializer_class(instance).data
        data["labels"] = list(
            instance.labels.filter(org_id=org_id).values_list("id", flat=True)
        )
        return data

    def get_org_scope_q(self, org_id: int) -> Q:
        if org_id is None:
            return Q()
        return Q(org_id=org_id)

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> McpTool:
        org_id = kwargs.get("org_id")
        import_labels = kwargs.get("import_labels", True)
        labels_data = data.pop("labels", [])
        if "name" in data:
            existing_names = McpTool.objects.filter(org_id=org_id).values_list(
                "name", flat=True
            )
            data["name"] = ensure_unique_identifier(
                base_name=data["name"],
                existing_names=existing_names,
            )

        serializer = self.serializer_class(data={**data, "org": org_id})
        serializer.is_valid(raise_exception=True)
        mcp_tool = serializer.save()

        if import_labels and labels_data:
            attach_tool_labels(mcp_tool, id_mapper, labels_data)

        return mcp_tool

    def find_existing(
        self, data: dict, id_mapper: IDMapper, org_id: int = None
    ) -> McpTool:
        data_copy = deepcopy(data)
        data_copy.pop("id", None)
        data_copy.pop("labels", None)

        filters, null_filters = create_filters(data_copy)
        existing = (
            McpTool.objects.filter(**filters, **null_filters)
            .filter(self.get_org_scope_q(org_id))
            .first()
        )
        return existing
