from typing import cast

from foundation.utils import task_scheduler
from foundation.utils.litestar import lifespan
from piccolo.engine import Engine, engine_finder

from manager.application.orchestrators import VenvBuildOrchestrator, VenvCRUDOrchestrator
from manager.domain.models import DEFAULT_VENV_NAME
from manager.infrastructure.database.unit_of_work import PiccoloUnitOfWork
from manager.infrastructure.providers import UVProvider


@lifespan.on_startup
async def start_database_pool():
    engine = cast(Engine, engine_finder())
    await engine.start_connection_pool()


@lifespan.on_shutdown
async def stop_database_pool():
    engine = cast(Engine, engine_finder())
    await engine.close_connection_pool()


@lifespan.on_startup
async def create_default_venv_if_not_exist():
    uow = PiccoloUnitOfWork()

    venv_crud_orchestrator = VenvCRUDOrchestrator(uow)
    venv = await venv_crud_orchestrator.retrieve_default()
    if venv is None:
        venv = await venv_crud_orchestrator.create(name=DEFAULT_VENV_NAME, libs=[])

    uv_provider = UVProvider()
    venv_build_orchestrator = VenvBuildOrchestrator(uow, uv_provider)
    await venv_build_orchestrator.build(venv)


@lifespan.on_startup
async def start_scheduled_tasks():
    import manager.presentation.tasks  # noqa: F401  registers @schedule tasks

    await task_scheduler.start()


@lifespan.on_shutdown
async def stop_scheduled_tasks():
    await task_scheduler.stop()
