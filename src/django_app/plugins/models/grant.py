from django.db import models
from django.db.models import Exists, F, OuterRef, Prefetch
from django.db.models.functions import Lower
from rbac.models import Organization, OrgScopedModel

from plugins.models.enums import GrantState, PluginState, SuspensionCause
from plugins.models.plugin import Plugin

GRANT_PER_ORGANIZATION_CONSTRAINT = "plugins_grant_plugin_org_uniq"
MAX_PURGE_ERROR_LENGTH = 2000


class PluginGrantQuerySet(models.QuerySet):
    def with_current_package(self) -> "PluginGrantQuerySet":
        """Grants of plugins with an approved package, each with that package (without the icon)."""
        return (
            self.filter(plugin__current_package__isnull=False)
            .select_related("plugin__current_package")
            .defer("plugin__current_package__icon_bytes")
        )

    def with_admin_details(self) -> "PluginGrantQuerySet":
        """Load what the SuperAdmin's grant list shows, in two queries for any number of grants.

        Adds `key_last_used_at` (when the grant's service account last called EpicStaff,
        `PluginServiceAccount.last_used_at`), and `install_jobs`, `upgrade_jobs` and
        `org_removed_jobs` (its install, upgrade and organization removed hook jobs, newest
        first, the last annotated with `organization_exists`), and comes with the plugin,
        organization, granting SuperAdmin and service account. The owned-resource count is
        set on the page afterwards (`ownership.owned_resource_summary.with_owned_resource_counts`).
        """
        # Imported here: the hook job module imports this one.
        from plugins.models.hook_job import HookJobKind, PluginHookJob

        return (
            self.select_related("plugin", "org", "created_by", "service_account")
            .annotate(key_last_used_at=F("service_account__last_used_at"))
            .prefetch_related(
                Prefetch(
                    "hook_jobs",
                    queryset=PluginHookJob.objects.filter(kind=HookJobKind.INSTALL).order_by(
                        "-created_at", "-pk"
                    ),
                    to_attr="install_jobs",
                ),
                Prefetch(
                    "hook_jobs",
                    queryset=PluginHookJob.objects.filter(kind=HookJobKind.UPGRADE).order_by(
                        "-created_at", "-pk"
                    ),
                    to_attr="upgrade_jobs",
                ),
                Prefetch(
                    "hook_jobs",
                    queryset=PluginHookJob.objects.filter(kind=HookJobKind.ORG_REMOVED)
                    .annotate(
                        organization_exists=Exists(
                            Organization.objects.filter(pk=OuterRef("organization_id"))
                        )
                    )
                    .order_by("-created_at", "-pk"),
                    to_attr="org_removed_jobs",
                ),
            )
        )

    def listed(self) -> "PluginGrantQuerySet":
        """Grants that give their organization a plugin in the Apps list: usable ones, and
        ones whose plugin or organization is being upgraded (its page then says so).

        `active` or `upgrading` grants of a plugin `running` or in `maintenance`. Only the list
        of available plugins uses it; sign-in, the gateway and the Roles matrix use `usable()`.
        Each comes with its plugin and current package (without the icon), sorted by name.
        """
        return (
            self.with_current_package()
            .filter(
                state__in=(GrantState.ACTIVE, GrantState.UPGRADING),
                plugin__state__in=(PluginState.RUNNING, PluginState.MAINTENANCE),
            )
            .order_by(Lower("plugin__name"), "plugin__identifier")
        )

    def usable(self) -> "PluginGrantQuerySet":
        """Grants that make their plugin usable: the grant is active and the plugin running.

        Only these give an organization a plugin in the Apps list and the Roles matrix.
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
    suspension_cause = models.CharField(
        max_length=16, choices=SuspensionCause.choices, null=True, blank=True
    )
    purge_after = models.DateTimeField(null=True, blank=True)
    last_hook_error = models.TextField(null=True, blank=True)
    # The plugin version this organization was last brought to: set when its install or
    # upgrade hook succeeds, or when it becomes active without one. Null while its install
    # hook has not succeeded.
    installed_version = models.CharField(max_length=64, null=True, blank=True)
    # When deleting the grant's data began; the row is deleted once it is done.
    purge_started_at = models.DateTimeField(null=True, blank=True)
    # The first resource the last purge pass could not delete, and why; cleared by a pass
    # with no failure.
    last_purge_error = models.CharField(max_length=MAX_PURGE_ERROR_LENGTH, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PluginGrantQuerySet.as_manager()

    class Meta(OrgScopedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["plugin", "org"], name=GRANT_PER_ORGANIZATION_CONSTRAINT
            ),
        ]
        indexes = [
            *OrgScopedModel.Meta.indexes,
            # The grace-period sweep asks for suspended grants whose time is up.
            models.Index(fields=["state", "purge_after"], name="plugins_grant_state_purge"),
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
