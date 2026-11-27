from typing import cast

from foundation.s3_file_storage import S3FileStorage
from foundation.utils import task_scheduler
from foundation.utils.litestar import lifespan
from litestar import Litestar
from piccolo.engine import Engine, engine_finder

from manager import settings
from manager.application.orchestrators import VenvBuildOrchestrator, VenvCRUDOrchestrator
from manager.domain.enums import VenvStatus
from manager.domain.models import SYSTEM_VENV_LIBS
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
async def prepare_system_venvs(app: Litestar):
    """Declare and build every venv the sandbox owns before it takes any work.

    They are part of a working sandbox, not something to finish later: code without a
    venv and the built-in nodes run in them. One that cannot be built stops the start,
    and the next start tries it again. Registered after the hook that opens the object
    store, because building a venv may install a library kept there.

    Raises:
        RuntimeError: A system venv failed to build.
    """
    uow = PiccoloUnitOfWork()
    venv_crud_orchestrator = VenvCRUDOrchestrator(uow)
    venv_build_orchestrator = VenvBuildOrchestrator(
        uow, UVProvider(), app.state.custom_library_storage
    )
    for system_key in SYSTEM_VENV_LIBS:
        venv = await venv_crud_orchestrator.declare_system(system_key)
        venv = await venv_build_orchestrator.prepare(venv)
        if venv.status is not VenvStatus.COMPLETED:
            raise RuntimeError(f"The {system_key} venv failed to build: {venv.error}")


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
