"""The node's part of a plugin upgrade and of a restore: the steps each stage allows.

EpicStaff grants an upgrade one stage at a time (`DesiredUpgrade.stage`); the node runs that
stage's steps in order, each one fine to run again, so an agent restart runs the stage again
cheaply:

| Stage | Steps |
|---|---|
| `preparing` (the running process is not touched) | `download`, `verify`, `build` the target into its own version directories; when a backup is required, `backup` checks there is room for it; then ask for `maintenance` |
| `maintenance` | the target's `download`, `verify` and `build` when it is not installed (a newer version replaced it); `drain`: wait for the hook call in flight; `stop` the process and every process of its user id; `backup` when required (a complete local backup of this upgrade is used again); then ask for `migrations` with that backup |
| `migrating` | the placement's controller runs `migrate` (provisioning with the target's migrations) and `start`, as for any start |

**Asking for the next stage** (`advance`). Granted (204): the node fetches the desired state at
once. 409: the upgrade moved on without this (it was cancelled, or a newer version replaced its
target); the node does nothing more for this stage and follows the next desired state. 400 or 404:
a failure of the step.

**Failures.** One that may pass by itself (django_app, plugins_db or the launcher not answering)
is retried every `TRANSIENT_RETRY_SECONDS`, reported `working` with the error. Any other is
reported `failed`, and the stage waits until EpicStaff sends it again with a new generation (a
Retry) or another target. EpicStaff then marks the desired upgrade `failed`, so a restarted
agent runs none of the stage's steps either; it reports nothing of an upgrade it saw fail only
before its restart, so EpicStaff keeps the step and the error it has. The process stays as the
stage left it: running while preparing, stopped from `stop` on.

**Restore** (`PlacementRestore`): while the desired placement names a restore, the process is
stopped and `RestoreService` replaces the database; the process is not started afterwards.

Log line: `plugins.upgrade.step` for each step begun.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from loguru import logger
from src.shared.models.plugin_nodes import (
    MAX_LAST_ERROR_LENGTH,
    DesiredDatabase,
    DesiredPackage,
    DesiredPlacement,
    DesiredRuntime,
    RestoreReport,
    RestoreStep,
    UpgradeAdvance,
    UpgradeReport,
    UpgradeStep,
)

from es_plugins.agent.django_client import DjangoNodeClient, NodeApiError
from es_plugins.agent.launcher_client import LauncherError, LauncherUnavailableError
from es_plugins.agent.port_reservation import PortUnavailableError
from es_plugins.database.backup_service import BackupError, BackupRequest, BackupService
from es_plugins.database.backup_store import BackupStore, StoredBackup
from es_plugins.database.connections import DatabaseProvisioningError, DatabaseUnreachableError
from es_plugins.database.placement_database import PlacementDatabase
from es_plugins.database.restore_service import RestoreError, RestoreService
from es_plugins.node_disk import FLOOR_BYTES, NodeDisk, NodeDiskFullError
from es_plugins.packages.package_verifier import PackageVerificationError
from es_plugins.packages.venv_builder import VenvBuildError
from es_plugins.packages.wheel_tag_check import IncompatibleWheelError

TRANSIENT_RETRY_SECONDS = 30.0
_MIB = 1024 * 1024
_FIRST_STEP: dict[str, UpgradeStep] = {
    "preparing": "download",
    "maintenance": "drain",
    "migrating": "migrate",
}
_PERMANENT_ERRORS = (
    PackageVerificationError,
    IncompatibleWheelError,
    VenvBuildError,
    NodeDiskFullError,
    BackupError,
    DatabaseProvisioningError,
)


class UpgradeStepError(Exception):
    """A step cannot be done as the desired state asks (permanent)."""


class UpgradeHost(Protocol):
    """What the stages need of the placement's controller."""

    async def install(
        self,
        package: DesiredPackage,
        runtime: DesiredRuntime,
        on_step: Callable[[UpgradeStep], None],
    ) -> None:
        """Download, verify and build `package` unless it is installed; never touches the process."""

    async def drain_hooks(self) -> None:
        """Wait for the hook call in flight; claim no new one."""

    async def stop_for_upgrade(self) -> None:
        """Stop the process and every process of its user id; withdraw its proxy password.

        Raises:
            UpgradeStepError: A process of the user id survived.
        """

    def database_lock(self, database: DesiredDatabase) -> asyncio.Lock:
        """The lock provisioning and the limits watchdog take for the database, to back it up."""

    def database_for(self, database: DesiredDatabase) -> PlacementDatabase:
        """The placement's database record, kept and reported from now on: a restore provisions it."""

    def database_replaced(self) -> None:
        """A restore replaced the database: the next start provisions it again, migrations included."""

    async def app_password(self, desired: DesiredPlacement) -> str:
        """The app role's password, from the runtime credentials."""


