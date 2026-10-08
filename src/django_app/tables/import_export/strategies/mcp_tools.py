from django.db.models import Q

from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.serializers.mcp_tools import McpToolImportSerializer
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.utils import (
    attach_tool_labels,
    compared_values,
    create_filters,
    ensure_unique_identifier,
    filter_by_name_or_renamed_copy,
    import_values,
)
from tables.models import McpTool

# Scalar fields compared for reuse, next to the rename-aware name match. An
# explicit allowlist, not create_filters over the whole exported dict: legacy
# files carry created_at/updated_at (and the source org), which a re-created
# tool never matches.
COMPARED_FIELDS = ("transport", "tool_name", "timeout", "init_timeout")


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
        data["labels"] = list(instance.labels.filter(org_id=org_id).values_list("id", flat=True))
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
            existing_names = McpTool.objects.filter(org_id=org_id).values_list("name", flat=True)
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

    def find_existing(self, data: dict, id_mapper: IDMapper, org_id: int | None = None) -> McpTool:
        # Every compared value is a stored column, so SQL decides and at most one
        # row is loaded.
        filters, null_filters = create_filters(
            compared_values(McpTool, self.serializer_class, data, COMPARED_FIELDS)
        )
        return filter_by_name_or_renamed_copy(
            McpTool.objects.filter(**filters, **null_filters).filter(self.get_org_scope_q(org_id)),
            import_values(self.serializer_class, data, ("name",)).get("name"),
        ).first()
