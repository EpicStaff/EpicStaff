"""What a node reports about its plugin processes, and the plugin states that follow from it."""

from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone
from epicstaff_plugin.problems import Problem, format_loc
from pydantic import ValidationError
from src.shared.models.plugin_nodes import NodeReport, PlacementReport
from utils.logger import logger

from plugins.databases.backup_records import BackupRecorder, mark_unlisted_deleted
from plugins.databases.database_reports import DatabaseReportRecorder
from plugins.exceptions import InvalidNodeReportError
from plugins.lifecycle.hook_job_service import HookJobService
from plugins.lifecycle.plugin_purge_service import PluginPurgeService
from plugins.lifecycle.upgrade_service import PluginUpgradeService
from plugins.models import (
    PlacementHealth,
    PlacementObservedState,
    PluginDatabase,
    PluginDatabaseBackup,
    PluginNode,
    PluginPlacement,
    PluginState,
    PluginUpgrade,
)
from plugins.models.upgrade import OPEN_UPGRADE_STAGES

REPORT_LOC = "report"


def parse_node_report(raw: bytes) -> NodeReport:
    """Parse a report body, ignoring fields this EpicStaff does not know (a newer node's).

    Raises:
        InvalidNodeReportError: The body is not a valid report; every problem is located
            under `report`.
    """
    try:
        return NodeReport.model_validate_json(raw, extra="ignore")
    except ValidationError as error:
        raise InvalidNodeReportError(
            Problem(format_loc(REPORT_LOC, detail["loc"]), detail["msg"])
            for detail in error.errors(include_url=False)
        ) from None


class NodeReportService:
    """Records a node's report: when it was seen, each placement's process, the plugin states."""

    def record(self, node: PluginNode, report: NodeReport) -> None:
        """Store `report` for `node`, then apply what it means for each plugin.

        A placement of another node, or one that no longer exists, is skipped. The report's
        observations are stored in one transaction that locks placements, then database
        records, then the backups it changes, and never a plugin: each placement's process,
        what it says about the plugin's database (`DatabaseReportRecorder`) and the backups
        its node holds (`BackupRecorder`). A backup inventory marks the recorded backups it
        no longer lists deleted; a report without one marks none.

        Then, for each placement whose plugin may move or has an open upgrade, a transaction
        of its own locks that plugin first and applies the rest (`PluginUpgradeService.
        follow_report`): a process of the current version reported running and healthy
        makes a `provisioning` or `failed` plugin `running`, one reported failed makes a
        `provisioning` or `running` plugin `failed` while no upgrade is open, and an open
        upgrade records the node's progress, fails, or completes. A report about a process
        older than the latest restart or settings change is stored for the Runtime tab but
        moves no state. Each removal it reports is applied on its own
        (`PluginPurgeService.apply_removal_report`). A running hook job of the node whose
        result is overdue fails.
        """
        now = timezone.now()
        by_id = {placement.placement_id: placement for placement in report.placements}
        reported = dict(by_id)
        with transaction.atomic():
            PluginNode.objects.filter(pk=node.pk).update(
                last_seen_at=now, agent_version=report.agent_version
            )
            placements = list(
                PluginPlacement.objects.select_for_update(of=("self",))
                .select_related("plugin__current_package")
                .defer("plugin__current_package__icon_bytes", "plugin__current_package__manifest")
                .filter(node=node, pk__in=list(by_id))
                .order_by("pk")
            )
            databases = _locked_reported_databases(placements, by_id)
            listed_by_database: dict[int, set[str]] = {}
            for placement in placements:
                observed = by_id.pop(placement.pk)
                _store_observation(placement, observed, now)
                record = databases.get(placement.plugin_id)
                if record is None:
                    continue
                listed = _store_database_observations(record, placement, observed, node, now)
                # A list, even an empty one, is every backup the node holds; None (it could not
                # read them, or an older node) says nothing about the ones recorded.
                if observed.backups is not None and record.has_present_backups:
                    listed_by_database[record.pk] = listed
            mark_unlisted_deleted(listed_by_database, now)
        upgrading = _plugins_with_an_open_upgrade(placements)
        upgrades = PluginUpgradeService()
        for placement in placements:
            observed = reported[placement.pk]
            if placement.plugin_id in upgrading or _may_move(placement, observed):
                upgrades.follow_report(node, placement.pk, observed, now)
        purge = PluginPurgeService()
        for removal in report.removals:
            purge.apply_removal_report(node, removal)
        HookJobService().fail_overdue(node)
        if by_id:
            logger.warning(
                "Plugin node {node} reported placements it does not have: {placement_ids}",
                node=node.name,
                placement_ids=sorted(by_id),
            )


