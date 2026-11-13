"""Logs the `sandbox_intake` BENCH checkpoint: the manager's admission side, every few seconds.

The worker logs its own `sandbox_gate` line; a benchmark reads the two side by side to
tell which limit was the one holding work back. The sampler is a neutral observer: it
sees the intake only through the protocol below and imports no implementation class.
"""

import asyncio
from typing import Protocol

from loguru import logger
from src.shared.bench_log import BENCH_LEVEL

__all__ = ["SAMPLE_INTERVAL_SECONDS", "IntakeMetrics", "IntakeSampler"]

SAMPLE_INTERVAL_SECONDS = 5.0


class IntakeMetrics(Protocol):
    """The manager's intake side, as the sampler reads it."""

    @property
    def queued_count(self) -> int: ...

    @property
    def held_count(self) -> int: ...

    def drain_rate(self) -> float | None: ...


class IntakeSampler:
    """Log one `sandbox_intake` checkpoint per interval; a failed sample is skipped, not fatal."""

    def __init__(self, intake: IntakeMetrics, *, interval: float = SAMPLE_INTERVAL_SECONDS):
        self._intake = intake
        self._interval = interval

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                self._sample()
            except Exception as error:
                logger.error("Intake sample failed: {}", type(error).__name__)

    def _sample(self) -> None:
        drain_rate = self._intake.drain_rate()
        logger.log(
            BENCH_LEVEL,
            "bench {checkpoint}",
            checkpoint="sandbox_intake",
            queued=self._intake.queued_count,
            held=self._intake.held_count,
            drain_rate=None if drain_rate is None else round(drain_rate, 3),
        )
