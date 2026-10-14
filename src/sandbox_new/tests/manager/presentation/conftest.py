"""A Litestar application wired for the controller tests.

Built from the controllers directly rather than from ``main.app``: that application's
lifespan hooks open a database pool, connect to Redis and build the default venv, none
of which belong in a unit suite. ``debug=True`` so an unexpected failure shows its
traceback in the response body instead of a bare 500.

``job_intake`` mirrors what ``common.bootstrap.lifespan`` publishes on ``app.state``. It
is rebuilt here from fakes instead of imported, so importing this conftest does not
register the real runtime's startup hooks.

The error handlers are the real ones, so a test can assert the status a rejected request
actually gets rather than the one the controller hoped for.
"""

from dataclasses import dataclass

import pytest
from foundation.utils.litestar import error_handler
from litestar.datastructures import State
from litestar.di import Provide
from litestar.testing import create_test_client

import manager.bootstrap  # noqa: F401  registers the error handlers below
from manager.application.holding import JobHoldingRegistry
from manager.application.ports import AbstractUnitOfWork
from manager.presentation.rest.controllers import ExecutionController, VenvController
from tests.fakes import FakeJobDispatcher, FakeJobFailureSink


@dataclass
class JobIntakeDouble:
    dispatcher: FakeJobDispatcher
    holding: JobHoldingRegistry
    failure_sink: FakeJobFailureSink


@pytest.fixture
def holding() -> JobHoldingRegistry:
    return JobHoldingRegistry()


@pytest.fixture
def job_intake(dispatcher, holding, failure_sink) -> JobIntakeDouble:
    return JobIntakeDouble(dispatcher=dispatcher, holding=holding, failure_sink=failure_sink)


@pytest.fixture
def client(uow, job_intake):
    async def provide_uow() -> AbstractUnitOfWork:
        return uow

    with create_test_client(
        route_handlers=[VenvController, ExecutionController],
        dependencies={"uow": Provide(provide_uow)},
        state=State({"job_intake": job_intake}),
        exception_handlers=error_handler.get_handlers(),
        debug=True,
    ) as test_client:
        yield test_client
