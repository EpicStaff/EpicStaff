"""Logs the `sandbox_gate` BENCH checkpoint: the worker's run gate, every few seconds.

`running` includes the one idle slot the job consumer holds ahead of its next pull
(slot-first pulling), so an idle worker reads 1, not 0.

The manager logs its own `sandbox_intake` line; a benchmark reads the two side by side
to tell which limit was the one holding work back. The sampler is a neutral observer:
it sees the gate only through the protocol below, and the only type it takes from the
application is `RunGateSnapshot`, the return type of the run gate's port.
"""

import asyncio
from typing import Protocol

from loguru import logger
from src.shared.bench_log import BENCH_LEVEL

from worker.application.ports import RunGateSnapshot

__all__ = ["SAMPLE_INTERVAL_SECONDS", "RunGateMetrics", "RunGateSampler"]

SAMPLE_INTERVAL_SECONDS = 5.0


class RunGateMetrics(Protocol):
    """The worker's run gate, as the sampler reads it."""

    def snapshot(self) -> RunGateSnapshot: ...


class RunGateSampler:
    """Log one `sandbox_gate` checkpoint per interval; a failed sample is skipped, not fatal."""

    def __init__(self, run_gate: RunGateMetrics, *, interval: float = SAMPLE_INTERVAL_SECONDS):
        self._run_gate = run_gate
        self._interval = interval

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                self._sample()
            except Exception as error:
                logger.error("Run gate sample failed: {}", type(error).__name__)

    def _sample(self) -> None:
        run_gate = self._run_gate.snapshot()
        logger.log(
            BENCH_LEVEL,
            "bench {checkpoint}",
            checkpoint="sandbox_gate",
            running=run_gate.running,
            floor=run_gate.floor,
            max_concurrent=run_gate.max_concurrent,
            cpu_busy_percent=_rounded(run_gate.sample.cpu_busy_percent),
            memory_used_percent=_rounded(run_gate.sample.memory_used_percent),
        )


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 1)
