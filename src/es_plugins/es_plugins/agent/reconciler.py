"""Apply the node's desired state, one controller per placement.

A placement's controller brings it to what EpicStaff wants, and is idempotent: applying the
same desired placement twice does nothing the second time. In order:

1. `desired_state: stopped` stops the process (EpicStaff blocks a plugin that misses a
   required setting this way).
2. A new package is downloaded, checked (sha256, `CONTENTS.json`, signature), unpacked,
   its wheels checked against the interpreter, its venv built and its code installed, and its
   database migrations read. No download and no venv build starts while the node's volume is
   below its install reserve (`NodeDisk`): the placement fails instead.
3. The process is (re)started when it is not running, or `restart_generation`,
   `settings_revision` (upwards), `runtime`, `package` or `database` changed. A start runs,
   in order: fetch the runtime credentials; provision the plugin's database
   (`DatabaseProvisioner`) when the placement has one and its package or database section
   differs from the last provisioning that succeeded in this agent's life; issue or keep the
   plugin's egress proxy password; write the runtime file; spawn.
4. A change of `credentials_revision` alone fetches the credentials and rewrites the runtime
   file; the SDK reloads it. A change of `egress` alone rewrites the proxy's `hosts.json`
   (`Reconciler.apply`), without a restart.

Each controller also has a `HookRunner`, a task of its own, which calls the plugin's lifecycle
hooks (`hook_jobs`) once the process and the runtime file are ready for them; converge goes on
while a hook runs.

A plugin that failed (its package could not be installed, its database could not be provisioned
or its permissions changed outside EpicStaff, it was restarted ten times in a row without a
stable run between them, or it went over its disk cap) stays failed until `restart_generation`
or the package changes. A failure that may pass by itself (django_app or plugins_db not
reachable, the port still in use by a placement being removed) is retried every 30 s. A retry
reuses the runtime credentials the failed attempt fetched, for the same desired placement and
for up to 5 minutes: each fetch mints new service-account keys, and an outage may last hours.

A process stopped for good (stopped, failed, its placement gone, the agent stopping) loses its
egress proxy password.

The agent holds every port of the node's range from start-up (`PortReservation`); the
controller takes its placement's port before anything else and each process serves on that
socket (see `ProcessSupervisor`). A placement whose plugin, UID or port changes is a new
controller, and the old one gives its port back.
"""

import asyncio
import shutil
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from loguru import logger
from src.shared.models.plugin_nodes import (
    MAX_LAST_ERROR_LENGTH,
    DesiredDatabase,
    DesiredPackage,
    DesiredPlacement,
    DesiredRuntime,
    DesiredState,
    PlacementReport,
    RuntimeCredentials,
)

from es_plugins.agent.django_client import DjangoNodeClient, FetchedCredentials, NodeApiError
from es_plugins.agent.launcher_client import LauncherClient, LauncherError
from es_plugins.agent.port_reservation import PortReservation, PortUnavailableError
from es_plugins.database.connections import DatabaseProvisioningError, DatabaseUnreachableError
from es_plugins.database.migration_runner import Migration
from es_plugins.database.placement_database import PlacementDatabase
from es_plugins.database.provisioner import DatabaseProvisioner
from es_plugins.egress.policy_writer import EgressPolicyError, EgressPolicyWriter
from es_plugins.health.health_checker import HealthChecker
from es_plugins.hooks.hook_caller import PluginHookCaller
from es_plugins.hooks.hook_runner import HookRunner, WrittenRuntimeFile
from es_plugins.layout import NodeLayout
from es_plugins.logs.log_collector import LogCollector, RotatingLogFile
from es_plugins.node_disk import NodeDisk, NodeDiskFullError
from es_plugins.packages.package_fetcher import PackageFetcher
from es_plugins.packages.package_unpacker import read_migrations, unpack_backend
from es_plugins.packages.package_verifier import PackageVerificationError, verify_package
from es_plugins.packages.venv_builder import (
    VenvBuildError,
    VenvRequest,
    build_venv,
    venv_is_current,
)
from es_plugins.packages.wheel_tag_check import IncompatibleWheelError
from es_plugins.runtime.process_environment import (
    PlatformCredentials,
    plugin_command,
    plugin_environment,
)
from es_plugins.supervisor.process_supervisor import ProcessSpec, ProcessSupervisor

