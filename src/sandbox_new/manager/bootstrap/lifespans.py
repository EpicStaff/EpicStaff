from typing import cast

import settings
from foundation.s3_file_storage import S3FileStorage
from foundation.utils import task_scheduler
from foundation.utils.litestar import lifespan
from litestar import Litestar
from piccolo.engine import Engine, engine_finder

from manager.application.orchestrators import VenvBuildOrchestrator, VenvCRUDOrchestrator
from manager.domain.models import DEFAULT_VENV_NAME
from manager.infrastructure.database.unit_of_work import PiccoloUnitOfWork
from manager.infrastructure.providers import FileStorage, UVProvider


@lifespan.on_startup
async def start_database_pool():
    engine = cast(Engine, engine_finder())
    await engine.start_connection_pool()


@lifespan.on_startup
async def open_custom_library_storage(app: Litestar):
    """Open the bucket custom libraries are kept in and publish it for the request path.

    Created here rather than provisioned alongside the service: the bucket is this
    service's own, nothing outside it knows the name, and a deployment should not have
    to make one by hand before the first upload.

    Reaching the object store is a condition of starting, the same way the database is:
    the service already declares it as a dependency, and a half-started service that
    accepts uploads it cannot store would be worse than one that does not come up.
    """
    bucket = S3FileStorage(
        host=settings.STORAGE_HOST,
        port=settings.STORAGE_PORT,
        user=settings.STORAGE_USER,
        password=settings.STORAGE_PASSWORD,
        use_ssl=settings.STORAGE_SSL,
    ).bucket(settings.CUSTOM_LIBRARY_BUCKET)

    if not await bucket.aexist():
        await bucket.acreate()

    app.state.custom_library_storage = FileStorage(bucket)


@lifespan.on_shutdown
async def stop_database_pool():
    engine = cast(Engine, engine_finder())
    await engine.close_connection_pool()


@lifespan.on_startup
async def create_default_venv_if_not_exist(app: Litestar):
    """Build the shared fallback venv. Registered after the hook that opens the object
    store, because building a venv may now install a library kept there."""
    uow = PiccoloUnitOfWork()

    venv_crud_orchestrator = VenvCRUDOrchestrator(uow)
    venv = await venv_crud_orchestrator.retrieve_default()
    if venv is None:
        venv = await venv_crud_orchestrator.create(name=DEFAULT_VENV_NAME, libs=[])

    uv_provider = UVProvider()
    venv_build_orchestrator = VenvBuildOrchestrator(
        uow, uv_provider, app.state.custom_library_storage
    )
    await venv_build_orchestrator.build(venv)


@lifespan.on_startup
async def start_scheduled_tasks(app: Litestar):
    """Start the background work, registering what the decorators could not.

    These tasks need the object store, which is opened by the hook above and has no
    business being opened a second time here, so they are handed it rather than
    reaching for it. Registration has to happen before `start`, which is why it is in
    this hook and not at import time.
    """
    from manager.presentation import tasks

    file_storage = app.state.custom_library_storage

    # Closures rather than `partial`: the scheduler names the work by `__name__` when it
    # reports a failure, and a partial has none -- it would raise inside the handler that
    # was reporting the real error and hide it.
    async def build_declared_wheel():
        await tasks.build_declared_wheel(file_storage)

    async def reap_deleted_custom_libraries():
        await tasks.reap_deleted_custom_libraries(file_storage)

    async def build_declared_venv():
        await tasks.build_declared_venv(file_storage)

    task_scheduler.schedule(build_declared_wheel, interval=5)
    task_scheduler.schedule(reap_deleted_custom_libraries, interval=60)
    task_scheduler.schedule(build_declared_venv, interval=5)

    await task_scheduler.start()


@lifespan.on_shutdown
async def stop_scheduled_tasks():
    await task_scheduler.stop()
