"""The plugin platform's scheduled maintenance, once a minute: grace periods and deletions.

Each tick stops sessions that slipped past a suspension, ends hook attempts whose node never
answered, starts deleting what a grace period no longer keeps, and moves every deletion in
progress on, within `RETENTION_TICK_BUDGET_SECONDS`. It runs whatever `PLUGINS_ENABLED`
says: a grace period is a promise about EpicStaff's data, so EpicStaff deletes its part even
while plugins are off; a plugin's own data waits until its node runs again.

Several hosts may run it at once. Every step locks what it changes with `skip_locked` and
checks the state again under the lock, so a row another tick holds is left to that tick.
"""

import time
from dataclasses import asdict, dataclass
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from plugins.audit import log_retention_tick
from plugins.lifecycle.grant_purge_service import GrantPurgeService, PurgeReason
from plugins.lifecycle.hook_job_service import HookJobService
from plugins.lifecycle.lifecycle_locks import lock_plugin
from plugins.lifecycle.plugin_purge_service import PluginPurgeService
from plugins.lifecycle.suspended_run_stopper import SuspendedRunStopper
from plugins.models import GrantState, Plugin, PluginGrant, PluginState, SuspensionCause
from plugins.runs.run_guard import organizations_with_refusable_runs

RETENTION_TICK_BUDGET_SECONDS = 45


@dataclass
class RetentionReport:
    """How many of each thing one tick did."""

    sessions_stopped: int = 0
    hook_attempts_overdue: int = 0
    grants_expired: int = 0
    plugins_expired: int = 0
    grants_purged: int = 0
    resources_purged: int = 0
    resources_failed: int = 0
    plugins_advanced: int = 0


class RetentionService:
    def run(self, now: datetime | None = None) -> RetentionReport:
        """One tick, in this order:

        1. stop the open sessions the run guard would refuse now, in every organization
           where it may refuse one (a session that started while a suspension committed);
        2. end the attempt of every running hook job whose result is overdue;
        3. begin deleting the data of suspended grants whose grace period is over (a grant
           the plugin's uninstall suspended goes with the plugin instead);
        4. begin deleting uninstalled plugins whose grace period is over;
        5. delete what the plugin owns under each purging grant, oldest first, and delete
           each grant that is done;
        6. move each purging plugin on.

        Steps 5 and 6 stop once the budget is spent and go on at the next tick.
        """
        now = now or timezone.now()
        until = time.monotonic() + RETENTION_TICK_BUDGET_SECONDS
        report = RetentionReport()
        stopper = SuspendedRunStopper()
        for organization_id in organizations_with_refusable_runs().order_by("pk"):
            report.sessions_stopped += stopper.stop_in_organization(organization_id)
        report.hook_attempts_overdue = HookJobService().fail_overdue()
        report.grants_expired = self._begin_expired_grants(now)
        report.plugins_expired = self._begin_expired_plugins(now)
        self._advance_purging_grants(report, until)
        self._advance_purging_plugins(report, until)
        log_retention_tick(asdict(report))
        return report

    @staticmethod
    def _begin_expired_grants(now: datetime) -> int:
        expired = (
            PluginGrant.objects.filter(state=GrantState.SUSPENDED, purge_after__lte=now)
            .exclude(suspension_cause=SuspensionCause.UNINSTALL)
            .order_by("purge_after", "pk")
            .values_list("pk", "plugin__identifier")
        )
        begun = 0
        for grant_id, identifier in list(expired):
            with transaction.atomic():
                plugin = lock_plugin(identifier, skip_locked=True)
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
                GrantPurgeService().begin(grant, actor=None, reason=PurgeReason.GRACE_PERIOD_OVER)
                begun += 1
        return begun

    @staticmethod
    def _begin_expired_plugins(now: datetime) -> int:
        expired = Plugin.objects.filter(
            state=PluginState.UNINSTALLING, purge_after__lte=now
        ).order_by("purge_after", "pk")
        begun = 0
        for identifier in list(expired.values_list("identifier", flat=True)):
            with transaction.atomic():
                plugin = lock_plugin(identifier, skip_locked=True)
                if (
                    plugin is None
                    or plugin.state != PluginState.UNINSTALLING
                    or plugin.purge_after is None
                    or plugin.purge_after > now
                ):
                    continue
                PluginPurgeService().begin(plugin, actor=None, reason=PurgeReason.GRACE_PERIOD_OVER)
                begun += 1
        return begun

    @staticmethod
    def _advance_purging_grants(report: RetentionReport, until: float) -> None:
        purging = (
            PluginGrant.objects.filter(state=GrantState.PURGING)
            .select_related("plugin", "org")
            .order_by("purge_started_at", "pk")
        )
        service = GrantPurgeService()
        for grant in list(purging):
            if time.monotonic() >= until:
                return
            result = service.advance(grant, until)
            report.resources_purged += result.purged
            report.resources_failed += result.failed
            if service.finish_if_done(grant):
                report.grants_purged += 1

    @staticmethod
    def _advance_purging_plugins(report: RetentionReport, until: float) -> None:
        service = PluginPurgeService()
        purging = Plugin.objects.filter(state=PluginState.PURGING).order_by(
            "purge_started_at", "pk"
        )
        for plugin in list(purging):
            if time.monotonic() >= until:
                return
            if service.advance(plugin, until):
                report.plugins_advanced += 1
