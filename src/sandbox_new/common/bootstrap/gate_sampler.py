"""Logs the `sandbox_gate` BENCH checkpoint: both admission gates' state, every few seconds.

The checkpoint reads the manager's intake side (queued and held executions, the drain
rate, the 503 refusals since the previous sample) next to the worker's run gate (slots in
use, its limits, the load it last read), so a benchmark can tell which limit was the one
holding work back. It lives in the composition root because it is the one place allowed
to see both sides of the seam.
"""

import asyncio

from loguru import logger
from manager.application.intake import IntakeGate
from manager.application.registry import ExecutionRegistry
from src.shared.bench_log import BENCH_LEVEL
from worker.application.resource_gate import ResourceAdmissionGate

__all__ = ["SAMPLE_INTERVAL_SECONDS", "GateSampler"]

SAMPLE_INTERVAL_SECONDS = 5.0


class GateSampler:
    """Log one `sandbox_gate` checkpoint per interval; a failed sample is skipped, not fatal.

    Each sample reads and resets the intake gate's refusal counters, so the refusals it
    reports are the ones since the previous sample.
    """

    def __init__(
        self,
        registry: ExecutionRegistry,
        intake_gate: IntakeGate,
        run_gate: ResourceAdmissionGate,
        *,
        interval: float = SAMPLE_INTERVAL_SECONDS,
    ) -> None:
        self._registry = registry
        self._intake_gate = intake_gate
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
        drain_rate = self._registry.drain_rate()
        refusals = self._intake_gate.take_refusals()
        logger.log(
            BENCH_LEVEL,
            "bench {checkpoint}",
            checkpoint="sandbox_gate",
            running=run_gate.running,
            floor=run_gate.floor,
            max_concurrent=run_gate.max_concurrent,
            cpu_busy_percent=_rounded(run_gate.sample.cpu_busy_percent, 1),
            memory_used_percent=_rounded(run_gate.sample.memory_used_percent, 1),
            queued=self._registry.queued_count,
            held=self._registry.held_count,
            drain_rate=_rounded(drain_rate, 3),
            refused_cap=refusals["cap"],
            refused_prediction=refusals["prediction"],
            refused_held_cap=refusals["held_cap"],
            refused_in_progress=refusals["in_progress"],
        )


def _rounded(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)