def _store_database_observations(
    record: PluginDatabase,
    placement: PluginPlacement,
    observed: PlacementReport,
    node: PluginNode,
    now,
) -> set[str]:
    """Apply the report's database section and backups to `record`; returns the backups it
    listed."""
    identifier = placement.plugin.identifier
    if observed.database is not None:
        DatabaseReportRecorder().apply(record, identifier, observed.database, now)
    return BackupRecorder().apply_inventory(
        record, observed.backups or [], identifier=identifier, node=node
    )


def _locked_reported_databases(
    placements: list[PluginPlacement], by_id: dict[int, PlacementReport]
) -> dict[int, PluginDatabase]:
    """The database records of the plugins whose report has a database section or a backup
    inventory, locked, by plugin id, each with `has_present_backups`; no query when no report
    has one.

    `FOR NO KEY UPDATE`: a backup recorded for the database points at the record, and its
    insert by the node's `migrations` request takes `FOR KEY SHARE` on it.
    """
    plugin_ids = [
        placement.plugin_id
        for placement in placements
        if by_id[placement.pk].database is not None or by_id[placement.pk].backups is not None
    ]
    if not plugin_ids:
        return {}
    return {
        record.plugin_id: record
        for record in PluginDatabase.objects.select_for_update(of=("self",), no_key=True)
        .filter(plugin_id__in=plugin_ids)
        .annotate(
            has_present_backups=Exists(
                PluginDatabaseBackup.objects.filter(
                    plugin_database=OuterRef("pk"), deleted_at__isnull=True
                )
            )
        )
        .order_by("pk")
    }


def _plugins_with_an_open_upgrade(placements: list[PluginPlacement]) -> set[int]:
    """The plugins among the placements' with an open upgrade; no query for no placement."""
    if not placements:
        return set()
    return set(
        PluginUpgrade.objects.filter(
            plugin_id__in=[placement.plugin_id for placement in placements],
            stage__in=OPEN_UPGRADE_STAGES,
        ).values_list("plugin_id", flat=True)
    )


def _may_move(placement: PluginPlacement, observed: PlacementReport) -> bool:
    """Whether the report could move the plugin's state, as the plugin read with its
    placement says; the follow-up checks again under the plugin's lock."""
    plugin = placement.plugin
    package = plugin.current_package
    if package is None:
        return False
    if (
        observed.observed_state == PlacementObservedState.RUNNING
        and observed.health == PlacementHealth.OK
        and observed.observed_version == package.version
    ):
        return plugin.state in (PluginState.PROVISIONING, PluginState.FAILED)
    if observed.observed_state == PlacementObservedState.FAILED:
        return plugin.state in (PluginState.PROVISIONING, PluginState.RUNNING)
    return False


def _store_observation(placement: PluginPlacement, observed: PlacementReport, now) -> None:
    placement.observed_state = observed.observed_state
    placement.observed_version = observed.observed_version
    placement.health = observed.health
    placement.pid = observed.pid
    placement.restarts = observed.restarts
    placement.rss_mb = observed.rss_mb
    placement.last_error = observed.last_error
    placement.log_tail = list(observed.log_tail)
    placement.last_report_at = now
    placement.save(
        update_fields=[
            "observed_state",
            "observed_version",
            "health",
            "pid",
            "restarts",
            "rss_mb",
            "last_error",
            "log_tail",
            "last_report_at",
            "updated_at",
        ]
    )
