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
from plugins.models import GrantState, HookJobKind, HookJobState, PluginGrant, PluginHookJob
from plugins.models.hook_job import GRANT_STEP_HOOK_KINDS, OPEN_HOOK_JOB_STATES

ORGANIZATION_DELETED = "Organization deleted."


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
        organization, by the sweep's own rule (`grants_needing_a_job`). Never raises: a
        failure is logged and counts nothing."""
        try:
            return {"plugin_data": len(grants_needing_a_job(list(_grants_of(organization))))}
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
        organization locked.

        It takes no plugin lock itself, but each job it inserts makes Postgres take `FOR KEY
        SHARE` on that plugin's row at commit. Lifecycle paths lock plugins `FOR NO KEY
        UPDATE` (`lifecycle_locks`), which does not conflict with it, so they never deadlock
        with this sweep over a grant of the organization.
        """
        now = timezone.now()
        grants = list(_grants_of(organization).select_for_update(of=("self",)).order_by("pk"))
        open_steps = list(
            PluginHookJob.objects.select_for_update()
            .filter(
                grant__in=grants, kind__in=GRANT_STEP_HOOK_KINDS, state__in=OPEN_HOOK_JOB_STATES
            )
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
            for grant in grants_needing_a_job(grants)
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


def grants_needing_a_job(grants: list[PluginGrant]) -> list[PluginGrant]:
    """The grants whose plugin must still be asked to delete its data for the organization.

    Every grant of a plugin with the hook, except one already being purged whose own latest
    organization removed job succeeded or was skipped: its data is gone. One query; the
    deletion preview and the sweep both count by it.
    """
    hooked = [grant for grant in grants if has_org_removed_hook(grant.plugin)]
    if not hooked:
        return []
    latest_state: dict[int, str] = {}
    for grant_id, state in (
        PluginHookJob.objects.filter(grant__in=hooked, kind=HookJobKind.ORG_REMOVED)
        .order_by("grant_id", "-created_at", "-pk")
        .values_list("grant_id", "state")
    ):
        latest_state.setdefault(grant_id, state)
    return [
        grant
        for grant in hooked
        if not (
            grant.state == GrantState.PURGING
            and latest_state.get(grant.pk) in SETTLED_ORG_REMOVED_STATES
        )
    ]
