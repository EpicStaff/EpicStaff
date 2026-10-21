"""The plugin run guard: a run that uses anything a plugin owns waits for the plugin to be active.

Registered as a run-admission check (`tables.services.run_admission`) in `PluginsConfig.ready()`.
It runs whatever `PLUGINS_ENABLED` says, so switching the platform off never resumes a
suspended plugin's resources. It never logs: the caller decides what a refusal means.
"""

from django.db.models import Exists, OuterRef
from rbac.models import Organization
from tables.services.run_admission import RunSubject
from tables.services.run_resources import RunResourceCollector

from plugins.exceptions import PluginSuspendedError
from plugins.models import GrantState, PluginGrant, PluginOwnedResource
from plugins.runs.owned_resource_index import OwnedResourceIndex


class PluginRunGuard:
    """Refuses a run that uses a row a plugin owns in the organization unless its grant is active.

    Not cached: the fast path is one query, so no grant writer has a cache to invalidate.
    """

    def check(self, subject: RunSubject) -> None:
        """Admit the run, or refuse it naming the plugin.

        Raises:
            PluginSuspendedError: The run reaches a row owned under a grant that is not active,
                or whose grant is gone.
        """
        if not _may_refuse_in(subject.organization_id):
            return
        resources = RunResourceCollector().collect(subject)
        owner = OwnedResourceIndex.for_inactive_grants(
            subject.organization_id, resources
        ).first_owner(resources)
        if owner is not None:
            raise PluginSuspendedError(owner, subject.organization_id)


def _may_refuse_in(organization_id: int) -> bool:
    """Whether any grant of the organization is not active, or any owned row lost its grant.

    One query. Without either, no run of the organization can be refused, so its resources
    are never walked.
    """
    inactive_grants = PluginGrant.objects.filter(org_id=OuterRef("pk")).exclude(
        state=GrantState.ACTIVE
    )
    orphaned_rows = PluginOwnedResource.objects.filter(org_id=OuterRef("pk"), grant__isnull=True)
    return (
        Organization.objects.filter(pk=organization_id)
        .filter(Exists(inactive_grants) | Exists(orphaned_rows))
        .exists()
    )
