import functools
import inspect
from collections.abc import Awaitable, Callable

from domain.errors import RepositoryError
from sqlalchemy.ext.asyncio import AsyncSession


class BaseSQLAlchemyRepositoryMixin:
    """SQLAlchemy session holder for concrete repository implementations."""

    def __init__(self, session: AsyncSession):
        self._session = session

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for name, obj in vars(cls).items():
            if inspect.iscoroutinefunction(obj) and not name.startswith("_"):
                setattr(cls, name, cls.__wrap_error_to_repository_error(obj))

    @staticmethod
    def __wrap_error_to_repository_error(func: Callable[..., Awaitable]):
        @functools.wraps(func)
        async def wrap(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except RepositoryError:
                raise
            except Exception as e:
                raise RepositoryError(function=func.__qualname__) from e

        return wrap
