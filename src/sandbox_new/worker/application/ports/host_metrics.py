"""The port the resource admission gate reads the container's CPU allowance and load from.

Reading them is a host fact, so it is infrastructure; the gate's policy depends on this
port only and stays in the application layer.
"""

import abc
from dataclasses import dataclass

__all__ = ["AbstractHostMetrics", "HostSample"]


@dataclass(frozen=True)
class HostSample:
    """One reading of host load; None for a signal that could not be read."""

    cpu_busy_percent: float | None
    memory_used_percent: float | None


class AbstractHostMetrics(abc.ABC):
    @abc.abstractmethod
    def floor(self) -> int:
        """How many CPUs the container may use, at least 1."""

    @abc.abstractmethod
    def sample(self) -> HostSample:
        """Read the current load; a signal that cannot be read is None."""
