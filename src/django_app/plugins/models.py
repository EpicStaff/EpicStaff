from django.db import models
from rbac.models.org_scoped import OrgScopedModel
from tables.models.base_models import TimestampMixin

from plugins.resource_types import PluginResourceType


class Plugin(OrgScopedModel, TimestampMixin):
    """A plugin installed in one organization.

    The plugin is a resource, not an identity: what it installed is ordinary,
    editable org data, linked back through `PluginResource`. `manifest` keeps the
    uploaded plugin.json for reference only; nothing reads behaviour from it.
    """

    class State(models.TextChoices):
        PREPARING = "preparing", "Preparing"
        READY = "ready", "Ready"
        NEEDS_ATTENTION = "needs_attention", "Needs attention"

    # Overrides the nullable OrgScopedModel.org: a brand-new table has nothing to backfill.
    org = models.ForeignKey(
        "rbac.Organization",
        on_delete=models.CASCADE,
        related_name="plugins",
    )
    plugin_id = models.CharField(max_length=64)
    version = models.CharField(max_length=64)
    format_version = models.PositiveSmallIntegerField()
    bridge_version = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    icon_data_url = models.TextField(blank=True, default="")
    # Path of the page's entry file inside the UI assets; blank when the plugin has no page.
    ui_entry = models.CharField(max_length=255, blank=True, default="")
    state = models.CharField(max_length=32, choices=State.choices, default=State.READY)
    status_reason = models.TextField(blank=True, default="")
    suspended = models.BooleanField(default=False)
    suspended_at = models.DateTimeField(null=True, blank=True)
    # [{alias, type, ref, actions}] -- `ref` is the entity id inside resources.json.
    access = models.JSONField(default=list, blank=True)
    # [{name, description}]
    secret_slots = models.JSONField(default=list, blank=True)
    manifest = models.JSONField(default=dict, blank=True)

    class Meta(OrgScopedModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["org", "plugin_id"], name="unique_plugin_id_per_org"),
        ]

    def __str__(self) -> str:
        return f"{self.plugin_id} {self.version} (org={self.org_id})"


class PluginResource(models.Model):
    """One org row a plugin installed: the registry suspend and delete walk."""

    plugin = models.ForeignKey(Plugin, on_delete=models.CASCADE, related_name="resources")
    resource_type = models.CharField(max_length=32, choices=PluginResourceType.choices)
    object_id = models.BigIntegerField()
    # Where the row came from in the bundle: the resources.json id, a slot name,
    # a knowledge collection name or a bundle file path.
    manifest_ref = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plugin", "resource_type", "object_id"],
                name="unique_plugin_resource",
            ),
        ]
        indexes = [models.Index(fields=["resource_type", "object_id"])]


class PluginAsset(models.Model):
    """One file of a plugin's own page, stored in the database.

    Stored here rather than object storage so it is written atomically with the
    install, cascades on delete, and is migrated and backed up with the rest.
    """

    plugin = models.ForeignKey(Plugin, on_delete=models.CASCADE, related_name="assets")
    # Relative to the bundle's ui/ folder, e.g. "index.html".
    path = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    content = models.BinaryField()
    sha256 = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["plugin", "path"], name="unique_plugin_asset_path"),
        ]
