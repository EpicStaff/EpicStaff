"""The per-plugin disk cap and the node's floor, every 30 s.

Each running plugin's HOME (with its TMPDIR) is measured through the launcher (see
`es_plugins.disk_usage` for what counts). Above `ES_PLUGINS_DISK_MB_PER_PLUGIN` or
`ES_PLUGINS_FILES_PER_PLUGIN`, or when its use cannot be measured, the plugin is killed and left
`failed` (`ProcessSupervisor.fail_for`): restarting it would only fill the disk again. It stays
failed until EpicStaff restarts it or installs another version. A measurement that brings no
result at all (the launcher refused it, or it ran out of time) counts as one that could not
measure, from the second in a row on: a plugin cannot escape the cap by making its measurement
slow.

Then the volume's free space: below the floor (see `es_plugins.node_disk`) the running plugin
that uses the most is stopped the same way, by bytes or by files, whichever ran short. By bytes,
a plugin uses its HOME, its database (`size_bytes`, as the database watchdog last measured it)
and its backups: on a default install the database's volume shares the host's file system with
the node's, so a plugin that fills its database is the one stopped. By files, its HOME's files.
A plugin whose measurement brought no result this time ranks above every measured one. Stopping a
plugin frees nothing, so another is stopped only while the free space keeps falling (by
`FURTHER_FALL_BYTES` or `FURTHER_FALL_FILES` since the last stop).

The measurements run one after the other; each costs at most about the caps it checks and
ends after `MEASUREMENT_SECONDS`.
"""

import asyncio
from collections.abc import Callable, Iterable
from typing import Protocol

from loguru import logger

from es_plugins.agent.launcher_client import LauncherClient, LauncherError
from es_plugins.descriptors import read_pipe
from es_plugins.disk_usage import DiskUsage
from es_plugins.launcher.disk_measurement import MEASUREMENT_SECONDS
from es_plugins.node_disk import FloorBreach, NodeDisk
from es_plugins.supervisor.process_supervisor import ProcessSupervisor

POLL_INTERVAL_SECONDS = 30.0
# The helper's own alarm ends a measurement first; this only bounds waiting for its pipe.
RESULT_TIMEOUT_SECONDS = MEASUREMENT_SECONDS + 10
_MAX_RESULT_BYTES = 64 * 1024
_MIB = 1024 * 1024
# Below the floor, another plugin is stopped only once the free space fell this much further
# since the last stop: the node's own logs move it a little all the time.
FURTHER_FALL_BYTES = 64 * _MIB
FURTHER_FALL_FILES = 1000
# Measurements in a row that bring no result before the plugin fails as unmeasurable.
MISSED_MEASUREMENTS_BEFORE_FAILING = 2


class DiskWatchedPlacement(Protocol):
    """A placement as the disk watchdog sees it (its controller)."""

    @property
    def supervisor(self) -> ProcessSupervisor: ...

    def bytes_outside_home(self) -> int:
        """What the plugin keeps outside its HOME: its database and its backups."""


