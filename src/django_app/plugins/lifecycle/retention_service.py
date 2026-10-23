"""The plugin platform's scheduled maintenance, once a minute: grace periods and deletions.

Each tick stops sessions that slipped past a suspension, ends hook attempts whose node never
answered, starts deleting what a grace period no longer keeps, and moves every deletion in
progress on, within `RETENTION_TICK_BUDGET_SECONDS`. It runs whatever `PLUGINS_ENABLED`
says: a grace period is a promise about EpicStaff's data, so EpicStaff deletes its part even
while plugins are off; a plugin's own data waits until its node runs again.

Several hosts may run it at once. A step waits for a plugin's lock, then takes the rows it
changes with `skip_locked` and checks their state again under the lock, so a row another
tick holds is left to that tick and no two ticks skip each other's plugins.
"""

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime

from django.db import transaction
from django.utils import timezone
from utils.logger import logger

from plugins.audit import log_retention_tick
from plugins.lifecycle.grant_purge_service import GrantPurgeService, PurgeReason
from plugins.lifecycle.hook_job_service import HookJobService
from plugins.lifecycle.lifecycle_locks import lock_plugin
from plugins.lifecycle.plugin_purge_service import PluginPurgeService
from plugins.lifecycle.suspended_run_stopper import SuspendedRunStopper
from plugins.models import (
    GrantState,
    HookJobKind,
    Plugin,
    PluginGrant,
    PluginHookJob,
    PluginState,
    SuspensionCause,
)
from plugins.models.hook_job import OPEN_HOOK_JOB_STATES
from plugins.runs.run_guard import organizations_with_stoppable_runs

RETENTION_TICK_BUDGET_SECONDS = 45


@dataclass
class RetentionReport:
    """How many of each thing one tick did, and how many steps or rows failed."""

    sessions_stopped: int = 0
    hook_attempts_overdue: int = 0
    grants_expired: int = 0
    plugins_expired: int = 0
    grants_purged: int = 0
    resources_purged: int = 0
    resources_failed: int = 0
    plugins_advanced: int = 0
    errors: int = 0