@dataclass(frozen=True)
class UpgradeServices:
    django: DjangoNodeClient
    disk: NodeDisk
    backups: BackupService
    backup_store: BackupStore
    restores: RestoreService
    request_desired_state: Callable[[], None]
    """Fetch the desired state now, not at the next poll."""

    on_change: Callable[[], None]


@dataclass(frozen=True)
class _Work:
    """One stage of one upgrade, as EpicStaff sent it: a Retry or a new target is new work."""

    upgrade_id: int
    generation: int
    stage: str
    target: DesiredPackage

    @classmethod
    def of(cls, desired: DesiredPlacement) -> "_Work":
        upgrade = desired.upgrade
        return cls(upgrade.upgrade_id, desired.restart_generation, upgrade.stage, upgrade.target)


class UpgradeStages:
    """The steps of `preparing` and `maintenance`, and what the node reports of an upgrade."""

    def __init__(self, plugin: str, services: UpgradeServices, host: UpgradeHost):
        self._plugin = plugin
        self._services = services
        self._host = host
        self._work: _Work | None = None
        self._step: UpgradeStep | None = None
        self._failed = False
        self._last_error: str | None = None
        # Work the node does no more: it failed (until a Retry), or EpicStaff refused to advance it.
        self._done_with: _Work | None = None
        self._advanced: tuple[_Work, float] | None = None
        self.in_progress: _Work | None = None
        """The stage work running now, which a desired state without it may cut short."""

    def report(self, desired: DesiredPlacement) -> UpgradeReport | None:
        if desired.upgrade is None:
            return None
        work = _Work.of(desired)
        if self._work == work:
            step, state, error = (
                self._step,
                "failed" if self._failed else "working",
                self._last_error,
            )
        elif desired.upgrade.failed:
            # Failed before this agent's start: the step and the error are EpicStaff's to keep.
            return None
        else:
            step, state, error = _FIRST_STEP[work.stage], "working", None
        return UpgradeReport(
            upgrade_id=work.upgrade_id,
            generation=work.generation,
            stage=work.stage,
            step=step,
            state=state,
            last_error=error[:MAX_LAST_ERROR_LENGTH] if error else None,
        )

    def moot(self, desired: DesiredPlacement) -> bool:
        """Whether the work in progress is no longer what `desired` asks for."""
        return self.in_progress is not None and (
            desired.upgrade is None or _Work.of(desired) != self.in_progress
        )

    def step(self, desired: DesiredPlacement, step: UpgradeStep, error: str | None = None) -> None:
        """The node is at `step` of the desired stage (with the error a retry last hit)."""
        work = _Work.of(desired)
        if (self._work, self._step) != (work, step):
            logger.info(
                "plugins.upgrade.step plugin={} upgrade={} stage={} step={}",
                self._plugin,
                work.upgrade_id,
                work.stage,
                step,
            )
        changed = (self._work, self._step, self._failed, self._last_error) != (
            work,
            step,
            False,
            error,
        )
        self._work, self._step, self._failed, self._last_error = work, step, False, error
        if changed:
            self._services.on_change()

    def fail(self, desired: DesiredPlacement, error: str, step: UpgradeStep | None = None) -> None:
        """The desired stage failed for good, at `step` or the step it is at."""
        work = _Work.of(desired)
        if step is None:
            step = self._step if self._work == work and self._step else _FIRST_STEP[work.stage]
        logger.error(
            "plugins.upgrade.failed plugin={} upgrade={} stage={} step={}",
            self._plugin,
            work.upgrade_id,
            work.stage,
            step,
        )
        self._work, self._step, self._failed, self._last_error = work, step, True, error
        self._done_with = work
        self._services.on_change()

    async def prepare(self, desired: DesiredPlacement) -> float | None:
        """The `preparing` steps; returns when to look again, or None."""
        return await self._run(desired, self._prepare)

    async def maintain(self, desired: DesiredPlacement) -> float | None:
        """The `maintenance` steps; returns when to look again, or None."""
        return await self._run(desired, self._maintain)

    async def _run(
        self,
        desired: DesiredPlacement,
        steps: Callable[[DesiredPlacement], Awaitable[float | None]],
    ) -> float | None:
        work = _Work.of(desired)
        if self._done_with == work:
            return None
        self.in_progress = work
        try:
            return await steps(desired)
        except UpgradeStepError as error:
            self.fail(desired, str(error))
        except NodeApiError as error:
            if not error.transient:
                self.fail(desired, str(error))
                return None
            self.retrying(desired, str(error))
            return TRANSIENT_RETRY_SECONDS
        except (DatabaseUnreachableError, LauncherUnavailableError, PortUnavailableError) as error:
            self.retrying(desired, str(error))
            return TRANSIENT_RETRY_SECONDS
        except (*_PERMANENT_ERRORS, LauncherError, OSError) as error:
            self.fail(desired, str(error))
        except Exception as error:
            # The agent upgrades every plugin: one upgrade's unexpected error must not stop it.
            logger.exception("Plugin {}: unexpected error in its upgrade", self._plugin)
            self.retrying(desired, f"internal error of the node agent: {error}")
            return TRANSIENT_RETRY_SECONDS
        finally:
            self.in_progress = None
        return None

    def retrying(self, desired: DesiredPlacement, error: str) -> None:
        """The step the node is at hit an error that may pass; it is tried again later."""
        work = _Work.of(desired)
        step = self._step if self._work == work and self._step else _FIRST_STEP[work.stage]
        self.step(desired, step, error)

    async def _prepare(self, desired: DesiredPlacement) -> float | None:
        upgrade = desired.upgrade
        await self._host.install(
            upgrade.target, upgrade.target_runtime, lambda step: self.step(desired, step)
        )
        if upgrade.backup == "required":
            self.step(desired, "backup")
            self._check_room(upgrade.backup_bytes_needed)
        return await self._advance(desired, UpgradeAdvance(to="maintenance"))

    async def _maintain(self, desired: DesiredPlacement) -> float | None:
        upgrade = desired.upgrade
        await self._host.install(
            desired.package, desired.runtime, lambda step: self.step(desired, step)
        )
        self.step(desired, "drain")
        await self._host.drain_hooks()
        self.step(desired, "stop")
        await self._host.stop_for_upgrade()
        backup = None
        if upgrade.backup == "required":
            self.step(desired, "backup")
            backup = await self._backup(desired)
        return await self._advance(
            desired, UpgradeAdvance(to="migrations", backup=backup.report() if backup else None)
        )

    def _check_room(self, needed: int) -> None:
        free = self._services.disk.free().bytes - FLOOR_BYTES
        if free < needed:
            raise UpgradeStepError(
                f"not enough disk space for the database backup: about {-(-needed // _MIB)} MB "
                f"needed, {max(free, 0) // _MIB} MB free"
            )

    async def _backup(self, desired: DesiredPlacement) -> StoredBackup:
        upgrade = desired.upgrade
        database = desired.database
        if database is None:
            raise UpgradeStepError("a backup is required, but the desired state names no database")
        inventory = await asyncio.to_thread(self._services.backup_store.inventory, self._plugin)
        for stored in inventory:
            metadata = stored.metadata
            if (metadata.upgrade_id, metadata.reason, metadata.installation_id) == (
                upgrade.upgrade_id,
                "pre_upgrade",
                database.installation_id,
            ):
                return stored
        async with self._host.database_lock(database):
            return await self._services.backups.backup(
                BackupRequest(
                    plugin=self._plugin,
                    database=database,
                    upgrade_id=upgrade.upgrade_id,
                    reason="pre_upgrade",
                    version=upgrade.from_version,
                )
            )

    async def _advance(self, desired: DesiredPlacement, advance: UpgradeAdvance) -> float | None:
        work = _Work.of(desired)
        advanced = self._advanced
        if (
            advanced is not None
            and advanced[0] == work
            and time.monotonic() - advanced[1] < TRANSIENT_RETRY_SECONDS
        ):
            # Granted a moment ago; the desired state showing it is on its way.
            return TRANSIENT_RETRY_SECONDS
        try:
            await self._services.django.advance_upgrade(work.upgrade_id, advance)
        except NodeApiError as error:
            if error.status != 409:
                raise
            # The upgrade went on without this stage: cancelled, replaced or failed.
            self._done_with = work
            self._services.request_desired_state()
            return None
        self._advanced = (work, time.monotonic())
        self._services.request_desired_state()
        # Granted: ask again later only if the desired state still shows this stage then.
        return TRANSIENT_RETRY_SECONDS


