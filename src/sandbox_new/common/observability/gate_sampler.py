"""Logs the `sandbox_gate` BENCH checkpoint: both admission gates' state, every few seconds.

The checkpoint reads the manager's intake side (queued and held executions, the drain
rate) next to the worker's run gate (slots in use, its limits, the load it last read), so
a benchmark can tell which limit was the one holding work back.

It is a neutral observer: it sees each side only through the two protocols below. The only
thing it takes from either side is `RunGateSnapshot`, the return type of the run gate's
port; it imports no implementation class and nothing from infrastructure. The composition
root hands it the real objects.
"""

import asyncio
from typing import Protocol

from loguru import logger
from src.shared.bench_log import BENCH_LEVEL
from worker.application.ports import RunGateSnapshot

__all__ = ["SAMPLE_INTERVAL_SECONDS", "GateSampler", "IntakeMetrics", "RunGateMetrics"]

SAMPLE_INTERVAL_SECONDS = 5.0


class IntakeMetrics(Protocol):
    """The manager's intake side, as the sampler reads it."""

    @property
    def queued_count(self) -> int: ...

    @property
    def held_count(self) -> int: ...

    def drain_rate(self) -> float | None: ...


class RunGateMetrics(Protocol):
    """The worker's run gate, as the sampler reads it."""

    def snapshot(self) -> RunGateSnapshot: ...


class GateSampler:
    """Log one `sandbox_gate` checkpoint per interval; a failed sample is skipped, not fatal."""

    def __init__(
        self,
        intake: IntakeMetrics,
        run_gate: RunGateMetrics,
        *,
        interval: float = SAMPLE_INTERVAL_SECONDS,
    ) -> None:
        self._intake = intake
        self._run_gate = run_gate
        self._interval = interval

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                self._sample()
            except Exception as error:
                logger.error("Admission gate sample failed: {}", type(error).__name__)

    def _sample(self) -> None:
        run_gate = self._run_gate.snapshot()
        drain_rate = self._intake.drain_rate()
        logger.log(
            BENCH_LEVEL,
            "bench {checkpoint}",
            checkpoint="sandbox_gate",
            running=run_gate.running,
            floor=run_gate.floor,
            max_concurrent=run_gate.max_concurrent,
            cpu_busy_percent=_rounded(run_gate.sample.cpu_busy_percent, 1),
            memory_used_percent=_rounded(run_gate.sample.memory_used_percent, 1),
            queued=self._intake.queued_count,
            held=self._intake.held_count,
            drain_rate=_rounded(drain_rate, 3),
        )


def _rounded(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)
