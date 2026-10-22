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

While the desired placement has an `upgrade`, the controller follows its stage (see
`es_plugins.agent.upgrade`): in `preparing` it keeps the running version as above and installs the
target next to it; in `maintenance` it only drains, stops and backs up; in `migrating` the
placement's package is the target and the start above runs its migrations. A desired `restore`
replaces the database and starts nothing. With no upgrade open, every version but the desired
one is deleted once it is installed. The desired placement's `backups_to_delete` are deleted
(`BackupStore`), and the report lists every complete backup.

A placement in the desired state's `removals` has its controller closed first, like any placement
that left `placements`; `PlacementRemover` then drops its database and deletes everything the node
keeps for it (see `es_plugins.agent.removal`), and the node's report carries the removal's state.

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
from pydantic import ValidationError
from src.shared.models.plugin_nodes import (
    MAX_LAST_ERROR_LENGTH,
    BackupFileReport,
    DesiredDatabase,
    DesiredPackage,
    DesiredPlacement,
    DesiredRemoval,
    DesiredRuntime,
    DesiredState,
    PlacementReport,
    RemovalReport,
    RuntimeCredentials,
    UpgradeStep,
)

from es_plugins.agent.agent_trees import prune_agent_trees
from es_plugins.agent.django_client import DjangoNodeClient, FetchedCredentials, NodeApiError
from es_plugins.agent.launcher_client import LauncherClient, LauncherError
from es_plugins.agent.port_reservation import PortReservation, PortUnavailableError
from es_plugins.agent.removal import PlacementRemover, RemovalServices
from es_plugins.agent.upgrade import (
    PlacementRestore,
    UpgradeServices,
    UpgradeStages,
    UpgradeStepError,
)
from es_plugins.database.backup_service import BackupService
from es_plugins.database.backup_store import BackupStore
from es_plugins.database.connections import DatabaseProvisioningError, DatabaseUnreachableError
from es_plugins.database.drop_sequence import DatabaseDropper
from es_plugins.database.migration_runner import Migration
from es_plugins.database.placement_database import PlacementDatabase
from es_plugins.database.provisioner import DatabaseProvisioner
from es_plugins.database.restore_service import RestoreService
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
    dropper: DatabaseDropper
    egress: EgressPolicyWriter
    backup_store: BackupStore
    backups: BackupService
    restores: RestoreService
    on_change: Callable[[], None]
    """Called whenever something a report shows changed."""

    request_desired_state: Callable[[], None]
    """Fetch the desired state now, not at the next poll (an upgrade was granted its next stage)."""

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
class _Installation:
    """A version of the plugin installed in this agent's life."""

    venv: Path
    migrations: tuple[Migration, ...]


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
        upgrade_services = UpgradeServices(
            django=services.django,
            disk=services.disk,
            backups=services.backups,
            backup_store=services.backup_store,
            restores=services.restores,
            request_desired_state=services.request_desired_state,
            on_change=services.on_change,
        )
        self._upgrade = UpgradeStages(placement.plugin_identifier, upgrade_services, self)
        self._restore = PlacementRestore(placement.plugin_identifier, upgrade_services, self)
        # The versions installed in this agent's life: the running one, and an upgrade's target.
        self._installed: dict[DesiredPackage, _Installation] = {}
        self._pruned_for: DesiredPackage | None = None
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
        self._failure: str | None = None
        self._unreportable_backups = False
        self._task: asyncio.Task | None = None
        self._converging: asyncio.Task | None = None

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
            if self._converging is not None and self._upgrade.moot(placement):
                # A download, build, drain or backup for a stage EpicStaff no longer asks for
                # (cancelled, or a newer target): cut it short.
                self._converging.cancel()
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
        desired = self._desired
        return PlacementReport(
            placement_id=desired.placement_id,
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
            upgrade=self._upgrade.report(desired),
            restore=self._restore.report(desired),
            backups=self._backup_reports(),
        )

    async def fail_database(self, error: str) -> None:
        """The database's permissions changed outside EpicStaff: stop the plugin, fail it.

        It stays failed until a restart, which provisions (and checks) the database again.
        """
        if self._database is not None:
            self._database.failed(error)
        self._provisioned_for = None
        await self._fail(self._desired, error)

    # What the upgrade stages use (`UpgradeHost`).

    async def install(
        self,
        package: DesiredPackage,
        runtime: DesiredRuntime,
        on_step: Callable[[UpgradeStep], None],
    ) -> None:
        """Download, verify and build `package` into its own version directories, unless done.

        The process is not touched, so an upgrade's target is installed next to the running
        version. No download and no venv build starts below the install reserve.
        """
        if package in self._installed:
            return
        services = self._services
        layout = services.layout
        identifier = self._desired.plugin_identifier
        uid = runtime.unix_uid
        version = package.version
        on_step("download")
        if not services.fetcher.holds(package):
            services.disk.check_room_for_install()
        package_path = await services.fetcher.fetch(package)
        on_step("verify")
        archive = await asyncio.to_thread(
            verify_package, package_path, identifier, package, runtime
        )
        migrations = await asyncio.to_thread(read_migrations, package_path, archive)
        on_step("build")
        unpacked = layout.unpacked_package(identifier, version)
        await asyncio.to_thread(unpack_backend, package_path, archive, unpacked)
        try:
            await services.launcher.prepare_plugin(identifier, uid)
            venv = layout.plugin_venv(identifier, version)
            request = VenvRequest(
                interpreter=services.interpreter_for(runtime.python),
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
        self._installed[package] = _Installation(venv=venv, migrations=migrations)
        # Another version is on the node now: once no upgrade is open, prune again.
        self._pruned_for = None
        logger.info("Installed plugin {} {}", identifier, version)

    async def drain_hooks(self) -> None:
        await self._hook_runner.drain()

    async def stop_for_upgrade(self) -> None:
        await self.supervisor.stop()
        remaining = await self._services.launcher.kill_uid(self._desired.runtime.unix_uid)
        if remaining:
            raise UpgradeStepError(
                f"{len(remaining)} process(es) of the plugin's user id survived being killed"
            )
        await self._withdraw_egress()

    def database_lock(self, database: DesiredDatabase) -> asyncio.Lock:
        record = self._database
        if record is not None and record.desired.installation_id == database.installation_id:
            return record.lock
        # Not provisioned in this agent's life: neither provisioning nor the watchdog has it.
        return asyncio.Lock()

    def database_for(self, database: DesiredDatabase) -> PlacementDatabase:
        record = self._database
        if record is None or record.desired.installation_id != database.installation_id:
            record = self._database = PlacementDatabase(self._desired.plugin_identifier, database)
        return record

    def database_replaced(self) -> None:
        self._provisioned_for = None

    async def app_password(self, desired: DesiredPlacement) -> str:
        fetched = await self._fetch_credentials(desired)
        if fetched.credentials.database is None:
            raise NodeApiError(
                "django_app sent no database credentials for a placement with a database",
                transient=False,
            )
        return fetched.credentials.database.app_password

    # The controller's own loop.

    def _process_changed(self) -> None:
        self._services.on_change()
        self._hook_runner.notice_change()
        if self.supervisor.failed:
            # The supervisor gave up on its own (too many restarts, over its disk cap).
            self._in_background(self._withdraw_egress_if_still_failed())
            desired = self._desired
            started = self._started_with
            if (
                _upgrade_stage(desired) == "migrating"
                and started is not None
                and started.package == desired.upgrade.target
            ):
                status = self.supervisor.status()
                self._upgrade.fail(
                    desired, status.last_error or "the new version did not start", step="start"
                )

    async def _loop(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            self._converging = asyncio.create_task(self._converge_safely(self._desired))
            try:
                retry_after = await self._converging
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
                # `update` cut short upgrade work the desired state no longer asks for.
                self._wake.set()
                continue
            finally:
                self._converging = None
            if retry_after is not None:
                asyncio.get_running_loop().call_later(retry_after, self._wake.set)

    async def _converge_safely(self, desired: DesiredPlacement) -> float | None:
        """Converge once; return seconds after which to try again, or None."""
        retry_after = await self._converge_once(desired)
        if retry_after is None:
            self._retry_credentials = None
        return retry_after

    async def _converge_once(self, desired: DesiredPlacement) -> float | None:
        stage = _upgrade_stage(desired)
        # EpicStaff marks a stage failed once the node reported it so: none of its steps runs
        # again, after an agent restart too, until a Retry or a newer target. A restore still runs.
        failed = desired.upgrade is not None and desired.upgrade.failed
        if stage == "maintenance":
            return None if failed else await self._upgrade.maintain(desired)
        if desired.restore is not None:
            return await self._restore.run(desired)
        if stage == "migrating" and failed:
            # Its steps are the migrations and the start: the process stays stopped.
            return None
        retry_after = await self._converge_running(desired)
        if stage == "preparing":
            # The running version is kept running either way.
            if failed:
                return retry_after
            return _sooner(retry_after, await self._upgrade.prepare(desired))
        if stage is None and retry_after is None:
            await self._prune(desired)
        return retry_after

    async def _converge_running(self, desired: DesiredPlacement) -> float | None:
        """Bring the process to the desired package; see the module. Upgrade-stage work aside."""
        try:
            await self._converge(desired)
        except PortUnavailableError as error:
            # Normally a placement that is being removed still uses the port: retry.
            logger.warning("Plugin {}: {}", desired.plugin_identifier, error)
            self._note_retry(desired, str(error))
            return TRANSIENT_RETRY_SECONDS
        except NodeApiError as error:
            if error.transient:
                logger.warning("Plugin {}: {}", desired.plugin_identifier, error)
                self._note_retry(desired, str(error))
                return TRANSIENT_RETRY_SECONDS
            await self._fail(desired, str(error))
        except DatabaseUnreachableError as error:
            self._note_retry(desired, str(error))
            return TRANSIENT_RETRY_SECONDS
        except _PERMANENT_ERRORS as error:
            await self._fail(desired, str(error))
        except Exception as error:
            # The agent supervises every plugin: one plugin's unexpected error must not stop it.
            logger.exception("Plugin {}: unexpected error", desired.plugin_identifier)
            self._note_retry(desired, f"internal error of the node agent: {error}")
            return TRANSIENT_RETRY_SECONDS
        return None

    def _note_retry(self, desired: DesiredPlacement, error: str) -> None:
        self.supervisor.note_error(error)
        if _upgrade_stage(desired) == "migrating":
            self._upgrade.retrying(desired, error)

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
        await self.install(desired.package, desired.runtime, self._show_install_phase)
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
        migrating = _upgrade_stage(desired) == "migrating"
        fetched = await self._fetch_credentials(desired)
        if migrating:
            self._upgrade.step(desired, "migrate")
        await self._provision_database(desired, fetched.credentials)
        if migrating:
            self._upgrade.step(desired, "start")
        egress_password = await self._services.egress.issue_password(desired.plugin_identifier)
        await self._write_runtime_file(desired, fetched)
        if self._failed_for is not None:
            # The limits watchdog failed the placement while this start was under way; the
            # password just issued must not outlive the start.
            await self._withdraw_egress()
            return
        await supervisor.start(self._process_spec(desired, fetched.credentials, egress_password))
        if self._failed_for is not None:
            # The watchdog failed it while `start` waited for the supervisor: a failed placement
            # never runs.
            await supervisor.stop()
            supervisor.fail(self._failure or "the plugin's database failed")
            await self._withdraw_egress()
            return
        self._started_with = _StartedWith.of(desired)
        self._running_settings_revision = fetched.credentials.settings_revision
        self._services.on_change()

    def _show_install_phase(self, step: UpgradeStep) -> None:
        self.supervisor.show_phase("building" if step == "build" else "downloading")

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
        database = self.database_for(wanted)
        async with database.lock:
            database.provisioning(wanted)
            self._services.on_change()
            try:
                outcome = await self._services.provisioner.ensure(
                    desired.plugin_identifier,
                    wanted,
                    credentials.database.app_password,
                    self._installed[desired.package].migrations,
                )
            except DatabaseUnreachableError as error:
                database.provisioning(wanted, str(error))
                raise
            except DatabaseProvisioningError as error:
                database.failed(str(error), ledger=error.ledger)
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
        venv = self._installed[desired.package].venv
        return ProcessSpec(
            plugin=desired.plugin_identifier,
            uid=desired.runtime.unix_uid,
            version=desired.package.version,
            argv=plugin_command(venv),
            environment=plugin_environment(
                self._services.layout,
                desired,
                venv,
                credentials.runtime_file,
                PlatformCredentials(egress_password, database_password),
            ),
            nice=NICENESS[desired.runtime.cpu_priority],
            port=desired.runtime.port,
            memory_mb=desired.runtime.memory_mb,
        )

    async def _prune(self, desired: DesiredPlacement) -> None:
        """With no upgrade open, delete every installed version of the plugin but the desired one.

        Done once per package in this agent's life; a failure is logged and tried again at the
        next converge.
        """
        package = desired.package
        if self._pruned_for == package or package not in self._installed:
            return
        identifier = desired.plugin_identifier
        try:
            code = await self._services.launcher.prune_code(
                identifier, desired.runtime.unix_uid, package.version
            )
            venvs = await asyncio.to_thread(
                prune_agent_trees, self._services.layout, identifier, package.version
            )
        except (LauncherError, OSError) as error:
            logger.warning("Plugin {}: could not delete its other versions: {}", identifier, error)
            return
        self._installed = {package: self._installed[package]}
        self._pruned_for = package
        if code or venvs:
            logger.info(
                "plugins.upgrade.pruned plugin={} kept={} removed={}",
                identifier,
                package.version,
                ",".join(sorted(set(code) | set(venvs))),
            )

    def _backup_reports(self) -> list[BackupFileReport]:
        """Every complete backup of the plugin; one that cannot be reported is left out."""
        try:
            stored = self._services.backup_store.inventory(self._desired.plugin_identifier)
        except OSError as error:
            self._log_unreportable_backups(f"the backups cannot be listed: {error}")
            return []
        reports = []
        for backup in stored:
            try:
                reports.append(backup.report())
            except ValidationError:
                self._log_unreportable_backups(f"backup {backup.file_name} cannot be reported")
        return reports

    def _log_unreportable_backups(self, message: str) -> None:
        if not self._unreportable_backups:
            self._unreportable_backups = True
            logger.warning("Plugin {}: {}", self._desired.plugin_identifier, message)

    async def _fail(self, desired: DesiredPlacement, error: str) -> None:
        logger.error("Plugin {} failed: {}", desired.plugin_identifier, error)
        await self.supervisor.stop()
        self._failed_for = (desired.restart_generation, desired.package)
        self._failure = error
        self.supervisor.fail(error)
        await self._withdraw_egress()
        if _upgrade_stage(desired) == "migrating":
            self._upgrade.fail(desired, error)

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


def _upgrade_stage(desired: DesiredPlacement) -> str | None:
    return desired.upgrade.stage if desired.upgrade is not None else None


def _sooner(first: float | None, second: float | None) -> float | None:
    waits = [wait for wait in (first, second) if wait is not None]
    return min(waits) if waits else None


class Reconciler:
    """Keeps one `PlacementController` per placement of the desired state."""

    def __init__(self, services: AgentServices):
        self._services = services
        self._controllers: dict[int, PlacementController] = {}
        self._placements: list[DesiredPlacement] = []
        # Placement ids whose report failed to build, so the failure is logged once.
        self._unreportable: set[int] = set()
        self._remover = PlacementRemover(
            RemovalServices(
                layout=services.layout,
                dropper=services.dropper,
                egress=services.egress,
                launcher=services.launcher,
                prune_downloads=self._prune_downloads,
                blocking_placement=self._blocking_placement,
                on_change=services.on_change,
            )
        )

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
        removed = {removal.placement_id for removal in desired_state.removals}
        closed_databases = {}
        for placement_id in [known for known in self._controllers if known not in wanted]:
            controller = self._controllers.pop(placement_id)
            if placement_id in removed and controller.database is not None:
                # From here on neither provisioning nor the limits watchdog touches it.
                controller.database.retire()
                closed_databases[placement_id] = controller.database
            await controller.close()
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
        self._placements = list(desired_state.placements)
        self._prune_downloads()
        await self._delete_backups(desired_state.placements)
        self._remover.apply(desired_state.removals, closed_databases)
        self._services.on_change()

    async def _delete_backups(self, placements: list[DesiredPlacement]) -> None:
        """Delete the backups EpicStaff no longer keeps; a failure is tried at the next apply."""
        for placement in placements:
            if not placement.backups_to_delete:
                continue
            try:
                await asyncio.to_thread(
                    self._services.backup_store.delete,
                    placement.plugin_identifier,
                    list(placement.backups_to_delete),
                )
            except OSError as error:
                logger.warning(
                    "Plugin {}: could not delete backups: {}", placement.plugin_identifier, error
                )

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
        """One report per placement. One that cannot be built is replaced by a minimal one, so
        no placement can stop the node's report."""
        reports = []
        for placement_id, controller in self._controllers.items():
            try:
                reports.append(controller.report())
                self._unreportable.discard(placement_id)
            except Exception:
                if placement_id not in self._unreportable:
                    self._unreportable.add(placement_id)
                    logger.exception("The report of placement {} could not be built", placement_id)
                reports.append(
                    PlacementReport(
                        placement_id=placement_id,
                        observed_state="unknown",
                        health="unknown",
                        restarts=0,
                        last_error="the node could not report this placement; see the node's log",
                    )
                )
        return reports

    def removal_reports(self) -> list[RemovalReport]:
        return self._remover.reports()

    async def close(self) -> None:
        """Stop every plugin, all at once: each gets the same few seconds to finish."""
        await self._remover.close()
        await asyncio.gather(*(controller.close() for controller in self._controllers.values()))
        self._controllers.clear()

    def _prune_downloads(self) -> None:
        """Keep the packages placements run, and the targets of their open upgrades."""
        kept = [placement.package for placement in self._placements]
        kept += [placement.upgrade.target for placement in self._placements if placement.upgrade]
        self._services.fetcher.prune(kept)

    def _blocking_placement(self, removal: DesiredRemoval) -> int | None:
        """A controller that still has the placement, or any of its plugin, UID and port."""
        for placement_id, controller in self._controllers.items():
            runs = controller.desired
            if (
                placement_id == removal.placement_id
                or runs.plugin_identifier == removal.plugin_identifier
                or runs.runtime.unix_uid == removal.unix_uid
                or runs.runtime.port == removal.port
            ):
                return placement_id
        return None


def _identity(placement: DesiredPlacement) -> tuple[str, int, int]:
    return placement.plugin_identifier, placement.runtime.unix_uid, placement.runtime.port