class PlacementRestore:
    """A restore the desired placement names: run it once, report it until EpicStaff drops it."""

    def __init__(self, plugin: str, services: UpgradeServices, host: UpgradeHost):
        self._plugin = plugin
        self._services = services
        self._host = host
        self._restore_id: int | None = None
        self._state: str = "running"
        self._step: RestoreStep = "verify"
        self._pre_restore: str | None = None
        self._last_error: str | None = None

    def report(self, desired: DesiredPlacement) -> RestoreReport | None:
        restore = desired.restore
        if restore is None:
            return None
        if self._restore_id != restore.restore_id:
            return RestoreReport(restore_id=restore.restore_id, state="running", step="verify")
        return RestoreReport(
            restore_id=restore.restore_id,
            state=self._state,
            step=self._step,
            pre_restore_backup=self._pre_restore,
            last_error=self._last_error[:MAX_LAST_ERROR_LENGTH] if self._last_error else None,
        )

    def finished(self, desired: DesiredPlacement) -> bool:
        """Whether the desired restore has succeeded or failed for good in this agent's life."""
        return (
            desired.restore is not None
            and self._restore_id == desired.restore.restore_id
            and self._state in ("succeeded", "failed")
        )

    async def run(self, desired: DesiredPlacement) -> float | None:
        """Restore the desired backup unless done; returns when to look again, or None."""
        restore = desired.restore
        if self.finished(desired):
            return None
        if self._restore_id != restore.restore_id:
            self._restore_id, self._state, self._step = restore.restore_id, "running", "verify"
            self._pre_restore = self._last_error = None
        try:
            await self._host.stop_for_upgrade()
            password = await self._host.app_password(desired)
            record = self._host.database_for(desired.database)
            async with record.lock:
                outcome = await self._services.restores.restore(
                    self._plugin,
                    desired.database,
                    restore,
                    version=desired.upgrade.target.version,
                    app_password=password,
                    on_step=self._on_step,
                )
                record.provisioned(outcome.provisioned)
            self._host.database_replaced()
        except RestoreError as error:
            self._step = error.step
            self._last_error = str(error)
            if error.temporary:
                self._services.on_change()
                return TRANSIENT_RETRY_SECONDS
            self._state = "failed"
            self._services.on_change()
            return None
        except (NodeApiError, LauncherUnavailableError) as error:
            if isinstance(error, NodeApiError) and not error.transient:
                self._state, self._last_error = "failed", str(error)
                self._services.on_change()
                return None
            self._last_error = str(error)
            self._services.on_change()
            return TRANSIENT_RETRY_SECONDS
        except (UpgradeStepError, LauncherError) as error:
            self._state, self._last_error = "failed", str(error)
            self._services.on_change()
            return None
        self._state = "succeeded"
        self._pre_restore = outcome.pre_restore.file_name
        self._last_error = None
        self._services.on_change()
        return None

    def _on_step(self, step: RestoreStep, pre_restore: StoredBackup | None) -> None:
        self._step = step
        if pre_restore is not None:
            self._pre_restore = pre_restore.file_name
        self._services.on_change()
