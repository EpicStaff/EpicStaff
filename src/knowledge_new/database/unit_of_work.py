import abc
from contextlib import AbstractAsyncContextManager

from database.config import SessionLocal
from database.repositories.base import AbstractGraphRagRepository, AbstractNaiveRagRepository
from database.repositories.graph import GraphRagSQLAlchemyRepository
from database.repositories.naive import NaiveRagSQLAlchemyRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

__all__ = ["AbstractUnitOfWork", "SQLAlchemyUnitOfWork"]


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


class SQLAlchemyUnitOfWork(AbstractUnitOfWork):
    def __init__(self, session_factory: async_sessionmaker = SessionLocal):
        self._session_factory = session_factory
        self._session = None
        self._naive_rag_repo = None
        self._graph_rag_repo = None

    async def __aenter__(self):
        self._session = self._session_factory()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.rollback()
        await self.session.close()
        self._session = None
        self._naive_rag_repo = None
        self._graph_rag_repo = None

    async def rollback(self):
        await self.session.rollback()

    async def commit(self):
        await self.session.commit()

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("UnitOfWork used outside its context manager.")
        return self._session

    @property
    def naive_rag_repo(self) -> AbstractNaiveRagRepository:
        if self._naive_rag_repo is None:
            self._naive_rag_repo = NaiveRagSQLAlchemyRepository(self.session)
        return self._naive_rag_repo

    @property
    def graph_rag_repo(self) -> AbstractGraphRagRepository:
        if self._graph_rag_repo is None:
            self._graph_rag_repo = GraphRagSQLAlchemyRepository(self.session)
        return self._graph_rag_repo