class RetentionService:
    def run(self, now: datetime | None = None) -> RetentionReport:
        """One tick, in this order:

        1. stop the open sessions that must not run now, in every organization where one may
           (a session that started while a suspension committed);
        2. end the attempt of every running hook job whose result is overdue;
        3. begin deleting the data of suspended grants whose grace period is over (a grant
           the plugin's uninstall suspended goes with the plugin instead);
        4. begin deleting uninstalled plugins whose grace period is over;
        5. delete what the plugin owns under each purging grant, oldest first, and delete
           each grant that is done;
        6. move each purging plugin on.

        Steps 5 and 6 stop once the budget is spent and go on at the next tick. A step, a
        grant or a plugin that fails is logged and counted in `errors`, and the tick goes on
        with the rest.
        """
        now = now or timezone.now()
        until = time.monotonic() + RETENTION_TICK_BUDGET_SECONDS
        report = RetentionReport()
        report.sessions_stopped = self._step(
            report,
            "stop sessions",
            lambda: SuspendedRunStopper().stop_in_organizations(
                organizations_with_stoppable_runs()
            ),
        )
        report.hook_attempts_overdue = self._step(
            report, "fail overdue hooks", lambda: HookJobService().fail_overdue()
        )
        report.grants_expired = self._step(
            report, "expire grants", lambda: self._begin_expired_grants(report, now)
        )
        report.plugins_expired = self._step(
            report, "expire plugins", lambda: self._begin_expired_plugins(report, now)
        )
        self._step(report, "purge grants", lambda: self._advance_purging_grants(report, until))
        self._step(report, "purge plugins", lambda: self._advance_purging_plugins(report, until))
        log_retention_tick(asdict(report))
        return report

    @staticmethod
    def _step(report: RetentionReport, name: str, step: Callable[[], int | None]) -> int:
        """Run one step; a failure is logged, counted, and leaves the rest of the tick to run."""
        try:
            return step() or 0
        except Exception:  # one step must not keep the others from running
            logger.exception("Plugin retention step {name} failed", name=name)
            report.errors += 1
            return 0

    @staticmethod
    def _begin_expired_grants(report: RetentionReport, now: datetime) -> int:
        expired = (
            PluginGrant.objects.filter(state=GrantState.SUSPENDED, purge_after__lte=now)
            .exclude(suspension_cause=SuspensionCause.UNINSTALL)
            .order_by("purge_after", "pk")
            .values_list("pk", "plugin__identifier")
        )
        begun = 0
        for grant_id, identifier in list(expired):
            try:
                with transaction.atomic():
                    # Waits for the plugin, so two ticks never skip each other's grants; a
                    # grant another process holds is left to it.
                    plugin = lock_plugin(identifier)
                    if plugin is None:
                        continue
                    grant = (
                        PluginGrant.objects.select_for_update(of=("self",), skip_locked=True)
                        .select_related("org")
                        .filter(pk=grant_id, plugin=plugin, state=GrantState.SUSPENDED)
                        .filter(purge_after__lte=now)
                        .exclude(suspension_cause=SuspensionCause.UNINSTALL)
                        .first()
                    )
                    if grant is None:
                        continue
                    grant.plugin = plugin
                    GrantPurgeService().begin(
                        grant, actor=None, reason=PurgeReason.GRACE_PERIOD_OVER
                    )
                    begun += 1
            except Exception:  # one grant must not keep the others waiting
                logger.exception("Could not begin deleting the data of grant {}", grant_id)
                report.errors += 1
        return begun

    @staticmethod
    def _begin_expired_plugins(report: RetentionReport, now: datetime) -> int:
        expired = Plugin.objects.filter(
            state=PluginState.UNINSTALLING, purge_after__lte=now
        ).order_by("purge_after", "pk")
        begun = 0
        for identifier in list(expired.values_list("identifier", flat=True)):
            try:
                with transaction.atomic():
                    plugin = lock_plugin(identifier)
                    if (
                        plugin is None
                        or plugin.state != PluginState.UNINSTALLING
                        or plugin.purge_after is None
                        or plugin.purge_after > now
                    ):
                        continue
                    PluginPurgeService().begin(
                        plugin, actor=None, reason=PurgeReason.GRACE_PERIOD_OVER
                    )
                    begun += 1
            except Exception:  # one plugin must not keep the others waiting
                logger.exception("Could not begin deleting plugin {}", identifier)
                report.errors += 1
        return begun

    @staticmethod
    def _advance_purging_grants(report: RetentionReport, until: float) -> None:
        grants = list(
            PluginGrant.objects.filter(state=GrantState.PURGING)
            .select_related("plugin", "org")
            .order_by("purge_started_at", "pk")
        )
        waiting = _waiting_for_their_hook(grants)
        service = GrantPurgeService()
        for grant in grants:
            if time.monotonic() >= until:
                return
            try:
                result = service.advance(grant, until)
                report.resources_purged += result.purged
                report.resources_failed += result.failed
                if (grant.plugin_id, grant.org_id) not in waiting and service.finish_if_done(grant):
                    report.grants_purged += 1
            except Exception:  # one grant must not keep the others waiting
                logger.exception("Could not move the deletion of grant {} on", grant.pk)
                report.errors += 1

    @staticmethod
    def _advance_purging_plugins(report: RetentionReport, until: float) -> None:
        service = PluginPurgeService()
        purging = Plugin.objects.filter(state=PluginState.PURGING).order_by(
            "purge_started_at", "pk"
        )
        for plugin in list(purging):
            if time.monotonic() >= until:
                return
            try:
                if service.advance(plugin, until):
                    report.plugins_advanced += 1
            except Exception:  # one plugin must not keep the others waiting
                logger.exception("Could not move the deletion of plugin {} on", plugin.identifier)
                report.errors += 1


def _waiting_for_their_hook(grants: list[PluginGrant]) -> set[tuple[int, int]]:
    """The `(plugin, organization)` pairs of `grants` whose organization removed job is still
    open: those grants cannot be done yet, so they are not checked. One query."""
    if not grants:
        return set()
    return set(
        PluginHookJob.objects.filter(
            kind=HookJobKind.ORG_REMOVED,
            state__in=OPEN_HOOK_JOB_STATES,
            plugin_id__in={grant.plugin_id for grant in grants},
            organization_id__in={grant.org_id for grant in grants},
        ).values_list("plugin_id", "organization_id")
    )