class DiskWatchdog:
    def __init__(
        self,
        launcher: LauncherClient,
        placements: Callable[[], Iterable[DiskWatchedPlacement]],
        node_disk: NodeDisk,
        *,
        max_megabytes: int,
        max_files: int,
        interval: float = POLL_INTERVAL_SECONDS,
    ):
        self._launcher = launcher
        self._placements = placements
        self._node_disk = node_disk
        self._max_megabytes = max_megabytes
        self._max_files = max_files
        self._interval = interval
        self._last_floor_stop: FloorBreach | None = None
        # Each running plugin's measurements in a row that brought no result.
        self._missed: dict[ProcessSupervisor, int] = {}

    async def check_once(self) -> list[ProcessSupervisor]:
        """Measure every running plugin, fail those over a cap, then check the floor.

        Returns:
            The supervisors failed by this check.
        """
        failed = []
        watched = [placement for placement in self._placements() if placement.supervisor.watching]
        running = {placement.supervisor for placement in watched}
        self._missed = {
            supervisor: count for supervisor, count in self._missed.items() if supervisor in running
        }
        # The measured ones, and None for one whose measurement brought no result this time.
        ranked: dict[DiskWatchedPlacement, DiskUsage | None] = {}
        for placement in watched:
            supervisor = placement.supervisor
            usage = await self._measure(supervisor)
            if usage is None:
                missed = self._missed.get(supervisor, 0) + 1
                self._missed[supervisor] = missed
                if missed < MISSED_MEASUREMENTS_BEFORE_FAILING:
                    ranked[placement] = None
                    continue
                reason = f"its disk use could not be measured {missed} times in a row"
            else:
                self._missed.pop(supervisor, None)
                reason = self._over_cap(usage)
            if reason is not None:
                self._missed.pop(supervisor, None)
                supervisor.fail_for(reason)
                failed.append(supervisor)
            else:
                ranked[placement] = usage
        stopped = self._stop_the_largest_below_floor(ranked)
        if stopped is not None:
            failed.append(stopped)
        return failed

    async def run(self) -> None:
        while True:
            await self.check_once()
            await asyncio.sleep(self._interval)

    def _over_cap(self, usage: DiskUsage) -> str | None:
        if usage.problem is not None:
            return f"its disk use cannot be measured: {usage.problem}"
        if usage.bytes > self._max_megabytes * _MIB:
            return (
                f"uses {usage.bytes // _MIB} MB of disk, more than its limit of "
                f"{self._max_megabytes} MB"
            )
        if usage.files > self._max_files:
            return f"has {usage.files} files, more than its limit of {self._max_files} files"
        return None

    def _stop_the_largest_below_floor(
        self, ranked: dict[DiskWatchedPlacement, DiskUsage | None]
    ) -> ProcessSupervisor | None:
        breach = self._node_disk.below_floor()
        if breach is None:
            self._last_floor_stop = None
            return None
        last = self._last_floor_stop
        further_fall = FURTHER_FALL_FILES if breach.by_files else FURTHER_FALL_BYTES
        still_falling = (
            last is None
            or last.by_files != breach.by_files
            or breach.free <= last.free - further_fall
        )
        if not ranked or not still_falling:
            return None
        uses = {
            placement: _use(placement, usage, by_files=breach.by_files)
            for placement, usage in ranked.items()
        }
        largest = max(uses, key=lambda placement: uses[placement][0])
        supervisor = largest.supervisor
        logger.error(
            "The node's disk is almost full ({}); stopping {}",
            breach.description,
            supervisor.plugin,
        )
        supervisor.fail_for(
            f"the node's disk is almost full ({breach.description}), and this plugin uses the most "
            f"of it ({uses[largest][1]})"
        )
        self._last_floor_stop = breach
        return supervisor

    async def _measure(self, supervisor: ProcessSupervisor) -> DiskUsage | None:
        try:
            result_pipe = await self._launcher.measure_disk(
                supervisor.plugin, supervisor.uid, self._max_megabytes * _MIB, self._max_files
            )
        except LauncherError as error:
            logger.warning(
                "Could not measure the disk use of plugin {}: {}", supervisor.plugin, error
            )
            return None
        try:
            data = await asyncio.wait_for(
                read_pipe(result_pipe, _MAX_RESULT_BYTES), RESULT_TIMEOUT_SECONDS
            )
        except TimeoutError:
            data = b""
        try:
            return DiskUsage.from_json(data)
        except (ValueError, KeyError, TypeError):
            logger.warning(
                "The disk use of plugin {} could not be measured in {} s",
                supervisor.plugin,
                MEASUREMENT_SECONDS,
            )
            return None


def _use(
    placement: DiskWatchedPlacement, usage: DiskUsage | None, *, by_files: bool
) -> tuple[tuple[bool, int], str]:
    """How a placement ranks below the floor (unmeasured first, then by size), and its share."""
    if usage is None:
        return (True, 0), "its disk use could not be measured"
    if by_files:
        return (False, usage.files), f"{usage.files} files"
    total = usage.bytes + placement.bytes_outside_home()
    return (False, total), f"{total // _MIB} MB, its database and backups included"
