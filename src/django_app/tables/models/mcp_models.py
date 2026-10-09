from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from rbac.models.org_scoped import OrgScopedModel

from tables.models.base_models import (
    SoftDeleteMixin,
    TimestampMixin,
    soft_delete_consistency_constraint,
)
from tables.validators.finite_number_validator import validate_finite_number
from tables.validators.mcp_transport_validator import validate_mcp_transport_url


class McpTool(OrgScopedModel, TimestampMixin, SoftDeleteMixin):
    """
    Configuration for a FastMCP client connecting to remote MCP tools via SSE.
    """

    name = models.CharField(max_length=255, help_text="Unique name for mcp configuration")

    # Deliberately unvalidated -- no scheme restriction, no private/loopback/link-local
    # range check. Won't Fix: the backend cannot validate an MCP endpoint on the
    # user's/operator's behalf; pointing this at an address is the intended shape of
    # the feature, and what it points at is their responsibility. Covers the SSRF
    # reading of this field (backend connects wherever the caller points it, including
    # internal services) -- it does NOT cover trusting the remote server's own
    # description/inputSchema once connected; that is separate, already-tracked work.
    transport = models.CharField(
        max_length=2048,
        validators=[validate_mcp_transport_url],
        help_text="http(s) URL of the remote MCP server (SSE). Required.",
    )
    tool_name = models.CharField(max_length=255, help_text="Name of the MCP tool.")
    timeout = models.FloatField(
        default=30,
        validators=[validate_finite_number, MinValueValidator(1), MaxValueValidator(1800)],
        help_text="Request timeout in seconds. Recommended to set.",
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
        validators=[validate_finite_number, MinValueValidator(1), MaxValueValidator(120)],
        help_text="Timeout for session initialization. Optional, default is 10 seconds.",
    )
    labels = models.ManyToManyField("Label", blank=True, related_name="mcp_tools")

    class Meta(OrgScopedModel.Meta):
        verbose_name = "MCP Tool Data"
        verbose_name_plural = "MCP Tool Data"
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [
            soft_delete_consistency_constraint(),
            models.UniqueConstraint(
                fields=["org", "name"],
                condition=models.Q(active=True),
                name="unique_mcptool_name_per_org",
            ),
        ]
