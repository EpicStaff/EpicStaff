from collections.abc import Callable

import settings
from foundation.cryptographer import AbstractCryptographer, FernetRotatedCryptographer
from infrastructure.database.unit_of_work import SQLAlchemyUnitOfWork
from litestar.di import Provide

__all__ = ["get_dependencies"]

from infrastructure.task_register import TaskRegister

_dependencies: dict[str, Provide] = {}


def get_dependencies() -> dict[str, Provide]:
    return _dependencies


def register(
    fn: Callable | None = None,
    /,
    use_cache=False,
    sync_to_thread: bool | None = None,
):
    def decorator(func: Callable):
        _dependencies[func.__name__] = Provide(
            func,
            use_cache=use_cache,
            sync_to_thread=sync_to_thread,
        )
        return func

    if fn is None:
        return decorator
    else:
        return decorator(fn)


@register(sync_to_thread=False)
def uow() -> SQLAlchemyUnitOfWork:
    return SQLAlchemyUnitOfWork()


@register(use_cache=True, sync_to_thread=False)
def task_register() -> TaskRegister:
    return TaskRegister()


@register(use_cache=True, sync_to_thread=False)
def cryptographer() -> AbstractCryptographer:
    return FernetRotatedCryptographer(
        settings.SECRETS_TRANSPORT_KEY,
        settings.SECRETS_TRANSPORT_PREVIOUS_KEYS,
        hkdf_info=settings.SECRETS_TRANSPORT_HKDF_INFO.encode(),
    )
