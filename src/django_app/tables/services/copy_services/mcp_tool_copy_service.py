from tables.import_export.utils import ensure_unique_identifier
from tables.models.mcp_models import McpTool
from tables.services.copy_services.base_copy_service import BaseCopyService


class McpToolCopyService(BaseCopyService):
    """Copy service for McpTool entities.

    Duplicates all scalar fields. No nested objects to clone.
    """

    def copy(self, tool: McpTool, name: str | None = None) -> McpTool:
        existing_names = McpTool.objects.values_list("name", flat=True)
        new_name = ensure_unique_identifier(
            base_name=name if name else tool.name,
            existing_names=existing_names,
        )

        return McpTool.objects.create(
            org=tool.org,
            name=new_name,
            transport=tool.transport,
            tool_name=tool.tool_name,
            timeout=tool.timeout,
            auth_secret=tool.auth_secret,
            init_timeout=tool.init_timeout,
        )
