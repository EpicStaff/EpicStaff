from django.db import models


from django.db import models


class McpTool(models.Model):
    """
    Configuration for a FastMCP client connecting to remote MCP tools via SSE.
    """

    name = models.CharField(
        max_length=255, unique=True, help_text="Unique name for mcp configuration"
    )

    transport = models.CharField(
        max_length=2048, help_text="URL of the remote MCP server (SSE). Required."
    )
    tool_name = models.CharField(max_length=255, help_text="Name of the MCP tool.")
    timeout = models.FloatField(
        default=30, help_text="Request timeout in seconds. Recommended to set."
    )
    auth = models.TextField(
        blank=True,
        null=True,
        help_text="Authorization token or OAuth string, if the server requires it.",
    )
    init_timeout = models.FloatField(
        default=10,
        help_text="Timeout for session initialization. Optional, default is 10 seconds.",
    )

    class Meta:
        verbose_name = "MCP Tool Data"
        verbose_name_plural = "MCP Tool Data"
