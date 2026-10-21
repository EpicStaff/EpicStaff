"""es-agent: UID 10000, no capabilities. Polls the desired state, runs the plugins, reports.

Loops, all in one event loop:

- reconcile, every 5 s: `GET desired-state` with `If-None-Match`, apply a changed one, touch
  the heartbeat file the container's health check reads;
- per placement: converge, and the hooks it lists (see `reconciler`);
- report, every 10 s and right after anything a report shows changed;
- memory watchdog, every 2 s;
- disk watchdog, every 30 s;
- database limits watchdog, every 60 s.

Before any of them, the agent empties the egress proxy's policy files: no proxy password of an
earlier run works any more.
"""

import asyncio
import os
import signal
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from loguru import logger
from src.shared.models.plugin_nodes import (
    CONTRACT_FORMAT,
    NODE_PORT_RANGE,
    NodeReport,
    PlacementReport,
)

from es_plugins import AGENT_VERSION
from es_plugins.agent.django_client import DjangoNodeClient, NodeApiError
from es_plugins.agent.launcher_client import LauncherClient
from es_plugins.agent.port_reservation import PortReservation
from es_plugins.agent.reconciler import AgentServices, Reconciler
from es_plugins.agent.settings import AgentSettings
from es_plugins.database.connections import DatabaseConnector
from es_plugins.database.limits_watchdog import DatabaseLimitsWatchdog
from es_plugins.database.provisioner import DatabaseProvisioner
from es_plugins.egress.policy_writer import EgressPolicyWriter
from es_plugins.health.health_checker import HealthChecker
from es_plugins.hooks.hook_caller import PluginHookCaller
from es_plugins.layout import NodeLayout
from es_plugins.node_disk import NodeDisk
from es_plugins.packages.package_fetcher import PackageFetcher
from es_plugins.process_table import ProcessTable
from es_plugins.supervisor.disk_watchdog import DiskWatchdog
from es_plugins.supervisor.memory_watchdog import MemoryWatchdog

RECONCILE_INTERVAL_SECONDS = 5.0
# Well under the container health check's 30 s staleness window, on its own clock.
HEARTBEAT_INTERVAL_SECONDS = 5.0
REPORT_INTERVAL_SECONDS = 10.0
# Lets the changes of one step (several placements, state and health) go in one report.
REPORT_DEBOUNCE_SECONDS = 0.2


class Reporter:
    """Sends the node's report every 10 s, and soon after `request()`."""

    def __init__(
        self,
        django: DjangoNodeClient,
        placement_reports: Callable[[], list[PlacementReport]],
        *,
        interval: float = REPORT_INTERVAL_SECONDS,
    ):
        self._django = django
        self._placement_reports = placement_reports
        self._interval = interval
        self._requested = asyncio.Event()
        self._failing = False

    def request(self) -> None:
        self._requested.set()

    async def send_once(self) -> None:
        report = NodeReport(
            format=CONTRACT_FORMAT,
            agent_version=AGENT_VERSION,
            reported_at=datetime.now(UTC),
            placements=self._placement_reports(),
        )
        try:
            await self._django.send_report(report)
        except NodeApiError as error:
            if not self._failing:
                logger.warning("Could not send the node report: {}", error)
            self._failing = True
            return
        if self._failing:
            logger.info("Sending node reports again")
        self._failing = False

    async def run(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._requested.wait(), self._interval)
                await asyncio.sleep(REPORT_DEBOUNCE_SECONDS)
            except TimeoutError:
                pass
            self._requested.clear()
            await self.send_once()


