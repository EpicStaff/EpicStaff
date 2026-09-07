from tables.import_export.utils import ensure_unique_identifier
from tables.models import Label
from tables.models.mcp_models import McpTool
from tables.services.copy_services.base_copy_service import BaseCopyService


class McpToolCopyService(BaseCopyService):
    """Copy service for McpTool entities.

    Duplicates all scalar fields and the tool-scope labels M2M.
    """

    def copy(
        self, tool: McpTool, name: str | None = None, org_id: int | None = None
    ) -> McpTool:
        target_org_id = org_id if org_id is not None else tool.org_id

        existing_names = McpTool.objects.filter(org_id=target_org_id).values_list(
            "name", flat=True
        )
        new_name = ensure_unique_identifier(
            base_name=name if name else tool.name,
            existing_names=existing_names,
        )

        new_tool = McpTool.objects.create(
            name=new_name,
            org_id=target_org_id,
            transport=tool.transport,
            tool_name=tool.tool_name,
            timeout=tool.timeout,
            auth_secret=tool.auth_secret,
            init_timeout=tool.init_timeout,
        )
        new_tool.labels.set(
            tool.labels.filter(scope=Label.Scope.TOOL, org_id=new_tool.org_id)
        )
        return new_tool