TRANSIENT_RETRY_SECONDS = 30.0
# The previous service-account key stays valid for 10 minutes after the next fetch mints one.
CREDENTIALS_REUSE_SECONDS = 300.0
PLUGIN_PYTHON_ROOT = Path("/opt/plugin-python")
NICENESS = {"normal": 0, "low": 10}
_PERMANENT_ERRORS = (
    PackageVerificationError,
    IncompatibleWheelError,
    VenvBuildError,
    LauncherError,
    NodeDiskFullError,
    DatabaseProvisioningError,
)


def plugin_interpreter(python: str) -> Path:
    """The node's CPython for a manifest's `backend.python` (`3.12` or `3.13`)."""
    return PLUGIN_PYTHON_ROOT / python / "bin" / f"python{python}"


@dataclass(frozen=True)
class AgentServices:
    """What every placement controller uses; one instance per agent."""

    layout: NodeLayout
    django: DjangoNodeClient
    fetcher: PackageFetcher
    launcher: LauncherClient
    health_checker: HealthChecker
    ports: PortReservation
    disk: NodeDisk
    hook_caller: PluginHookCaller
    provisioner: DatabaseProvisioner
    egress: EgressPolicyWriter
    on_change: Callable[[], None]
    """Called whenever something a report shows changed."""

    interpreter_for: Callable[[str], Path] = plugin_interpreter
    venv_builder: Callable[[VenvRequest], Awaitable[Path]] = build_venv


@dataclass(frozen=True)
class _StartedWith:
    """What the running process was started from; a change of any field restarts it."""

    restart_generation: int
    runtime: DesiredRuntime
    package: DesiredPackage
    database: DesiredDatabase | None

    @classmethod
    def of(cls, placement: DesiredPlacement) -> "_StartedWith":
        return cls(
            placement.restart_generation, placement.runtime, placement.package, placement.database
        )


@dataclass(frozen=True)
class _FetchedFor:
    """Runtime credentials, the desired placement they were fetched for, and when."""

    placement: DesiredPlacement
    fetched: FetchedCredentials
    fetched_at: float


