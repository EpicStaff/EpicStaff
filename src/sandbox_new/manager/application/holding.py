"""In-RAM holding for jobs whose venv is still being built.

The manager only dispatches a job once its venv is COMPLETED. Jobs that arrive before
that wait here, keyed by venv, and are released when the venv finishes building, or
when their hold deadline passes first. Jobs are never persisted: this registry lives
only in memory, so a restart drops whatever was waiting -- acceptable, since a dropped
submission is re-sent, never silently half-run.
"""

from manager.domain.models import Job

__all__ = ["JobHoldingRegistry"]


class JobHoldingRegistry:
    def __init__(self) -> None:
        # Venv id -> (hold deadline, job) pairs, in the order the jobs arrived.
        self._by_venv: dict[int, list[tuple[float, Job]]] = {}

    def hold(self, venv_id: int, job: Job, *, deadline: float) -> None:
        """Keep ``job`` until ``venv_id`` is built, or until the clock reaches ``deadline``."""
        self._by_venv.setdefault(venv_id, []).append((deadline, job))

    def release(self, venv_id: int) -> list[Job]:
        """Remove and return every job waiting on ``venv_id``."""
        return [job for _, job in self._by_venv.pop(venv_id, [])]

    def release_overdue(self, now: float) -> list[Job]:
        """Remove and return every job whose hold deadline is at or before ``now``."""
        overdue: list[Job] = []
        for venv_id, held in list(self._by_venv.items()):
            waiting = [(deadline, job) for deadline, job in held if deadline > now]
            overdue.extend(job for deadline, job in held if deadline <= now)
            if waiting:
                self._by_venv[venv_id] = waiting
            else:
                del self._by_venv[venv_id]
        return overdue

    def pending_venv_ids(self) -> list[int]:
        return list(self._by_venv)
