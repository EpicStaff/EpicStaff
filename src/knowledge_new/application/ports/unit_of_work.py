import abc
from contextlib import AbstractAsyncContextManager

from domain.ports.repositories import AbstractGraphRagRepository, AbstractNaiveRagRepository


class AbstractUnitOfWork(AbstractAsyncContextManager, abc.ABC):
    """Abstract async context manager defining the unit-of-work contract."""

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.rollback()

    @abc.abstractmethod
    async def rollback(self):
        """Roll back the current transaction."""

    @abc.abstractmethod
    async def commit(self):
        """Commit the current transaction."""

    @property
    @abc.abstractmethod
    def naive_rag_repo(self) -> AbstractNaiveRagRepository:
        """Active `AbstractNaiveRagRepository` for this unit of work."""

    @property
    @abc.abstractmethod
    def graph_rag_repo(self) -> AbstractGraphRagRepository:
        """Active `AbstractGraphRagRepository` for this unit of work."""