class PlacementController:
    def __init__(self, placement: DesiredPlacement, services: AgentServices):
        self._desired = placement
        self._services = services
        self._wake = asyncio.Event()
        self._log_collector = LogCollector(
            placement.plugin_identifier,
            RotatingLogFile(services.layout.plugin_logs(placement.plugin_identifier)),
        )
        # The placement's port, taken from the agent's reservation before anything else; None
        # until then.
        self._taken_port: int | None = None
        self.supervisor = ProcessSupervisor(
            placement.plugin_identifier,
            placement.runtime.unix_uid,
            services.launcher,
            services.health_checker,
            self._log_collector,
            self._process_changed,
        )
        self._hook_runner = HookRunner(
            placement, self.supervisor, services.django, services.hook_caller
        )
        self._installed_package: DesiredPackage | None = None
        self._venv: Path | None = None
        self._migrations: tuple[Migration, ...] = ()
        # None until the node first tries to provision the placement's database.
        self._database: PlacementDatabase | None = None
        self._provisioned_for: tuple[DesiredPackage, DesiredDatabase] | None = None
        self._background_tasks: set[asyncio.Task] = set()
        self._started_with: _StartedWith | None = None
        self._applied_credentials_revision: str | None = None
        # Kept only while a converge that fetched them is being retried after a transient error.
        self._retry_credentials: _FetchedFor | None = None
        self._running_settings_revision: int | None = None
        self._failed_for: tuple[int, DesiredPackage] | None = None
        self._task: asyncio.Task | None = None

    @property
    def desired(self) -> DesiredPlacement:
        return self._desired

    @property
    def database(self) -> PlacementDatabase | None:
        return self._database

    def start(self) -> None:
        self._wake.set()
        self._task = asyncio.create_task(
            self._loop(), name=f"placement-{self._desired.placement_id}"
        )
        self._hook_runner.start()

    def update(self, placement: DesiredPlacement) -> None:
        if placement != self._desired:
            self._desired = placement
            self._wake.set()
            self._hook_runner.update(placement)

    async def close(self) -> None:
        """Stop the controller and the plugin's process, and give its port back."""
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        # Together: a hook call in progress is reported while the process stops.
        await asyncio.gather(self._hook_runner.close(), self.supervisor.stop())
        await self._withdraw_egress()
        self._log_collector.close()
        if self._taken_port is not None:
            self._services.ports.give_back(self._taken_port, self._desired.placement_id)
            self._taken_port = None

    def report(self) -> PlacementReport:
        status = self.supervisor.status()
        last_error = status.last_error[:MAX_LAST_ERROR_LENGTH] if status.last_error else None
        started = self._started_with
        return PlacementReport(
            placement_id=self._desired.placement_id,
            observed_state=status.observed_state,
            observed_version=status.version,
            health=status.health,
            pid=status.pid,
            restarts=status.restarts,
            rss_mb=status.rss_mb,
            last_error=last_error,
            log_tail=self._log_collector.tail if status.observed_state == "failed" else [],
            applied_credentials_revision=self._applied_credentials_revision,
            applied_settings_revision=self._running_settings_revision,
            applied_restart_generation=started.restart_generation if started else None,
            database=self._database.report() if self._database is not None else None,
        )

    async def fail_database(self, error: str) -> None:
        """The database's permissions changed outside EpicStaff: stop the plugin, fail it.

        It stays failed until a restart, which provisions (and checks) the database again.
        """
        if self._database is not None:
            self._database.failed(error)
        self._provisioned_for = None
        await self._fail(self._desired, error)

    def _process_changed(self) -> None:
        self._services.on_change()
        self._hook_runner.notice_change()
        if self.supervisor.failed:
            # The supervisor gave up on its own (too many restarts, over its disk cap).
            self._in_background(self._withdraw_egress_if_still_failed())

    async def _loop(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            retry_after = await self._converge_safely(self._desired)
            if retry_after is not None:
                asyncio.get_running_loop().call_later(retry_after, self._wake.set)

    async def _converge_safely(self, desired: DesiredPlacement) -> float | None:
        """Converge once; return seconds after which to try again, or None."""
        retry_after = await self._converge_once(desired)
        if retry_after is None:
            self._retry_credentials = None
        return retry_after

    async def _converge_once(self, desired: DesiredPlacement) -> float | None:
        try:
            await self._converge(desired)
        except PortUnavailableError as error:
            # Normally a placement that is being removed still uses the port: retry.
            logger.warning("Plugin {}: {}", desired.plugin_identifier, error)
            self.supervisor.note_error(str(error))
            return TRANSIENT_RETRY_SECONDS
        except NodeApiError as error:
            if error.transient:
                logger.warning("Plugin {}: {}", desired.plugin_identifier, error)
                self.supervisor.note_error(str(error))
                return TRANSIENT_RETRY_SECONDS
            await self._fail(desired, str(error))
        except DatabaseUnreachableError as error:
            self.supervisor.note_error(str(error))
            return TRANSIENT_RETRY_SECONDS
        except _PERMANENT_ERRORS as error:
            await self._fail(desired, str(error))
        except Exception as error:
            # The agent supervises every plugin: one plugin's unexpected error must not stop it.
            logger.exception("Plugin {}: unexpected error", desired.plugin_identifier)
            self.supervisor.note_error(f"internal error of the node agent: {error}")
            return TRANSIENT_RETRY_SECONDS
        return None

    async def _converge(self, desired: DesiredPlacement) -> None:
        supervisor = self.supervisor
        if desired.desired_state == "stopped":
            await supervisor.stop()
            await self._withdraw_egress()
            return
        if self._failed_for is not None:
            if self._failed_for == (desired.restart_generation, desired.package):
                return
            self._failed_for = None
        started = self._started_with
        if (
            supervisor.failed
            and started is not None
            and (started.restart_generation, started.package)
            == (desired.restart_generation, desired.package)
        ):
            return
        self._take_port(desired)
        if self._installed_package != desired.package:
            await self._install(desired)
        must_start = (
            not supervisor.watching
            or started is None
            or started != _StartedWith.of(desired)
            # The settings revision the *running* process started with, not the last one written:
            # a credentials-only rewrite must not mask a later settings change.
            or self._running_settings_revision is None
            or desired.settings_revision > self._running_settings_revision
        )
        if not must_start:
            if desired.credentials_revision != self._applied_credentials_revision:
                await self._write_runtime_file(desired, await self._fetch_credentials(desired))
            self._services.on_change()
            return
        fetched = await self._fetch_credentials(desired)
        await self._provision_database(desired, fetched.credentials)
        egress_password = await self._services.egress.issue_password(desired.plugin_identifier)
        await self._write_runtime_file(desired, fetched)
        if self._failed_for is not None:
            # The limits watchdog failed the placement while this start was under way.
            return
        await supervisor.start(self._process_spec(desired, fetched.credentials, egress_password))
        self._started_with = _StartedWith.of(desired)
        self._running_settings_revision = fetched.credentials.settings_revision
        self._services.on_change()

    def _take_port(self, desired: DesiredPlacement) -> None:
        """Take the placement's port from the agent's reservation and hand it to the supervisor.

        Raises:
            PortUnavailableError: The port is not the node's, or another placement still uses it.
        """
        if self._taken_port is not None:
            return
        port = desired.runtime.port
        self.supervisor.set_listen_fd(self._services.ports.take(port, desired.placement_id))
        self._taken_port = port

    async def _install(self, desired: DesiredPlacement) -> None:
        services = self._services
        layout = services.layout
        identifier = desired.plugin_identifier
        uid = desired.runtime.unix_uid
        version = desired.package.version
        self.supervisor.show_phase("downloading")
        if not services.fetcher.holds(desired.package):
            services.disk.check_room_for_install()
        package_path = await services.fetcher.fetch(desired.package)
        archive = await asyncio.to_thread(verify_package, package_path, desired)
        migrations = await asyncio.to_thread(read_migrations, package_path, archive)
        self.supervisor.show_phase("building")
        unpacked = layout.unpacked_package(identifier, version)
        await asyncio.to_thread(unpack_backend, package_path, archive, unpacked)
        try:
            await services.launcher.prepare_plugin(identifier, uid)
            venv = layout.plugin_venv(identifier, version)
            request = VenvRequest(
                interpreter=services.interpreter_for(desired.runtime.python),
                venv=venv,
                backend=unpacked / "backend",
                source_path=layout.plugin_source(identifier, version),
                temporary_directory=layout.agent_temporary_directory,
            )
            if not venv_is_current(request):
                services.disk.check_room_for_install()
            await services.venv_builder(request)
            await services.launcher.install_code(identifier, uid, version)
        finally:
            await asyncio.to_thread(shutil.rmtree, unpacked, True)
        self._installed_package = desired.package
        self._venv = venv
        self._migrations = migrations
        logger.info("Installed plugin {} {}", identifier, version)

    async def _fetch_credentials(self, desired: DesiredPlacement) -> FetchedCredentials:
        """The placement's runtime credentials, fetched unless a retry may reuse the last ones.

        A retry after a transient failure reuses what the failed attempt fetched, when it was for
        the same desired placement (so no revision changed) less than
        `CREDENTIALS_REUSE_SECONDS` ago.
        """
        kept = self._retry_credentials
        if (
            kept is not None
            and kept.placement == desired
            and time.monotonic() - kept.fetched_at < CREDENTIALS_REUSE_SECONDS
        ):
            return kept.fetched
        fetched = await self._services.django.fetch_runtime_credentials(desired.placement_id)
        self._retry_credentials = _FetchedFor(desired, fetched, time.monotonic())
        return fetched

    async def _provision_database(
        self, desired: DesiredPlacement, credentials: RuntimeCredentials
    ) -> None:
        """Provision the placement's database unless this package and section already are.

        Raises:
            DatabaseUnreachableError: plugins_db cannot be reached; reported `provisioning`.
            DatabaseProvisioningError: It failed for good; reported `failed`.
            NodeApiError: django_app sent no app password for a placement with a database.
        """
        wanted = desired.database
        if wanted is None:
            self._database = None
            self._provisioned_for = None
            return
        if self._provisioned_for == (desired.package, wanted):
            return
        if credentials.database is None:
            raise NodeApiError(
                "django_app sent no database credentials for a placement with a database",
                transient=False,
            )
        database = self._database
        if database is None or database.desired.installation_id != wanted.installation_id:
            database = self._database = PlacementDatabase(desired.plugin_identifier, wanted)
        async with database.lock:
            database.provisioning(wanted)
            self._services.on_change()
            try:
                outcome = await self._services.provisioner.ensure(
                    desired.plugin_identifier,
                    wanted,
                    credentials.database.app_password,
                    self._migrations,
                )
            except DatabaseUnreachableError as error:
                database.provisioning(wanted, str(error))
                raise
            except DatabaseProvisioningError as error:
                database.failed(str(error))
                raise
            database.provisioned(outcome)
        self._provisioned_for = (desired.package, wanted)
        self._services.on_change()

    async def _write_runtime_file(
        self, desired: DesiredPlacement, fetched: FetchedCredentials
    ) -> None:
        """Write the fetched runtime file.

        Records only the written credentials revision here; the settings revision the process
        runs with is recorded when it is (re)started, so a credentials-only rewrite that
        happens to carry newer settings does not mask the restart those settings need.
        """
        services = self._services
        await services.launcher.prepare_plugin(desired.plugin_identifier, desired.runtime.unix_uid)
        await services.launcher.write_runtime_file(
            desired.plugin_identifier, desired.runtime.unix_uid, fetched.runtime_file
        )
        credentials = fetched.credentials
        self._applied_credentials_revision = credentials.credentials_revision
        self._hook_runner.runtime_file_written(
            WrittenRuntimeFile(
                credentials_revision=credentials.credentials_revision,
                organization_ids=frozenset(
                    int(organization_id)
                    for organization_id in credentials.runtime_file.service_accounts
                ),
            )
        )

    def _process_spec(
        self, desired: DesiredPlacement, credentials: RuntimeCredentials, egress_password: str
    ) -> ProcessSpec:
        database_password = None
        if desired.database is not None and credentials.database is not None:
            database_password = credentials.database.app_password
        return ProcessSpec(
            plugin=desired.plugin_identifier,
            uid=desired.runtime.unix_uid,
            version=desired.package.version,
            argv=plugin_command(self._venv),
            environment=plugin_environment(
                self._services.layout,
                desired,
                self._venv,
                credentials.runtime_file,
                PlatformCredentials(egress_password, database_password),
            ),
            nice=NICENESS[desired.runtime.cpu_priority],
            port=desired.runtime.port,
            memory_mb=desired.runtime.memory_mb,
        )

    async def _fail(self, desired: DesiredPlacement, error: str) -> None:
        logger.error("Plugin {} failed: {}", desired.plugin_identifier, error)
        await self.supervisor.stop()
        self._failed_for = (desired.restart_generation, desired.package)
        self.supervisor.fail(error)
        await self._withdraw_egress()

    async def _withdraw_egress(self) -> None:
        """The process is stopped for good: its proxy password stops working."""
        egress = self._services.egress
        identifier = self._desired.plugin_identifier
        if not egress.forget_password(identifier):
            return
        try:
            await egress.write_passwords()
        except EgressPolicyError as error:
            # Forgotten already: the next write of the password file leaves it out.
            logger.error("Plugin {}: {}", identifier, error)

    async def _withdraw_egress_if_still_failed(self) -> None:
        # Runs a moment after the failure: a restart since then has issued a password to keep.
        if self.supervisor.failed:
            await self._withdraw_egress()

    def _in_background(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)


class Reconciler:
    """Keeps one `PlacementController` per placement of the desired state."""

    def __init__(self, services: AgentServices):
        self._services = services
        self._controllers: dict[int, PlacementController] = {}

    async def apply(self, desired_state: DesiredState) -> None:
        """Run what `desired_state` names, beginning with the egress proxy's host lists.

        Raises:
            EgressPolicyError: `hosts.json` could not be written. The agent stops rather than
                leave the proxy an allow-list it cannot narrow.
        """
        await self._services.egress.write_hosts(
            {
                placement.plugin_identifier: placement.egress.hosts
                for placement in desired_state.placements
            }
        )
        wanted = {placement.placement_id: placement for placement in desired_state.placements}
        for placement_id in [known for known in self._controllers if known not in wanted]:
            await self._controllers.pop(placement_id).close()
        for placement in desired_state.placements:
            controller = self._controllers.get(placement.placement_id)
            if controller is not None and _identity(controller.desired) != _identity(placement):
                # A changed plugin, UID or port is a new process on a new socket: the old
                # controller stops its process and releases its port first.
                await self._controllers.pop(placement.placement_id).close()
                controller = None
            if controller is None:
                controller = PlacementController(placement, self._services)
                self._controllers[placement.placement_id] = controller
                controller.start()
            else:
                controller.update(placement)
        self._services.fetcher.prune(placement.package for placement in desired_state.placements)
        self._services.on_change()

    def supervisors(self) -> list[ProcessSupervisor]:
        return [controller.supervisor for controller in self._controllers.values()]

    def watched_databases(self) -> list[PlacementController]:
        """The controllers whose placement has a database, for the limits watchdog."""
        return [
            controller
            for controller in self._controllers.values()
            if controller.database is not None
        ]

    def reports(self) -> list[PlacementReport]:
        return [controller.report() for controller in self._controllers.values()]

    async def close(self) -> None:
        """Stop every plugin, all at once: each gets the same few seconds to finish."""
        await asyncio.gather(*(controller.close() for controller in self._controllers.values()))
        self._controllers.clear()


def _identity(placement: DesiredPlacement) -> tuple[str, int, int]:
    return placement.plugin_identifier, placement.runtime.unix_uid, placement.runtime.port
