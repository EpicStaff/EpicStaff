"""Admits executions by the container's real headroom instead of a fixed slot count.

Up to a floor of executions -- by default the CPUs the container may use -- always
start. Above the floor, up to a hard maximum, a job starts only while host CPU and
container memory are under their thresholds, and at most `floor` such jobs start per
sampling tick: load shows up in the metrics only after the jobs have started, so the
burst limit keeps one quiet reading from admitting a flood.
"""

import asyncio
from dataclasses import dataclass

from loguru import logger

from worker.application.ports.admission_gate import AbstractAdmissionGate
from worker.infrastructure.admission.host_metrics import HostMetrics, HostSample

__all__ = ["TICK_SECONDS", "ResourceAdmissionGate", "RunGateSnapshot"]

# How often load is sampled and the above-floor burst budget refilled.
TICK_SECONDS = 0.5


@dataclass(frozen=True)
class RunGateSnapshot:
    """What the gate is deciding on right now: slots in use, its limits, the last load sample."""

    running: int
    floor: int
    max_concurrent: int
    sample: HostSample


class ResourceAdmissionGate(AbstractAdmissionGate):
    """Hand out execution slots by load; `run()` must be running for the budget to refill.

    Args:
        min_concurrent: Executions that always start; 0 means the container's CPUs.
        max_concurrent: Executions that never run at once, whatever the load.
        cpu_threshold: Host CPU busy percent at or above which no job starts above the floor.
        memory_threshold: Container memory percent with the same effect.
    """

    def __init__(
        self,
        metrics: HostMetrics,
        *,
        min_concurrent: int,
        max_concurrent: int,
        cpu_threshold: float,
        memory_threshold: float,
        tick_seconds: float = TICK_SECONDS,
    ) -> None:
        floor = min_concurrent if min_concurrent > 0 else metrics.floor()
        self._floor = min(floor, max_concurrent)
        self._max_concurrent = max_concurrent
        self._cpu_threshold = cpu_threshold
        self._memory_threshold = memory_threshold
        self._metrics = metrics
        self._tick_seconds = tick_seconds
        self._running = 0
        self._starts_left_above_floor = self._floor
        self._sample = HostSample(cpu_busy_percent=None, memory_used_percent=None)
        # Replaced on every change, so a waiter never misses one: it grabs the current
        # event, and whatever changes next sets exactly that event.
        self._changed = asyncio.Event()

    async def acquire(self) -> None:
        while not self._admits():
            changed = self._changed
            await changed.wait()
        if self._running >= self._floor:
            self._starts_left_above_floor -= 1
        self._running += 1

    def release(self) -> None:
        self._running -= 1
        self._notify_change()

    def has_free_slot(self) -> bool:
        return self._admits()

    def snapshot(self) -> RunGateSnapshot:
        return RunGateSnapshot(
            running=self._running,
            floor=self._floor,
            max_concurrent=self._max_concurrent,
            sample=self._sample,
        )

    def refresh(self) -> None:
        """Take a new load sample, refill the burst budget and wake a waiting job."""
        self._sample = self._metrics.sample()
        self._starts_left_above_floor = self._floor
        self._notify_change()

    async def run(self) -> None:
        # The first CPU reading only primes the counters: busy time needs two readings.
        self._metrics.sample()
        await asyncio.sleep(self._tick_seconds)
        self.refresh()
        self._log_configuration()
        while True:
            await asyncio.sleep(self._tick_seconds)
            self.refresh()

    def _admits(self) -> bool:
        if self._running < self._floor:
            return True
        return (
            self._running < self._max_concurrent
            and self._starts_left_above_floor > 0
            and _below(self._sample.cpu_busy_percent, self._cpu_threshold)
            and _below(self._sample.memory_used_percent, self._memory_threshold)
        )

    def _notify_change(self) -> None:
        self._changed.set()
        self._changed = asyncio.Event()

    def _log_configuration(self) -> None:
        logger.info(
            "Admission gate: {} executions always start, at most {} run at once; above "
            "{} a job starts while host CPU < {}% and container memory < {}%",
            self._floor,
            self._max_concurrent,
            self._floor,
            self._cpu_threshold,
            self._memory_threshold,
        )
        if self._sample.cpu_busy_percent is None:
            logger.warning("Host CPU load is unreadable; it does not limit admission")
        if self._sample.memory_used_percent is None:
            logger.warning("Container memory use is unreadable; it does not limit admission")
        if self._sample.cpu_busy_percent is None and self._sample.memory_used_percent is None:
            logger.warning(
                "Admission falls back to the floor ({}) and the maximum ({}) alone",
                self._floor,
                self._max_concurrent,
            )


def _below(value: float | None, threshold: float) -> bool:
    """An unreadable signal does not block admission."""
    return value is None or value < threshold
