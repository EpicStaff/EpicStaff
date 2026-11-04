from collections.abc import Callable

import settings
from infrastructure.database.unit_of_work import SQLAlchemyUnitOfWork
from infrastructure.graphrag.artifact_store import S3ArtifactStore
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
def artifact_store() -> S3ArtifactStore:
    return S3ArtifactStore(
        endpoint=settings.STORAGE_ENDPOINT,
        bucket=settings.KNOWLEDGE_BUCKET,
        access_key=settings.STORAGE_ACCESS_KEY,
        secret_key=settings.STORAGE_SECRET_KEY,
    )
