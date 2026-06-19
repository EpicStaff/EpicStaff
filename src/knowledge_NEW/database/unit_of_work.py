import abc
from contextlib import AbstractAsyncContextManager

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from database.config import SessionLocal
from database.repositories import (
    NaiveRagSQLAlchemyRepository,
)

__all__ = [
    "AbstractUnitOfWork",
    "SQLAlchemyUnitOfWork",
]


class AbstractUnitOfWork(AbstractAsyncContextManager, abc.ABC):
    """Abstract async unit of work grouping repository operations into one transaction.

    Subclasses must implement `commit` and `rollback`; exiting the context
    manager rolls back any uncommitted work.
    """

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.rollback()

    @abc.abstractmethod
    async def rollback(self):
        """Discard all changes made in the current transaction."""
        pass

    @abc.abstractmethod
    async def commit(self):
        """Persist all changes made in the current transaction."""
        pass


class SQLAlchemyUnitOfWork(AbstractUnitOfWork):
    """SQLAlchemy-backed unit of work that opens a session per context."""

    def __init__(self, session_factory: async_sessionmaker = SessionLocal):
        self._session_factory = session_factory
        self._session = None
        self._naive_rag_repo = None

    async def __aenter__(self):
        self._session = self._session_factory()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.rollback()
        await self.session.close()
        self._session = None
        self._naive_rag_repo = None

    async def rollback(self):
        """Roll back the current session."""
        await self.session.rollback()

    async def commit(self):
        """Commit the current session."""
        await self.session.commit()

    @property
    def session(self) -> AsyncSession:
        """Active session, raising `RuntimeError` when used outside the context manager."""
        if self._session is None:
            raise RuntimeError("UnitOfWork used outside its context manager.")
        return self._session

    @property
    def naive_rag_repo(self) -> NaiveRagSQLAlchemyRepository:
        """Naive RAG repository bound to the active session."""
        if self._naive_rag_repo is None:
            self._naive_rag_repo = NaiveRagSQLAlchemyRepository(self.session)
        return self._naive_rag_repo
