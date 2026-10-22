"""In-RAM holding for jobs whose venv is still being built.

The manager only dispatches a job once its venv is COMPLETED. Jobs that arrive before
that wait here, keyed by venv, and are released when the venv finishes building.
Jobs are never persisted: this registry lives only in memory, so a restart drops
whatever was waiting -- acceptable, since a dropped submission is re-sent, never
silently half-run.
"""

from manager.domain.models import Job

__all__ = ["JobHoldingRegistry"]


class JobHoldingRegistry:
    def __init__(self) -> None:
        self._by_venv: dict[int, list[Job]] = {}

    def hold(self, venv_id: int, job: Job) -> None:
        self._by_venv.setdefault(venv_id, []).append(job)

    def release(self, venv_id: int) -> list[Job]:
        """Remove and return every job waiting on ``venv_id``."""
        return self._by_venv.pop(venv_id, [])

    def pending_venv_ids(self) -> list[int]:
        return list(self._by_venv)
