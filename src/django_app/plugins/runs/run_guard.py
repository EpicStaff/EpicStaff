"""The plugin run guard: a run that uses anything a plugin owns waits for the plugin to be active,
and a run a plugin starts sends no secret the plugin may not reference.

Registered as a run-admission check (`tables.services.run_admission`) in `PluginsConfig.ready()`.
It runs whatever `PLUGINS_ENABLED` says, so switching the platform off never resumes a
suspended plugin's resources. It never logs: the caller decides what a refusal means.
"""

from django.db.models import Exists, OuterRef, Q, QuerySet
from rbac.models import Organization
from tables.services.run_admission import RunSubject
from tables.services.run_resources import RunResourceCollector, RunResources
from tables.services.secrets.reference_guard import secret_reference_guard

from plugins.exceptions import PluginSuspendedError
from plugins.identity.principals import PluginServiceAccountPrincipal
from plugins.models import PluginGrant, PluginOwnedResource
from plugins.ownership.request_scope import current_principal
from plugins.runs.owned_resource_index import (
    INACTIVE_GRANT_STATES,
    RUN_STOPPING_GRANT_STATES,
    OwnedResourceIndex,
)


class PluginRunGuard:
    """Refuses a run that uses a row a plugin owns in the organization unless its grant is active,
    and a run a plugin's service account starts whose header markers name a secret the plugin
    may not reference.

    Not cached: the fast path is one query, so no grant writer has a cache to invalidate.
    """

    def check(self, subject: RunSubject) -> RunResources | None:
        """Admit the run, or refuse it.

        A run a plugin starts is always walked: its `epicstaff_secret(<name>)` markers bind by
        name now, so each must name a secret the plugin may reference, as when it wrote them.

        Returns:
            What the run uses, for the re-check; None when nothing was walked: no plugin
            starts the run, and the organization has nothing that could refuse it.

        Raises:
            PluginSuspendedError: The run reaches a row owned under a grant that is not active,
                or whose grant is gone.
            SecretMarkerNotReferenceableError: A plugin starts the run, and one of the run's
                header markers names a secret the plugin may not reference.
        """
        principal = current_principal()
        may_refuse = _may_refuse_in(subject.organization_id)
        if principal is None and not may_refuse:
            return None
        resources = RunResourceCollector().collect(subject)
        _refuse_unreferenceable_markers(principal, resources)
        if may_refuse:
            _refuse_if_owned(subject, resources)
        return resources

    def recheck(self, subject: RunSubject, first_look: RunResources | None) -> None:
        """Refuse the run if what refuses it in `check` came about since.

        A run walked the first time is matched again without a second walk: a few queries.
        One that was not walked is checked from the start.

        Raises:
            PluginSuspendedError: As `check`.
            SecretMarkerNotReferenceableError: As `check`.
        """
        if first_look is None:
            self.check(subject)
            return
        _refuse_unreferenceable_markers(current_principal(), first_look)
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


def _refuse_unreferenceable_markers(
    principal: PluginServiceAccountPrincipal | None, resources: RunResources
) -> None:
    """A plugin's run sends a marker's secret only when the plugin may reference it.

    Without this, a name the plugin wrote could come to mean a secret of the organization (its
    own purged and a person's created under the name) and the run would send that one.
    """
    if principal is not None:
        secret_reference_guard.assert_may_resolve_markers(
            principal=principal, names=resources.secret_marker_names
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
