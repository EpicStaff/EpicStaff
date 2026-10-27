"""A host-metrics reader that reports whatever floor and load the test sets.

Implements the metrics port, so the real gate is driven exactly as in production while
the test controls the one input it is about.
"""

from worker.application.ports import AbstractHostMetrics, HostSample

__all__ = ["FakeHostMetrics"]


class FakeHostMetrics(AbstractHostMetrics):
    def __init__(
        self, *, floor: int = 1, cpu: float | None = 10.0, memory: float | None = 10.0
    ) -> None:
        self.floor_value = floor
        self.reading = HostSample(cpu_busy_percent=cpu, memory_used_percent=memory)

    def floor(self) -> int:
        return self.floor_value

    def sample(self) -> HostSample:
        return self.reading