class NodeAgent:
    def __init__(
        self,
        settings: AgentSettings,
        layout: NodeLayout,
        django: DjangoNodeClient,
        reconciler: Reconciler,
        reporter: Reporter,
        watchdogs: Sequence[MemoryWatchdog | DiskWatchdog | DatabaseLimitsWatchdog],
    ):
        self._settings = settings
        self._layout = layout
        self._django = django
        self._reconciler = reconciler
        self._reporter = reporter
        self._watchdogs = watchdogs
        self._unreachable = False
        self._warned_node_name: str | None = None

    async def reconcile_once(self) -> None:
        try:
            desired_state = await self._django.fetch_desired_state()
        except NodeApiError as error:
            if not self._unreachable:
                logger.warning("Could not fetch the desired state: {}", error)
            self._unreachable = True
            return
        if self._unreachable:
            logger.info("Fetching the desired state again")
        self._unreachable = False
        if desired_state is None:
            return
        if (
            desired_state.node.name != self._settings.node_name
            and desired_state.node.name != self._warned_node_name
        ):
            logger.warning(
                "django_app calls this node {}, PLUGINS_NODE_NAME says {}",
                desired_state.node.name,
                self._settings.node_name,
            )
            self._warned_node_name = desired_state.node.name
        await self._reconciler.apply(desired_state)

    async def reconcile_forever(self) -> None:
        while True:
            await self.reconcile_once()
            await asyncio.sleep(RECONCILE_INTERVAL_SECONDS)

    async def beat_heartbeat(self) -> None:
        """Touch the heartbeat file on its own clock, so a slow Django never fails the health check."""
        while True:
            os.utime(self._layout.heartbeat_file)
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)

    async def run(self, stop: asyncio.Event) -> None:
        tasks = [
            asyncio.create_task(self.reconcile_forever(), name="reconcile"),
            asyncio.create_task(self.beat_heartbeat(), name="heartbeat"),
            asyncio.create_task(self._reporter.run(), name="report"),
            *(
                asyncio.create_task(watchdog.run(), name=type(watchdog).__name__)
                for watchdog in self._watchdogs
            ),
        ]
        stopped = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait([*tasks, stopped], return_when=asyncio.FIRST_COMPLETED)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Stopping every plugin")
        await self._reconciler.close()
        await self._reporter.send_once()
        for task in done:
            if task is not stopped and task.exception() is not None:
                raise task.exception()


def prepare_agent_directories(layout: NodeLayout) -> None:
    for directory in (
        layout.downloads_directory,
        layout.agent_temporary_directory,
    ):
        directory.mkdir(mode=0o700, exist_ok=True)
    # Readable by the launcher (root, without CAP_DAC_OVERRIDE), which installs code from it.
    layout.unpack_directory.mkdir(mode=0o755, exist_ok=True)


async def run_agent(settings: AgentSettings, layout: NodeLayout) -> None:
    """Run the agent until SIGTERM.

    Raises:
        EgressPolicyError: The egress policy directory is missing or cannot be written.
        PortReservationError: A port of the node's range could not be bound at start-up.
    """
    prepare_agent_directories(layout)
    egress = EgressPolicyWriter(layout.egress_policy_directory)
    await egress.start()
    # Before any plugin runs: from here on no plugin can bind a port of the range.
    ports = PortReservation(range(NODE_PORT_RANGE[0], NODE_PORT_RANGE[1] + 1))
    ports.reserve()
    launcher = LauncherClient(layout.launcher_socket)
    await launcher.connect()
    django = DjangoNodeClient(settings.api_url, settings.node_key)
    health_checker = HealthChecker()
    hook_caller = PluginHookCaller()
    node_disk = NodeDisk(layout.data_root)
    database_connector = DatabaseConnector(settings.database_admin_password)
    reconciler: Reconciler
    reporter = Reporter(django, lambda: reconciler.reports())
    services = AgentServices(
        layout=layout,
        django=django,
        fetcher=PackageFetcher(django, layout.downloads_directory),
        launcher=launcher,
        health_checker=health_checker,
        ports=ports,
        disk=node_disk,
        hook_caller=hook_caller,
        provisioner=DatabaseProvisioner(database_connector),
        egress=egress,
        on_change=reporter.request,
    )
    reconciler = Reconciler(services)
    watchdogs = [
        MemoryWatchdog(ProcessTable(), reconciler.supervisors),
        DiskWatchdog(
            launcher,
            reconciler.supervisors,
            node_disk,
            max_megabytes=settings.disk_megabytes_per_plugin,
            max_files=settings.files_per_plugin,
        ),
        DatabaseLimitsWatchdog(
            database_connector, reconciler.watched_databases, on_change=reporter.request
        ),
    ]
    agent = NodeAgent(settings, layout, django, reconciler, reporter, watchdogs)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signal_number, stop.set)
    logger.info("Node agent {} for node {} started", AGENT_VERSION, settings.node_name)
    try:
        await agent.run(stop)
    finally:
        await health_checker.aclose()
        await hook_caller.aclose()
        await django.aclose()
        launcher.close()
        ports.close()
