"""The per-plugin memory cap: resident memory summed over the plugin's UID, every 2 s.

Resident memory here is what the processes allocated themselves (anonymous and shared-memory
pages), not the interpreter and libraries every process maps (see `ProcessTable`).

Summing by UID counts every process of the plugin, also children that called `setsid` or
were reparented to PID 1. Above `runtime.memory_mb` the supervisor kills the UID and
restarts the plugin with backoff. It is a soft cap: between two polls a plugin can allocate
past it (by about its allocation rate times 2 s). The container's `mem_limit` is the hard
limit for the node as a whole, and a plugin's `oom_score_adj` of 800 makes the kernel pick
a plugin, not the agent or the launcher, if that limit is reached first.
"""

import asyncio
from collections.abc import Callable, Iterable

from es_plugins.process_table import ProcessTable
from es_plugins.supervisor.process_supervisor import ProcessSupervisor

POLL_INTERVAL_SECONDS = 2.0
_KIB_PER_MIB = 1024


class MemoryWatchdog:
    def __init__(
        self,
        process_table: ProcessTable,
        supervisors: Callable[[], Iterable[ProcessSupervisor]],
        *,
        interval: float = POLL_INTERVAL_SECONDS,
    ):
        self._process_table = process_table
        self._supervisors = supervisors
        self._interval = interval

    def check_once(self) -> list[ProcessSupervisor]:
        """Record each running plugin's RSS; ask those over their cap to restart.

        Returns:
            The supervisors asked to restart.
        """
        running = [
            supervisor
            for supervisor in self._supervisors()
            if supervisor.watching and supervisor.memory_mb is not None
        ]
        totals = self._process_table.rss_kib_by_uid(supervisor.uid for supervisor in running)
        over_cap = []
        for supervisor in running:
            rss_mb = round(totals[supervisor.uid] / _KIB_PER_MIB, 1)
            supervisor.record_memory(rss_mb)
            if rss_mb > supervisor.memory_mb:
                supervisor.restart_for_memory(rss_mb)
                over_cap.append(supervisor)
        return over_cap

    async def run(self) -> None:
        while True:
            self.check_once()
            await asyncio.sleep(self._interval)
