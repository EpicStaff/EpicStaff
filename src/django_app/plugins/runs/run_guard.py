"""The plugin run guard: a run that uses anything a plugin owns waits for the plugin to be active.

Registered as a run-admission check (`tables.services.run_admission`) in `PluginsConfig.ready()`.
It runs whatever `PLUGINS_ENABLED` says, so switching the platform off never resumes a
suspended plugin's resources. It never logs: the caller decides what a refusal means.
"""

from django.db.models import Exists, OuterRef, Q, QuerySet
from rbac.models import Organization
from tables.services.run_admission import RunSubject
from tables.services.run_resources import RunResourceCollector, RunResources

from plugins.exceptions import PluginSuspendedError
from plugins.models import PluginGrant, PluginOwnedResource
from plugins.runs.owned_resource_index import (
    INACTIVE_GRANT_STATES,
    RUN_STOPPING_GRANT_STATES,
    OwnedResourceIndex,
)


class PluginRunGuard:
    """Refuses a run that uses a row a plugin owns in the organization unless its grant is active.

    Not cached: the fast path is one query, so no grant writer has a cache to invalidate.
    """

    def check(self, subject: RunSubject) -> RunResources | None:
        """Admit the run, or refuse it naming the plugin.

        Returns:
            What the run uses, for the re-check; None when the organization has nothing
            that could refuse a run, so nothing was walked.

        Raises:
            PluginSuspendedError: The run reaches a row owned under a grant that is not active,
                or whose grant is gone.
        """
        if not _may_refuse_in(subject.organization_id):
            return None
        resources = RunResourceCollector().collect(subject)
        _refuse_if_owned(subject, resources)
        return resources

    def recheck(self, subject: RunSubject, first_look: RunResources | None) -> None:
        """Refuse the run if a grant owning what it uses stopped being active since `check`.

        A run walked the first time is matched again without a second walk: one or two
        queries. One that was not walked is checked from the start.

        Raises:
            PluginSuspendedError: As `check`.
        """
        if first_look is None:
            self.check(subject)
            return
        _refuse_if_owned(subject, first_look)


def organizations_with_refusable_runs() -> QuerySet:
    """The ids of the organizations where the guard could refuse a run: one query.

    The same rule as the guard's own first step: a grant of the organization that is not
    active owns a row there, or an owned row lost its grant.
    """
    return Organization.objects.filter(_has_refusable_runs()).values_list("pk", flat=True)


def organizations_with_stoppable_runs() -> QuerySet:
    """The ids of the organizations where a running session may have to be stopped: one query.

    The guard's rule, narrowed to the grant states that stop running sessions
    (`RUN_STOPPING_GRANT_STATES`): an organization being upgraded refuses new runs, and lets
    the ones already running finish.
    """
    return Organization.objects.filter(_has_refusable_runs(RUN_STOPPING_GRANT_STATES)).values_list(
        "pk", flat=True
    )


def _refuse_if_owned(subject: RunSubject, resources: RunResources) -> None:
    owner = OwnedResourceIndex.for_inactive_grants(subject.organization_id, resources).first_owner(
        resources
    )
    if owner is not None:
        raise PluginSuspendedError(owner, subject.organization_id)


def _may_refuse_in(organization_id: int) -> bool:
    """Whether the guard could refuse a run of the organization: one query.

    Without a non-active grant that owns a row there, or an owned row that lost its grant, no
    run of the organization can be refused, so its resources are never walked. A grant that
    is still `granting` but owns nothing yet keeps it that way. A tombstone (an owned row
    whose resource is gone) still counts until the sweep removes it, which only costs a walk.
    """
    return Organization.objects.filter(pk=organization_id).filter(_has_refusable_runs()).exists()


def _has_refusable_runs(grant_states: tuple[str, ...] = INACTIVE_GRANT_STATES) -> Q:
    """The rule, as a filter on `Organization`, shared by the per-run and the per-org question:
    a grant of the organization in `grant_states` owns a row there, or an owned row lost its
    grant."""
    rows_of_grant = PluginOwnedResource.objects.filter(
        grant_id=OuterRef("pk"), org_id=OuterRef("org_id")
    )
    inactive_owning_grants = PluginGrant.objects.filter(
        org_id=OuterRef("pk"), state__in=grant_states
    ).filter(Exists(rows_of_grant))
    orphaned_rows = PluginOwnedResource.objects.filter(org_id=OuterRef("pk"), grant__isnull=True)
    return Exists(inactive_owning_grants) | Exists(orphaned_rows)
