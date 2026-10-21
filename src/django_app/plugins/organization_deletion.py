"""The plugins app's part in deleting an organization.

An organization's grants, their service accounts, keys and role actions, and what plugins own
there all go with the organization's cascade; plugins, packages, hook jobs and activity
events are deployment-wide and stay. Before the cascade runs, each grant's open install or
upgrade job is failed, and every plugin with an organization removed hook is asked to
delete its own data for the organization: the job keeps the organization's id and name, and
runs once the plugin's process can run it, after the organization is gone.
"""

from django.db.models import QuerySet
from django.utils import timezone
from rbac.governance.organization_deletion import OrganizationDeletionCounts, PostCommitCleanup
from rbac.models import Organization
from utils.logger import logger

from plugins.audit import log_organization_deleted
from plugins.lifecycle.org_removed_hooks import (
    SETTLED_ORG_REMOVED_STATES,
    OrgRemovedHookService,
    has_org_removed_hook,
)
from plugins.models import HookJobKind, HookJobState, PluginGrant, PluginHookJob
from plugins.models.hook_job import OPEN_HOOK_JOB_STATES

ORGANIZATION_DELETED = "Organization deleted."
# The kinds whose job is a step of its grant, which the organization's deletion ends.
_GRANT_STEP_KINDS = (HookJobKind.INSTALL, HookJobKind.UPGRADE)


class PluginsOrganizationDeletion:
    """Asks each plugin granted to a deleted organization to delete its data there."""

    def resource_names(self) -> dict[str, str]:
        return {"plugins.PluginGrant": "plugin_grants"}

    def excluded_resource_labels(self) -> frozenset[str]:
        # Details of a grant or of a resource, both already reported.
        return frozenset(
            {
                "plugins.PluginRolePermission",
                "plugins.PluginServiceAccount",
                "plugins.PluginServiceAccountKey",
                "plugins.PluginOwnedResource",
            }
        )

    def count_external_artifacts(self, organization: Organization) -> dict[str, int]:
        """`plugin_data`: the plugins that will be asked to delete their data for the
        organization, leaving out those that already did or were skipped. Never raises: a
        failure is logged and counts nothing."""
        try:
            return {"plugin_data": _plugins_holding_data(organization)}
        except Exception:  # the delete report must not fail over a count
            logger.exception("Could not count the plugin data of organization {}", organization.pk)
            return {}

    def count(self, organization: Organization) -> OrganizationDeletionCounts:
        # The sweep deletes no row: grants and what hangs off them go with the cascade, and
        # owned resources are reported under their own names.
        return OrganizationDeletionCounts()

    def sweep(self, organization: Organization) -> PostCommitCleanup | None:
        """Fail the grants' open install and upgrade jobs, and create (or keep) one
        organization removed job per plugin with the hook; runs before the cascade, with the
        organization locked. Never locks a plugin row.
        """
        now = timezone.now()
        grants = list(_grants_of(organization).select_for_update(of=("self",)).order_by("pk"))
        open_steps = list(
            PluginHookJob.objects.select_for_update()
            .filter(grant__in=grants, kind__in=_GRANT_STEP_KINDS, state__in=OPEN_HOOK_JOB_STATES)
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        PluginHookJob.objects.filter(pk__in=open_steps).update(
            state=HookJobState.FAILED, finished_at=now, error=ORGANIZATION_DELETED, updated_at=now
        )
        hooks = OrgRemovedHookService()
        data_removals = sum(
            hooks.ensure_job(
                grant.plugin,
                organization_id=organization.pk,
                organization_name=organization.name,
                grant=grant,
            )
            is not None
            for grant in grants
        )
        organization_id = organization.pk
        grant_count = len(grants)

        def log_deleted() -> None:
            log_organization_deleted(
                org_id=organization_id, grants=grant_count, data_removals=data_removals
            )

        return log_deleted


def _grants_of(organization: Organization) -> QuerySet[PluginGrant]:
    return (
        PluginGrant.objects.filter(org=organization)
        .select_related("plugin__current_package")
        .defer("plugin__current_package__icon_bytes")
    )


def _plugins_holding_data(organization: Organization) -> int:
    """How many of the organization's grants are of a plugin with the hook whose latest job for
    the organization has not succeeded or been skipped: two queries."""
    hooked = {
        grant.plugin_id for grant in _grants_of(organization) if has_org_removed_hook(grant.plugin)
    }
    if not hooked:
        return 0
    latest_state: dict[int, str] = {}
    for plugin_id, state in (
        PluginHookJob.objects.filter(
            plugin_id__in=hooked, organization_id=organization.pk, kind=HookJobKind.ORG_REMOVED
        )
        .order_by("plugin_id", "-created_at", "-pk")
        .values_list("plugin_id", "state")
    ):
        latest_state.setdefault(plugin_id, state)
    return sum(
        1 for plugin_id in hooked if latest_state.get(plugin_id) not in SETTLED_ORG_REMOVED_STATES
    )
