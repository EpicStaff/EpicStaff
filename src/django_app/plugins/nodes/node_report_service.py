"""What a node reports about its plugin processes, and the plugin states that follow from it."""

from django.db import transaction
from django.utils import timezone
from epicstaff_plugin.problems import Problem, format_loc
from pydantic import ValidationError
from src.shared.models.plugin_nodes import NodeReport, PlacementReport
from utils.logger import logger

from plugins.exceptions import InvalidNodeReportError
from plugins.lifecycle.hook_job_service import HookJobService
from plugins.models import (
    PlacementHealth,
    PlacementObservedState,
    Plugin,
    PluginNode,
    PluginPlacement,
    PluginState,
)

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
        """Store `report` for `node`.

        A placement of another node, or one that no longer exists, is skipped. For the
        current package of a plugin, a process reported running and healthy makes a
        `provisioning` or `failed` plugin `running`; one reported failed makes a
        `provisioning` or `running` plugin `failed`; anything else leaves the state. A report
        about a process older than the latest restart or settings change is stored for the
        Runtime tab but moves no state. A running hook job of the node whose result is
        overdue fails.
        """
        now = timezone.now()
        by_id = {placement.placement_id: placement for placement in report.placements}
        with transaction.atomic():
            PluginNode.objects.filter(pk=node.pk).update(
                last_seen_at=now, agent_version=report.agent_version
            )
            placements = (
                PluginPlacement.objects.select_for_update(of=("self",))
                .select_related("plugin__current_package")
                .defer("plugin__current_package__icon_bytes", "plugin__current_package__manifest")
                .filter(node=node, pk__in=list(by_id))
            )
            for placement in placements:
                observed = by_id.pop(placement.pk)
                _store_observation(placement, observed, now)
                _follow_plugin_state(placement, observed)
        HookJobService().fail_overdue(node)
        if by_id:
            logger.warning(
                "Plugin node {node} reported placements it does not have: {placement_ids}",
                node=node.name,
                placement_ids=sorted(by_id),
            )


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


def _follow_plugin_state(placement: PluginPlacement, observed: PlacementReport) -> None:
    plugin = placement.plugin
    package = plugin.current_package
    if package is None or _is_stale(placement, observed):
        return
    if (
        observed.observed_state == PlacementObservedState.RUNNING
        and observed.health == PlacementHealth.OK
        and observed.observed_version == package.version
    ):
        _move(plugin, (PluginState.PROVISIONING, PluginState.FAILED), PluginState.RUNNING)
    elif observed.observed_state == PlacementObservedState.FAILED:
        _move(plugin, (PluginState.PROVISIONING, PluginState.RUNNING), PluginState.FAILED)


def _is_stale(placement: PluginPlacement, observed: PlacementReport) -> bool:
    """Whether the report is about a process from before the latest restart or settings change.

    Such a report, sent before the node picked up the new desired state, must not move the
    plugin: a `failed` from before a restart would undo the restart. A report without the
    applied values (no process started yet, a download that failed) is current.
    """
    return any(
        applied is not None and applied < current
        for applied, current in (
            (observed.applied_restart_generation, placement.restart_generation),
            (observed.applied_settings_revision, placement.settings_revision),
        )
    )


def _move(plugin: Plugin, from_states: tuple[str, ...], to_state: str) -> None:
    moved = Plugin.objects.filter(pk=plugin.pk, state__in=from_states).update(
        state=to_state, updated_at=timezone.now()
    )
    if moved:
        logger.info(
            "Plugin {identifier} is now {state}, as its node reports",
            identifier=plugin.identifier,
            state=to_state,
        )
