from foundation.utils.litestar import di
from litestar.datastructures import State

from manager.application.orchestrators import JobOrchestrator
from manager.application.ports import AbstractUnitOfWork
from manager.application.registry import ExecutionRegistry
from manager.infrastructure.database.unit_of_work import PiccoloUnitOfWork


@di.register
async def uow() -> AbstractUnitOfWork:
    return PiccoloUnitOfWork()


@di.register
async def job_orchestrator(state: State, uow: AbstractUnitOfWork) -> JobOrchestrator:
    """Build the request's orchestrator from the factory the runtime published on startup."""
    return state.build_job_orchestrator(uow)


@di.register
async def execution_registry(state: State) -> ExecutionRegistry:
    """Return the runtime's single execution registry, published on startup."""
    return state.execution_registry
