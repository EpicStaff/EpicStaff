"""Remove a plugin from the node for good: the desired state's `removals`.

`Reconciler.apply` closes the controller of a placement that left `placements` (its process is
stopped and its proxy password withdrawn) and hands each removal to `PlacementRemover`. One task
per removal then runs these steps in order. Each can run again, so a restarted agent runs the whole
list again and finds most of it done:

1. Wait until no controller runs the placement, its plugin, its UID or its port.
2. Drop the plugin's database and roles (`DatabaseDropper`), holding the placement's database
   lock, which the limits watchdog and provisioning share.
3. Remove the plugin's proxy password and host list from the egress policy.
4. Delete what the agent keeps for the plugin: the contents of `venvs/<id>/`, `logs/<id>/`,
   `agent/unpack/<id>/`, its backups (`backups/<id>/`: a deleted plugin keeps none) and its
   downloaded packages. A link is deleted, never followed.
5. Have the launcher kill every process of the UID, remove its System V IPC objects, delete its
   HOME, code and run directory, and remove the empty `venvs/<id>/`.
6. Report `removed`, for as long as the removal stays in the desired state.

The report is `removing` from step 1 to step 6. A failure that may pass (plugins_db or the
launcher not answering, a backup still connected to the database) is retried every
`TRANSIENT_RETRY_SECONDS`, still `removing`, with `last_error`. Any other failure (a database
another installation made, a statement that fails, a launcher refusal, a file that cannot be
deleted) is reported `failed` until EpicStaff sends the removal with a new `generation`.

Log lines: `plugins.removal.started`, `.database_dropped`, `.done` and `.failed`. None carries a
password, a connection string or anything the plugin wrote.
"""

import asyncio
import contextlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from loguru import logger
from src.shared.models.plugin_nodes import MAX_LAST_ERROR_LENGTH, DesiredRemoval, RemovalReport

from es_plugins.agent.agent_trees import delete_agent_trees
from es_plugins.agent.launcher_client import LauncherClient, LauncherError, LauncherUnavailableError
from es_plugins.database.connections import DatabaseUnreachableError
from es_plugins.database.drop_sequence import DatabaseDropError, DatabaseDropper
from es_plugins.database.placement_database import PlacementDatabase
from es_plugins.egress.policy_writer import EgressPolicyError, EgressPolicyWriter
from es_plugins.launcher.plugin_removal import REMOVAL_SECONDS
from es_plugins.layout import NodeLayout

TRANSIENT_RETRY_SECONDS = 30.0
# Longer than the launcher's removing helper may take. A retry while it still runs is answered
# "already being removed", a temporary refusal.
LAUNCHER_REMOVAL_TIMEOUT_SECONDS = REMOVAL_SECONDS + 60.0
FailureReason = Literal["conflict", "database", "files", "launcher", "unreachable"]


class _RemovalStepError(Exception):
    def __init__(self, reason: FailureReason, message: str, *, temporary: bool):
        super().__init__(message)
        self.reason = reason
        self.temporary = temporary


@dataclass(frozen=True)
class RemovalServices:
    """What every removal uses; the agent's own instances."""

    layout: NodeLayout
    dropper: DatabaseDropper
    egress: EgressPolicyWriter
    launcher: LauncherClient
    prune_downloads: Callable[[], None]
    """Delete every downloaded package no placement of the desired state uses."""

    blocking_placement: Callable[[DesiredRemoval], int | None]
    """The placement id of a controller still running this placement, plugin, UID or port."""

    on_change: Callable[[], None]


@dataclass
class _Removal:
    desired: DesiredRemoval
    database_lock: asyncio.Lock
    state: Literal["removing", "removed", "failed"] = "removing"
    last_error: str | None = None
    task: asyncio.Task | None = field(default=None, repr=False)


