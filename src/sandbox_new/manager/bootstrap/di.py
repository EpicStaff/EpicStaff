import asyncio

from foundation.cryptographer import AbstractCryptographer, FernetRotatedCryptographer
from foundation.utils.litestar import di
from litestar.datastructures import State

from manager import settings
from manager.application.orchestrators import JobOrchestrator
from manager.application.ports import (
    AbstractFileStorage,
    AbstractJobFailureSink,
    AbstractUnitOfWork,
)
from manager.application.registry import ExecutionRegistry
from manager.application.worker_contact import WorkerContact
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


@di.register
async def worker_contact(state: State) -> WorkerContact:
    """Return the runtime's single worker-contact record, published on startup."""
    return state.worker_contact


@di.register
async def job_queue(state: State) -> asyncio.Queue:
    """Return the runtime's job queue the worker pulls from, published on startup."""
    return state.job_queue


@di.register
async def result_queue(state: State) -> asyncio.Queue:
    """Return the runtime's result queue the result consumer drains, published on startup."""
    return state.result_queue


@di.register
async def job_failure_sink(state: State) -> AbstractJobFailureSink:
    """Return the runtime's failure sink, published on startup."""
    return state.job_failure_sink
