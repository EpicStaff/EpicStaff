"""A Litestar application wired for the controller tests.

Built from the controllers directly rather than from ``main.app``: that application's
lifespan hooks open a database pool, connect to Redis and build the default venv, none
of which belong in a unit suite. ``debug=True`` so an unexpected failure shows its
traceback in the response body instead of a bare 500.

``runtime_state`` mirrors what the startup hooks publish on ``app.state`` -- the job
orchestrator's factory, the intake gate, the execution registry and the object store. It
is rebuilt here from fakes instead of imported, so importing this conftest does not
register the real runtime's startup hooks. The dependency providers are the real ones
from ``manager.bootstrap.di``; only ``uow`` is swapped for the fake, so a controller
reaching the object store goes through the same provider it would in production. The real
``cryptographer`` provider is registered uncached here, so each request builds it from
the settings the root conftest patches instead of keeping one for the whole process.

The error handlers are the real ones, so a test can assert the status a rejected request
actually gets rather than the one the controller hoped for.
"""

from functools import partial

import pytest
from foundation.utils.litestar import di, error_handler
from litestar.datastructures import State
from litestar.di import Provide
from litestar.testing import create_test_client

import manager.bootstrap  # noqa: F401  registers the error handlers below
from manager.application.holding import JobHoldingRegistry
from manager.application.intake import IntakeGate
from manager.application.orchestrators import JobOrchestrator
from manager.application.ports import AbstractUnitOfWork
from manager.application.registry import ExecutionRegistry
from manager.bootstrap import di as manager_di
from manager.presentation.rest.controllers import (
    CustomLibraryController,
    ExecutionController,
    VenvController,
    WheelController,
)
from tests.fakes import FakeJobDispatcher, FakeJobFailureSink

# Small, so a test reaches either cap with a few reservations.
MAX_ACCEPTED = 3
MAX_HELD = 2
QUEUE_TIMEOUT = 120.0
HOLD_TIMEOUT = 1800.0


@pytest.fixture
def holding() -> JobHoldingRegistry:
    return JobHoldingRegistry()


@pytest.fixture
def registry(clock) -> ExecutionRegistry:
    return ExecutionRegistry(clock=clock)


@pytest.fixture
def runtime_state(
    dispatcher: FakeJobDispatcher,
    holding: JobHoldingRegistry,
    failure_sink: FakeJobFailureSink,
    registry: ExecutionRegistry,
    file_storage,
) -> State:
    intake_gate = IntakeGate(
        registry,
        lambda: True,
        max_accepted=MAX_ACCEPTED,
        max_held=MAX_HELD,
        queue_timeout=QUEUE_TIMEOUT,
    )
    build_job_orchestrator = partial(
        JobOrchestrator,
        dispatcher=dispatcher,
        holding=holding,
        failure_sink=failure_sink,
        registry=registry,
        intake_gate=intake_gate,
        hold_timeout=HOLD_TIMEOUT,
    )
    return State(
        {
            "build_job_orchestrator": build_job_orchestrator,
            "intake_gate": intake_gate,
            "execution_registry": registry,
            "custom_library_storage": file_storage,
        }
    )


@pytest.fixture
def client(uow, runtime_state):
    async def provide_uow() -> AbstractUnitOfWork:
        return uow

    with create_test_client(
        route_handlers=[
            VenvController,
            ExecutionController,
            CustomLibraryController,
            WheelController,
        ],
        dependencies={
            **di.get_dependencies(),
            "uow": Provide(provide_uow),
            "cryptographer": Provide(manager_di.cryptographer, sync_to_thread=False),
        },
        state=runtime_state,
        exception_handlers=error_handler.get_handlers(),
        debug=True,
    ) as test_client:
        yield test_client
