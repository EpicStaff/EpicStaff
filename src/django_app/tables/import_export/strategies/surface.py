from agents.models import Surface, SurfaceMcpTool, SurfacePythonTool
from django.db.models import Q
from rbac.authorship import resolve_author

from tables.import_export.constants import MAX_REUSE_CANDIDATES
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.serializers.surface import SurfaceImportSerializer
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.utils import (
    compared_values,
    ensure_unique_identifier,
    filter_by_name_or_renamed_copy,
    import_values,
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
        deps[EntityType.MCP_TOOL] = list(instance.mcp_tools.values_list("mcp_tool_id", flat=True))

        return deps

    def export_entity(self, instance: Surface) -> dict:
        return self.serializer_class(instance).data

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> Surface:
        tools = data.pop("tools", {})
        data.pop("owner_agent", None)
        data.pop("id", None)

        organization = resolve_import_organization(kwargs.get("org_id"))

        if "name" in data:
            existing_names = Surface.objects.filter(org=organization).values_list("name", flat=True)
            data["name"] = ensure_unique_identifier(
                base_name=data["name"],
                existing_names=existing_names,
            )

        serializer = self.serializer_class(data=data)
        serializer.is_valid(raise_exception=True)
        surface = serializer.save(
            org=organization,
            owner_agent=kwargs.get("owner_agent"),
            created_by=resolve_author(kwargs.get("user")),
        )

        self._create_python_tools(surface, tools, id_mapper)
        self._create_mcp_tools(surface, tools, id_mapper)

        return surface

    def find_existing(self, data: dict, id_mapper: IDMapper, org_id: int | None = None) -> Surface:
        # Entries that reach this method are shared: nest_owned_surface_entries
        # hands owned ones to AgentDefinitionStrategy. A shared entry reuses only
        # a shared row -- an agent's owned surface may not be listed by another
        # agent or node, and would be deleted together with its owner. SQL
        # narrows on stored columns; the tool sets are compared in Python.
        content_key = self.entry_content_key(data, id_mapper)
        candidates = filter_by_name_or_renamed_copy(
            Surface.objects.filter(
                self.get_org_scope_q(org_id),
                owner_agent__isnull=True,
                instructions=content_key[0],
            ).prefetch_related("python_tools", "mcp_tools"),
            import_values(self.serializer_class, data, ("name",)).get("name"),
        )[:MAX_REUSE_CANDIDATES]
        return next(
            (
                candidate
                for candidate in candidates
                if self.surface_content_key(candidate) == content_key
            ),
            None,
        )

    def entry_content_key(self, data: dict, id_mapper: IDMapper) -> tuple:
        """Return the content an exported surface entry is matched on.

        Instructions as the import serializer stores them (the model default
        when missing) plus the remapped python and MCP tool sets with modes;
        equal to `surface_content_key` of an equivalent stored surface.
        """
        tools = data.get("tools", {})
        python_tool_pairs = self._remap_tool_set(
            tools.get(EntityType.PYTHON_CODE_TOOL, []),
            "python_tool_id",
            EntityType.PYTHON_CODE_TOOL,
            id_mapper,
        )
        mcp_tool_pairs = self._remap_tool_set(
            tools.get(EntityType.MCP_TOOL, []),
            "mcp_tool_id",
            EntityType.MCP_TOOL,
            id_mapper,
        )
        instructions = compared_values(Surface, self.serializer_class, data, ("instructions",))
        return (
            instructions["instructions"],
            frozenset(python_tool_pairs),
            frozenset(mcp_tool_pairs),
        )

    @staticmethod
    def surface_content_key(surface: Surface) -> tuple:
        """Return `entry_content_key` for a stored surface (tools prefetched)."""
        return (
            surface.instructions,
            frozenset((row.python_tool_id, row.mode) for row in surface.python_tools.all()),
            frozenset((row.mcp_tool_id, row.mode) for row in surface.mcp_tools.all()),
        )

    def get_org_scope_q(self, org_id: int) -> Q:
        organization = resolve_import_organization(org_id)
        if organization is None:
            return Q()
        return Q(org=organization)

    def _remap_tool_set(
        self, entries: list, id_field: str, entity_type: EntityType, id_mapper: IDMapper
    ) -> set:
        remapped = set()

        for entry in entries:
            new_id = id_mapper.get_or_none(entity_type, entry[id_field])
            if new_id is None:
                continue

            remapped.add((new_id, entry["mode"]))

        return remapped

    def _create_python_tools(self, surface: Surface, tools: dict, id_mapper: IDMapper):
        python_tool_rows = []

        for entry in tools.get(EntityType.PYTHON_CODE_TOOL, []):
            new_id = id_mapper.get_or_none(EntityType.PYTHON_CODE_TOOL, entry["python_tool_id"])
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
