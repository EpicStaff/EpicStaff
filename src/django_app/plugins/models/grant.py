from django.db import models
from django.db.models import Count, F, OuterRef, Prefetch, Subquery
from django.db.models.functions import Coalesce, Lower
from rbac.models import OrgScopedModel

from plugins.models.enums import GrantState, PluginState
from plugins.models.plugin import Plugin

GRANT_PER_ORGANIZATION_CONSTRAINT = "plugins_grant_plugin_org_uniq"


class PluginGrantQuerySet(models.QuerySet):
    def with_current_package(self) -> "PluginGrantQuerySet":
        """Grants of plugins with an approved package, each with that package (without the icon)."""
        return (
            self.filter(plugin__current_package__isnull=False)
            .select_related("plugin__current_package")
            .defer("plugin__current_package__icon_bytes")
        )

    def with_admin_details(self) -> "PluginGrantQuerySet":
        """Load what the SuperAdmin's grant list shows, in three queries for any number of grants.

        Adds `owned_resource_count` (the resources the plugin created there that still
        exist), `key_last_used_at` (when the grant's service account last called EpicStaff,
        `PluginServiceAccount.last_used_at`) and `install_jobs` (its install hook jobs,
        newest first), and comes with the plugin, organization, granting SuperAdmin and
        service account.
        """
        # Imported here: each of these modules imports this one.
        from plugins.models.hook_job import HookJobKind, PluginHookJob
        from plugins.models.ownership import PluginOwnedResource
        from plugins.ownership.existing_owned import existing_owned_resources

        owned = (
            existing_owned_resources(PluginOwnedResource.objects.filter(grant=OuterRef("pk")))
            .order_by()
            .values("grant")
            .annotate(count=Count("pk"))
            .values("count")
        )
        return (
            self.select_related("plugin", "org", "created_by", "service_account")
            .annotate(
                owned_resource_count=Coalesce(Subquery(owned), 0),
                key_last_used_at=F("service_account__last_used_at"),
            )
            .prefetch_related(
                Prefetch(
                    "hook_jobs",
                    queryset=PluginHookJob.objects.filter(kind=HookJobKind.INSTALL).order_by(
                        "-created_at", "-pk"
                    ),
                    to_attr="install_jobs",
                )
            )
        )

    def usable(self) -> "PluginGrantQuerySet":
        """Grants that make their plugin usable: the grant is active and the plugin running.

        Only these give an organization a plugin row in the left bar and the Roles matrix.
        Each comes with its plugin and current package (without the icon), sorted by plugin
        name.
        """
        return (
            self.with_current_package()
            .filter(state=GrantState.ACTIVE, plugin__state=PluginState.RUNNING)
            .order_by(Lower("plugin__name"), "plugin__identifier")
        )


class PluginGrant(OrgScopedModel):
    """A plugin given to one organization by a SuperAdmin.

    The only organization-owned plugin row: `org` is NOT NULL in the database, and
    `created_by` is the SuperAdmin who granted it. Only `active` grants make a plugin
    usable in the organization.
    """

    plugin = models.ForeignKey(Plugin, on_delete=models.CASCADE, related_name="grants")
    state = models.CharField(max_length=32, choices=GrantState.choices)
    suspended_at = models.DateTimeField(null=True, blank=True)
    purge_after = models.DateTimeField(null=True, blank=True)
    last_hook_error = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PluginGrantQuerySet.as_manager()

    class Meta(OrgScopedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["plugin", "org"], name=GRANT_PER_ORGANIZATION_CONSTRAINT
            ),
        ]

    @property
    def is_usable(self) -> bool:
        """`PluginGrantQuerySet.usable()` for a grant already loaded with its plugin."""
        return (
            self.state == GrantState.ACTIVE
            and self.plugin.state == PluginState.RUNNING
            and self.plugin.current_package_id is not None
        )

    def __str__(self) -> str:
        return f"{self.plugin_id} in org {self.org_id}"
