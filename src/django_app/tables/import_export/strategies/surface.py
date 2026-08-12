from agents.models import Surface, SurfacePythonTool, SurfaceMcpTool
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.serializers.surface import SurfaceImportSerializer
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.utils import (
    ensure_unique_identifier,
    resolve_import_organization,
)


class SurfaceStrategy(EntityImportExportStrategy):
    entity_type = EntityType.SURFACE
    serializer_class = SurfaceImportSerializer

    def get_instance(self, entity_id: int) -> Surface:
        return Surface.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: Surface) -> dict:
        return {"id": instance.id, "name": instance.name}

    def extract_dependencies_from_instance(self, instance: Surface) -> dict:
        deps = {}

        deps[EntityType.PYTHON_CODE_TOOL] = list(
            instance.python_tools.values_list("python_tool_id", flat=True)
        )
        deps[EntityType.MCP_TOOL] = list(
            instance.mcp_tools.values_list("mcp_tool_id", flat=True)
        )

        return deps

    def export_entity(self, instance: Surface) -> dict:
        return self.serializer_class(instance).data

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> Surface:
        tools = data.pop("tools", {})
        data.pop("owner_agent", None)
        data.pop("id", None)

        organization = resolve_import_organization(kwargs.get("org_id"))

        if "name" in data:
            existing_names = Surface.objects.filter(
                organization=organization
            ).values_list("name", flat=True)
            data["name"] = ensure_unique_identifier(
                base_name=data["name"],
                existing_names=existing_names,
            )

        serializer = self.serializer_class(data=data)
        serializer.is_valid(raise_exception=True)
        surface = serializer.save(organization=organization)

        self._create_python_tools(surface, tools, id_mapper)
        self._create_mcp_tools(surface, tools, id_mapper)

        return surface

    def _create_python_tools(self, surface: Surface, tools: dict, id_mapper: IDMapper):
        python_tool_rows = []

        for entry in tools.get(EntityType.PYTHON_CODE_TOOL, []):
            new_id = id_mapper.get_or_none(
                EntityType.PYTHON_CODE_TOOL, entry["python_tool_id"]
            )
            if new_id is None:
                continue

            python_tool_rows.append(
                SurfacePythonTool(
                    surface=surface,
                    python_tool_id=new_id,
                    mode=entry["mode"],
                )
            )

        SurfacePythonTool.objects.bulk_create(python_tool_rows, ignore_conflicts=True)

    def _create_mcp_tools(self, surface: Surface, tools: dict, id_mapper: IDMapper):
        mcp_tool_rows = []

        for entry in tools.get(EntityType.MCP_TOOL, []):
            new_id = id_mapper.get_or_none(EntityType.MCP_TOOL, entry["mcp_tool_id"])
            if new_id is None:
                continue

            mcp_tool_rows.append(
                SurfaceMcpTool(
                    surface=surface,
                    mcp_tool_id=new_id,
                    mode=entry["mode"],
                )
            )

        SurfaceMcpTool.objects.bulk_create(mcp_tool_rows, ignore_conflicts=True)
