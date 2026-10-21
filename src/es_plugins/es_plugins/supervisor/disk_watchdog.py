"""The per-plugin disk cap and the node's floor, every 30 s.

Each running plugin's HOME (with its TMPDIR) is measured through the launcher (see
`es_plugins.disk_usage` for what counts). Above `ES_PLUGINS_DISK_MB_PER_PLUGIN` or
`ES_PLUGINS_FILES_PER_PLUGIN`, or when its use cannot be measured, the plugin is killed and left
`failed` (`ProcessSupervisor.fail_for`): restarting it would only fill the disk again. It stays
failed until EpicStaff restarts it or installs another version.

Then the volume's free space: below the floor (see `es_plugins.node_disk`) the running plugin
that uses the most is stopped the same way, by bytes or by files, whichever ran short. Stopping
a plugin frees nothing, so another is stopped only while the free space keeps falling (by
`FURTHER_FALL_BYTES` or `FURTHER_FALL_FILES` since the last stop).

The measurements run one after the other; each costs at most about the caps it checks and
ends after `MEASUREMENT_SECONDS`.
"""

import asyncio
import contextlib
import os
from collections.abc import Callable, Iterable

from loguru import logger

from es_plugins.agent.launcher_client import LauncherClient, LauncherError
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


class DiskWatchdog:
    def __init__(
        self,
        launcher: LauncherClient,
        supervisors: Callable[[], Iterable[ProcessSupervisor]],
        node_disk: NodeDisk,
        *,
        max_megabytes: int,
        max_files: int,
        interval: float = POLL_INTERVAL_SECONDS,
    ):
        self._launcher = launcher
        self._supervisors = supervisors
        self._node_disk = node_disk
        self._max_megabytes = max_megabytes
        self._max_files = max_files
        self._interval = interval
        self._last_floor_stop: FloorBreach | None = None

    async def check_once(self) -> list[ProcessSupervisor]:
        """Measure every running plugin, fail those over a cap, then check the floor.

        Returns:
            The supervisors failed by this check.
        """
        failed = []
        measured: dict[ProcessSupervisor, DiskUsage] = {}
        for supervisor in [supervisor for supervisor in self._supervisors() if supervisor.watching]:
            usage = await self._measure(supervisor)
            if usage is None:
                continue
            reason = self._over_cap(usage)
            if reason is not None:
                supervisor.fail_for(reason)
                failed.append(supervisor)
            else:
                measured[supervisor] = usage
        stopped = self._stop_the_largest_below_floor(measured)
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
        self, measured: dict[ProcessSupervisor, DiskUsage]
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
        if not measured or not still_falling:
            return None
        if breach.by_files:
            largest = max(measured, key=lambda supervisor: measured[supervisor].files)
            share = f"{measured[largest].files} files"
        else:
            largest = max(measured, key=lambda supervisor: measured[supervisor].bytes)
            share = f"{measured[largest].bytes // _MIB} MB"
        logger.error(
            "The node's disk is almost full ({}); stopping {}", breach.description, largest.plugin
        )
        largest.fail_for(
            f"the node's disk is almost full ({breach.description}), and this plugin uses the most "
            f"of it ({share})"
        )
        self._last_floor_stop = breach
        return largest

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
            data = await asyncio.wait_for(_read_all(result_pipe), RESULT_TIMEOUT_SECONDS)
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


async def _read_all(descriptor: int) -> bytes:
    """Read the pipe to its end without blocking the event loop; the descriptor is closed after.

    Returns b"" for a result larger than any `DiskUsage`.
    """
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=_MAX_RESULT_BYTES)
    pipe = os.fdopen(descriptor, "rb", buffering=0)
    transport, _ = await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), pipe)
    try:
        data = b""
        while chunk := await reader.read(_MAX_RESULT_BYTES):
            data += chunk
            if len(data) > _MAX_RESULT_BYTES:
                return b""
        return data
    finally:
        with contextlib.suppress(Exception):
            transport.close()
