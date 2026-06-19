import abc

from sqlalchemy.ext.asyncio import AsyncSession

from database.config import BaseModel


class AbstractRepository(abc.ABC):
    """Root abstract base for all repositories."""


class AbstractSQLAlchemyRepository(AbstractRepository, abc.ABC):
    """Abstract base for repositories backed by a SQLAlchemy async session.

    Attributes:
        model: ORM model class the repository operates on.
    """

    model: type[BaseModel]

    def __init__(self, session: AsyncSession):
        self._session = session
