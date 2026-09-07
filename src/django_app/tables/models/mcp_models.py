from django.db import models

from tables.models.rbac_models.org_scoped import OrgScopedModel


class McpTool(OrgScopedModel, models.Model):
    """
    Configuration for a FastMCP client connecting to remote MCP tools via SSE.
    """

    name = models.CharField(
        max_length=255, help_text="Unique name for mcp configuration"
    )

    transport = models.CharField(
        max_length=2048, help_text="URL of the remote MCP server (SSE). Required."
    )
    tool_name = models.CharField(max_length=255, help_text="Name of the MCP tool.")
    timeout = models.FloatField(
        default=30, help_text="Request timeout in seconds. Recommended to set."
    )
    auth_secret = models.ForeignKey(
        "Secret",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="mcp_tools",
    )
    init_timeout = models.FloatField(
        default=10,
        help_text="Timeout for session initialization. Optional, default is 10 seconds.",
    )
    labels = models.ManyToManyField("Label", blank=True, related_name="mcp_tools")

    class Meta(OrgScopedModel.Meta):
        verbose_name = "MCP Tool Data"
        verbose_name_plural = "MCP Tool Data"
        constraints = [
            models.UniqueConstraint(
                fields=["org", "name"],
                name="unique_mcptool_name_per_org",
            ),
        ]
