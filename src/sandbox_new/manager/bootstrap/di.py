import settings
from foundation.cryptographer import AbstractCryptographer, FernetRotatedCryptographer
from foundation.utils.litestar import di
from litestar.datastructures import State

from manager.application.orchestrators import JobOrchestrator
from manager.application.ports import AbstractFileStorage, AbstractUnitOfWork
from manager.application.registry import ExecutionRegistry
from manager.infrastructure.database.unit_of_work import PiccoloUnitOfWork


@di.register
async def uow() -> AbstractUnitOfWork:
    return PiccoloUnitOfWork()


@di.register
async def file_storage(state: State) -> AbstractFileStorage:
    return state.custom_library_storage


@di.register(use_cache=True, sync_to_thread=False)
def cryptographer() -> AbstractCryptographer:
    """Build the cryptographer that opens transport-sealed secrets.

    Cached by Litestar, so the request path and the held-job releaser share one instance.
    """
    return FernetRotatedCryptographer(
        settings.SECRETS_TRANSPORT_KEY,
        settings.SECRETS_TRANSPORT_PREVIOUS_KEYS,
        hkdf_info=settings.SECRETS_TRANSPORT_HKDF_INFO.encode(),
    )


@di.register
async def job_orchestrator(
    state: State, uow: AbstractUnitOfWork, cryptographer: AbstractCryptographer
) -> JobOrchestrator:
    """Build the request's orchestrator from the factory the runtime published on startup."""
    return state.build_job_orchestrator(uow, cryptographer=cryptographer)


@di.register
async def execution_registry(state: State) -> ExecutionRegistry:
    """Return the runtime's single execution registry, published on startup."""
    return state.execution_registry
