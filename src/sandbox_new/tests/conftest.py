"""Shared test configuration.

The environment block runs before any project import on purpose: ``settings`` reads
these variables at import time with no defaults, and ``manager.application`` imports
``settings`` at module level. ``RUN_IN_DOCKER`` keeps ``settings`` from reading the
developer's local ``.env``, so the suite behaves the same everywhere.
"""

import os

_TEST_ENVIRONMENT = {
    "RUN_IN_DOCKER": "true",
    "SANDBOX_DB_USER": "sandbox",
    "SANDBOX_DB_PASSWORD": "sandbox",
    "DB_HOST": "localhost",
    "DB_PORT": "5432",
    "DB_NAME": "sandbox",
    "CODE_RESULT_CHANNEL": "code:results",
    "STORAGE_MUTATION_CHANNEL": "storage:mutations",
    "REDIS_HOST": "localhost",
    "REDIS_PORT": "6379",
    "SANDBOX_MAX_EXECUTION_TIMEOUT": "30m",
    "SANDBOX_DEFAULT_EXECUTION_TIMEOUT": "5m",
    "SANDBOX_QUEUE_TIMEOUT": "2m",
    "SANDBOX_HOLD_TIMEOUT": "30m",
    "SANDBOX_MAX_RESULT_SIZE": "16mb",
    "STORAGE_PORT": "9000",
    "STORAGE_HOST": "localhost",
    "STORAGE_SSL": "false",
    "STORAGE_BUCKET": "sandbox",
}

for _name, _value in _TEST_ENVIRONMENT.items():
    os.environ.setdefault(_name, _value)

import pytest  # noqa: E402
from loguru import logger  # noqa: E402
from src.shared.bench_log import BENCH_LEVEL  # noqa: E402

from tests.builders import make_venv  # noqa: E402
from tests.fakes import (  # noqa: E402
    FakeClock,
    FakeIsolationProbe,
    FakeJobDispatcher,
    FakeJobFailureSink,
    FakeResultSink,
    FakeUnitOfWork,
    FakeUVProvider,
    FakeVenvRepository,
)


@pytest.fixture
def checkpoints():
    """The BENCH checkpoints logged during the test, as their extra fields, in order."""
    logged: list[dict] = []
    sink_id = logger.add(
        lambda message: logged.append(dict(message.record["extra"])),
        level=BENCH_LEVEL,
        filter=lambda record: record["level"].no == BENCH_LEVEL,
    )
    yield logged
    logger.remove(sink_id)


@pytest.fixture
def venv_repository() -> FakeVenvRepository:
    return FakeVenvRepository()


@pytest.fixture
def uow(venv_repository: FakeVenvRepository) -> FakeUnitOfWork:
    return FakeUnitOfWork(venv_repository)


@pytest.fixture
def uv_provider() -> FakeUVProvider:
    return FakeUVProvider()


@pytest.fixture
def dispatcher() -> FakeJobDispatcher:
    return FakeJobDispatcher()


@pytest.fixture
def failure_sink() -> FakeJobFailureSink:
    return FakeJobFailureSink()


@pytest.fixture
def result_sink() -> FakeResultSink:
    return FakeResultSink()


@pytest.fixture
def isolation_probe() -> FakeIsolationProbe:
    return FakeIsolationProbe()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def venvs_dir(tmp_path, monkeypatch):
    """Point the venv settings at tmp_path and return the venvs root.

    ``VenvBuildOrchestrator`` reads ``settings.VENVS_DIR`` and
    ``settings.VENV_STAGING_DIR`` at call time, so patching the module attributes is
    enough; no import-order trickery is needed.
    """
    import settings

    root = tmp_path / "venvs"
    staging = root / "builds"
    root.mkdir()
    staging.mkdir()
    monkeypatch.setattr(settings, "VENVS_DIR", root)
    monkeypatch.setattr(settings, "VENV_STAGING_DIR", staging)
    monkeypatch.setattr(settings, "PREDEFINED_VENV_PACKAGES", (tmp_path / "shared" / "dotdict",))
    return root


@pytest.fixture
def completed_venv(venv_repository: FakeVenvRepository):
    from manager.domain.enums import VenvStatus

    return venv_repository.seed(
        make_venv(name="default", status=VenvStatus.COMPLETED, hash="1deadbeef")
    )[0]
