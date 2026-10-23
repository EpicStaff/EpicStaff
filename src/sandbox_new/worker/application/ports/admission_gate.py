"""The port the job consumer uses to decide when the next job may start.

The adapter behind it owns the policy (how many jobs, judged on which host signals);
the consumer only takes a slot before running a job and gives it back afterwards.
"""

import abc

__all__ = ["AbstractAdmissionGate"]


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
