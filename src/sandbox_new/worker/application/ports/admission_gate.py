"""The port the job consumer uses to decide when the next job may start.

The policy behind it (how many jobs, judged on which host signals) lives in the
application layer; the consumer only takes a slot before running a job and gives it
back afterwards.
"""

import abc
from dataclasses import dataclass

from worker.application.ports.host_metrics import HostSample

__all__ = ["AbstractAdmissionGate", "RunGateSnapshot"]


@dataclass(frozen=True)
class RunGateSnapshot:
    """What the gate is deciding on right now: slots in use, its limits, the last load sample."""

    running: int
    floor: int
    max_concurrent: int
    sample: HostSample


class AbstractAdmissionGate(abc.ABC):
    @abc.abstractmethod
    async def acquire(self) -> None:
        """Wait until a job may start, then take its slot.

        Cancelling the wait takes no slot.
        """

    @abc.abstractmethod
    def release(self) -> None:
        """Give back the slot of a job that has finished."""

    @abc.abstractmethod
    def has_free_slot(self) -> bool:
        """Whether `acquire` would take a slot right now without waiting."""

    @abc.abstractmethod
    def snapshot(self) -> RunGateSnapshot:
        """The gate's current state, for observing it without changing it."""