class PlacementRemover:
    def __init__(
        self, services: RemovalServices, *, retry_seconds: float = TRANSIENT_RETRY_SECONDS
    ):
        self._services = services
        self._retry_seconds = retry_seconds
        self._removals: dict[int, _Removal] = {}
        # One removal at a time per plugin, should two placements of one plugin be removed.
        self._plugin_locks: dict[str, asyncio.Lock] = {}
        self._changed = asyncio.Event()

    def apply(
        self,
        removals: Sequence[DesiredRemoval],
        closed_databases: Mapping[int, PlacementDatabase],
    ) -> None:
        """Start, restart or forget removals to match the desired state.

        `closed_databases` are the databases of the controllers `apply` just closed for these
        removals: their locks are the ones the limits watchdog may still hold.
        """
        wanted = {removal.placement_id: removal for removal in removals}
        for placement_id in [known for known in self._removals if known not in wanted]:
            self._forget(placement_id)
        for placement_id, desired in wanted.items():
            known = self._removals.get(placement_id)
            if known is not None and known.desired.generation == desired.generation:
                continue
            if known is not None:
                # A new generation: EpicStaff asks for a failed removal to be tried again.
                self._forget(placement_id)
            database = closed_databases.get(placement_id)
            removal = _Removal(desired, database.lock if database is not None else asyncio.Lock())
            self._removals[placement_id] = removal
            removal.task = asyncio.create_task(self._run(removal), name=f"removal-{placement_id}")
        self.notice_change()

    def notice_change(self) -> None:
        """A controller closed: a removal waiting at step 1 looks again."""
        self._changed.set()

    def reports(self) -> list[RemovalReport]:
        reports = []
        for placement_id, removal in self._removals.items():
            try:
                reports.append(
                    RemovalReport(
                        placement_id=placement_id,
                        generation=removal.desired.generation,
                        state=removal.state,
                        last_error=(removal.last_error or "")[:MAX_LAST_ERROR_LENGTH] or None,
                    )
                )
            except Exception:
                # One removal's report must never stop the node's report.
                logger.exception("The report of removal {} could not be built", placement_id)
        return reports

    async def close(self) -> None:
        """Stop every removal task; the next agent runs them again from step 1."""
        tasks = [removal.task for removal in self._removals.values() if removal.task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _forget(self, placement_id: int) -> None:
        removal = self._removals.pop(placement_id)
        if removal.task is not None:
            removal.task.cancel()

    async def _run(self, removal: _Removal) -> None:
        desired = removal.desired
        plugin_lock = self._plugin_locks.setdefault(desired.plugin_identifier, asyncio.Lock())
        logger.info(
            "plugins.removal.started plugin={} placement={}",
            desired.plugin_identifier,
            desired.placement_id,
        )
        reported_temporary: str | None = None
        reported_unexpected: str | None = None
        while True:
            try:
                async with plugin_lock:
                    await self._remove(removal)
            except _RemovalStepError as failure:
                if not failure.temporary:
                    self._fail(removal, failure)
                    return
                self._set(removal, "removing", str(failure))
                if str(failure) != reported_temporary:
                    reported_temporary = str(failure)
                    logger.warning(
                        "plugins.removal.failed plugin={} reason={} detail={} retry_in={}",
                        desired.plugin_identifier,
                        failure.reason,
                        failure,
                        self._retry_seconds,
                    )
                await asyncio.sleep(self._retry_seconds)
                continue
            except Exception as error:
                # The agent removes every plugin: one removal's unexpected error must not stop it.
                # Logged when it changes, not at every retry.
                if str(error) != reported_unexpected:
                    reported_unexpected = str(error)
                    logger.exception(
                        "Removing plugin {}: unexpected error", desired.plugin_identifier
                    )
                self._set(removal, "removing", f"internal error of the node agent: {error}")
                await asyncio.sleep(self._retry_seconds)
                continue
            self._set(removal, "removed", None)
            logger.info(
                "plugins.removal.done plugin={} placement={}",
                desired.plugin_identifier,
                desired.placement_id,
            )
            return

    async def _remove(self, removal: _Removal) -> None:
        desired = removal.desired
        services = self._services
        self._set(removal, "removing", removal.last_error)
        await self._wait_for_no_controller(removal)
        if desired.database is not None:
            async with removal.database_lock:
                try:
                    dropped = await services.dropper.drop(desired.database)
                except DatabaseUnreachableError as error:
                    raise _RemovalStepError("unreachable", str(error), temporary=True) from None
                except DatabaseDropError as error:
                    raise _RemovalStepError(
                        error.reason, str(error), temporary=error.temporary
                    ) from None
            logger.info(
                "plugins.removal.database_dropped plugin={} placement={} databases={} roles={}",
                desired.plugin_identifier,
                desired.placement_id,
                dropped.databases,
                dropped.roles,
            )
        try:
            await services.egress.remove_plugin(desired.plugin_identifier)
        except EgressPolicyError as error:
            raise _RemovalStepError("files", str(error), temporary=False) from None
        try:
            await asyncio.to_thread(delete_agent_trees, services.layout, desired.plugin_identifier)
            services.prune_downloads()
        except OSError as error:
            raise _RemovalStepError(
                "files",
                f"the node's files of the plugin could not be deleted: {error}",
                temporary=False,
            ) from None
        try:
            await services.launcher.remove_plugin(
                desired.plugin_identifier,
                desired.unix_uid,
                timeout_seconds=LAUNCHER_REMOVAL_TIMEOUT_SECONDS,
            )
        except LauncherUnavailableError as error:
            raise _RemovalStepError("launcher", str(error), temporary=True) from None
        except LauncherError as error:
            raise _RemovalStepError("launcher", str(error), temporary=False) from None

    async def _wait_for_no_controller(self, removal: _Removal) -> None:
        while (running := self._services.blocking_placement(removal.desired)) is not None:
            self._set(
                removal,
                "removing",
                f"waiting for placement {running}, which runs the same plugin, UID or port, to stop",
            )
            self._changed.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._changed.wait(), self._retry_seconds)

    def _fail(self, removal: _Removal, failure: _RemovalStepError) -> None:
        self._set(removal, "failed", str(failure))
        logger.error(
            "plugins.removal.failed plugin={} reason={} detail={}",
            removal.desired.plugin_identifier,
            failure.reason,
            failure,
        )

    def _set(self, removal: _Removal, state, last_error: str | None) -> None:
        if (removal.state, removal.last_error) == (state, last_error):
            return
        removal.state, removal.last_error = state, last_error
        self._services.on_change()
