from django.db import transaction
from rbac.authorship import record_last_edit, resolve_author
from tables.models import Label
from tables.models.mcp_models import McpTool
from tables.services.copy_services.base_copy_service import BaseCopyService
from tables.services.copy_services.helpers import next_copy_name


class McpToolCopyService(BaseCopyService):
    """Copy service for McpTool entities.

    Duplicates all scalar fields and the tool-scope labels M2M.
    """

    def copy(
        self,
        tool: McpTool,
        name: str | None = None,
        org_id: int | None = None,
        user=None,
    ) -> McpTool:
        target_org_id = org_id if org_id is not None else tool.org_id
        base_name = name if name else tool.name

        with transaction.atomic():
            new_tool = McpTool.objects.create(
                name=next_copy_name(McpTool, org_id=target_org_id, base_name=base_name),
                org_id=target_org_id,
                transport=tool.transport,
                tool_name=tool.tool_name,
                timeout=tool.timeout,
                auth_secret=tool.auth_secret,
                init_timeout=tool.init_timeout,
                created_by=resolve_author(user),
            )
            record_last_edit(new_tool, user)

        new_tool.labels.set(tool.labels.filter(scope=Label.Scope.TOOL, org_id=new_tool.org_id))
        return new_tool
