"""Transaction-less stand-in for the unit of work.

Records how often it was entered, committed and rolled back, which is what the
orchestrator tests assert on: an operation that fails must not commit.
"""

from manager.application.ports import AbstractUnitOfWork
from manager.domain.ports import AbstractVenvRepository

from tests.fakes.repositories import FakeVenvRepository

__all__ = ["FakeUnitOfWork"]


class FakeUnitOfWork(AbstractUnitOfWork):
    def __init__(self, venv_repo: AbstractVenvRepository | None = None) -> None:
        self._venv_repo = venv_repo if venv_repo is not None else FakeVenvRepository()
        self.entered = 0
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self) -> "FakeUnitOfWork":
        self.entered += 1
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    @property
    def venv_repo(self) -> AbstractVenvRepository:
        return self._venv_repo
