import abc
from contextlib import AbstractAsyncContextManager

__all__ = ["AbstractUnitOfWork"]


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

    # @property
    # @abc.abstract
    # def <name>_repo(self) -> <abstract-repo-class>:
    #   pass
