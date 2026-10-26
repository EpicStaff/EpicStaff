"""The manager-to-worker seam, end to end in one process.

Real queues, real pipeline, real child interpreter. Fakes only at the true edges: the
venv repository and the Landlock probe. This is the only test that would catch the
manager encoding a field the worker does not decode.
"""

import asyncio
import json
import sys
from pathlib import Path

import fakeredis.aioredis
import pytest

from common.contracts import ExecutionJobMessage, ExecutionResultMessage
from manager.application.holding import JobHoldingRegistry
from manager.application.intake import IntakeGate
from manager.application.orchestrators import JobOrchestrator
from manager.application.registry import ExecutionRegistry
from manager.domain.enums import VenvStatus
from manager.domain.models import StorageCredentials
from manager.infrastructure.transport.queue_job_dispatcher import QueueJobDispatcher
from manager.infrastructure.transport.queue_job_failure_sink import QueueJobFailureSink
from manager.infrastructure.transport.redis_result_publisher import RedisResultPublisher
from worker.application.orchestrator import ExecutionOrchestrator
from worker.application.pipeline import Pipeline
from worker.application.steps import BuildIsolationPlan, ConfigureStorageStep
from worker.infrastructure.execution.steps import (
    CaptureMutationsStep,
    CaptureResultStep,
    LaunchStep,
    PrepareWorkspaceStep,
    ResolveVenvStep,
    WrapCodeStep,
)
from worker.infrastructure.transport.queue_job_source import QueueJobSource
from worker.infrastructure.admission import ResourceAdmissionGate
from worker.infrastructure.transport.queue_result_sink import QueueResultSink
from worker.presentation.job_consumer import JobConsumer
from tests.builders import make_venv, make_worker_job
from tests.fakes import FakeClock, FakeHostMetrics, FakeIsolationProbe, FakeJobSource

VENV_HASH = "1integration"
EXECUTION_ID = "exec-integration"

CODE = """def main(value):
    print("token=s3cret")
    return {"echo": value, "limit": LIMIT}
"""

DOTDICT_STUB = """class DotDict(dict):
    pass


class DotObject:
    pass


class DotList(list):
    pass
"""

SECRETS_STUB = """def get_secret(name, default=None):
    return default
"""


@pytest.fixture
def runtime(tmp_path):
    """Everything the seam needs: the two queues, a venv on disk, and the child stubs."""
    venvs_dir = tmp_path / "venvs"
    executions_dir = tmp_path / "executions"
    savefiles_dir = tmp_path / "savefiles"

    venv_bin = venvs_dir / f"venv-{VENV_HASH}" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").symlink_to(Path(sys.executable))

    # Production installs these into every venv as predefined packages. The child's
    # sys.path[0] is the directory holding code.py, so stubs go there.
    exec_dir = executions_dir / EXECUTION_ID
    exec_dir.mkdir(parents=True)
    (exec_dir / "dotdict.py").write_text(DOTDICT_STUB, encoding="utf-8")
    (exec_dir / "epicstaff_secrets.py").write_text(SECRETS_STUB, encoding="utf-8")

    return {
        "job_queue": asyncio.Queue(),
        "result_queue": asyncio.Queue(),
        "venvs_dir": venvs_dir,
        "executions_dir": executions_dir,
        "savefiles_dir": savefiles_dir,
    }


def build_manager(uow, runtime) -> JobOrchestrator:
    registry = ExecutionRegistry()
    return JobOrchestrator(
        uow,
        QueueJobDispatcher(runtime["job_queue"]),
        JobHoldingRegistry(),
        QueueJobFailureSink(runtime["result_queue"]),
        registry,
        IntakeGate(registry, lambda: True, max_accepted=10, max_held=10, queue_timeout=120),
        queue_timeout=120,
        hold_timeout=1800,
    )


def build_worker(runtime) -> ExecutionOrchestrator:
    """The worker pipeline, with only the kernel probe faked out."""
    pipeline = (
        Pipeline()
        .register(ResolveVenvStep(venvs_dir=runtime["venvs_dir"]))
        .register(
            PrepareWorkspaceStep(
                executions_dir=runtime["executions_dir"],
                savefiles_root=runtime["savefiles_dir"],
            )
        )
        .register(
            ConfigureStorageStep(
                storage_endpoint="http://localhost:9000",
                storage_bucket="sandbox",
            )
        )
        .register(WrapCodeStep())
        .register(
            BuildIsolationPlan(
                FakeIsolationProbe(0),
                require_isolation=False,
                block_network=False,
                require_signal_isolation=False,
                storage_port=9000,
            )
        )
        .register(LaunchStep(default_timeout=30, min_timeout=0, max_timeout=None))
        .register(CaptureMutationsStep())
        .register(CaptureResultStep())
    )
    return ExecutionOrchestrator(
        pipeline,
        result_sink=QueueResultSink(runtime["result_queue"]),
        mask_secrets=True,
    )


async def test_a_submission_runs_and_its_result_comes_back(uow, runtime):
    venv = uow.venv_repo.seed(
        make_venv(status=VenvStatus.COMPLETED, hash=VENV_HASH)
    )[0]
    manager = build_manager(uow, runtime)

    await manager.submit(
        execution_id=EXECUTION_ID,
        session_id=7,
        code=CODE,
        entrypoint="main",
        global_kwargs={"LIMIT": 3},
        func_kwargs={"value": "x"},
        secrets={"TOKEN": "s3cret"},
        venv_id=venv.id,
        use_storage=False,
        storage_allowed_paths=[],
        storage_org_prefix=None,
        storage_credentials=None,
        timeout=None,
        reply_to_crew_channel=False,
    )

    job = await QueueJobSource(runtime["job_queue"]).get()
    assert job.venv_hash == VENV_HASH
    assert job.func_kwargs == {"value": "x"}
    assert job.secrets == {"TOKEN": "s3cret"}
    assert job.queue_deadline is not None

    await build_worker(runtime).execute(job)

    message: ExecutionResultMessage = runtime["result_queue"].get_nowait()
    assert message.execution_id == EXECUTION_ID
    assert message.returncode == 0
    assert message.ran is True
    assert message.session_id == 7
    assert json.loads(message.result) == {"echo": "x", "limit": 3}
    assert "token=[REDACTED]" in message.stdout
    assert "s3cret" not in message.stdout


async def test_a_job_whose_venv_failed_to_build_reaches_the_same_result_queue(uow, runtime):
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.FAILED, error="uv blew up"))[0]
    manager = build_manager(uow, runtime)

    await manager.submit(
        execution_id=EXECUTION_ID,
        session_id=7,
        code=CODE,
        entrypoint="main",
        global_kwargs={},
        func_kwargs={},
        secrets={},
        venv_id=venv.id,
        use_storage=False,
        storage_allowed_paths=[],
        storage_org_prefix=None,
        storage_credentials=None,
        timeout=None,
        reply_to_crew_channel=False,
    )

    assert runtime["job_queue"].empty()
    message: ExecutionResultMessage = runtime["result_queue"].get_nowait()
    assert message.execution_id == EXECUTION_ID
    assert message.returncode == 1
    assert message.ran is False
    assert "failed to build" in message.stderr
    assert (message.session_id, message.not_run_reason) == (7, "venv_failed")


async def test_storage_credentials_reach_the_worker_unchanged(uow, runtime):
    """The credentials the caller issued must survive the manager-to-worker encoding."""
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.COMPLETED, hash=VENV_HASH))[0]
    manager = build_manager(uow, runtime)

    await manager.submit(
        execution_id=EXECUTION_ID,
        session_id=7,
        code=CODE,
        entrypoint="main",
        global_kwargs={},
        func_kwargs={},
        secrets={},
        venv_id=venv.id,
        use_storage=True,
        storage_allowed_paths=["docs/"],
        storage_org_prefix="org1",
        storage_credentials=StorageCredentials(access_key="AK123", secret_key="SK456"),
        timeout=None,
        reply_to_crew_channel=False,
    )

    job = await QueueJobSource(runtime["job_queue"]).get()
    assert job.storage_credentials.access_key == "AK123"
    assert job.storage_credentials.secret_key == "SK456"


async def test_a_crew_submission_is_still_flagged_on_the_result_that_comes_back(uow, runtime):
    """The routing flag has to survive the manager, the worker and the way back.

    The manager is what publishes, so a flag that got lost anywhere along this path
    would send crew's result to the shared channel and leave crew waiting.
    """
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.COMPLETED, hash=VENV_HASH))[0]
    manager = build_manager(uow, runtime)

    await manager.submit(
        execution_id=EXECUTION_ID,
        session_id=7,
        code=CODE,
        entrypoint="main",
        global_kwargs={"LIMIT": 3},
        func_kwargs={"value": "x"},
        secrets={},
        venv_id=venv.id,
        use_storage=False,
        storage_allowed_paths=[],
        storage_org_prefix=None,
        storage_credentials=None,
        timeout=None,
        reply_to_crew_channel=True,
    )

    job = await QueueJobSource(runtime["job_queue"]).get()
    await build_worker(runtime).execute(job)

    message: ExecutionResultMessage = runtime["result_queue"].get_nowait()
    assert message.returncode == 0
    assert message.reply_to_crew_channel is True


async def test_a_crew_submission_whose_venv_failed_is_still_flagged(uow, runtime):
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.FAILED, error="uv blew up"))[0]
    manager = build_manager(uow, runtime)

    await manager.submit(
        execution_id=EXECUTION_ID,
        session_id=7,
        code=CODE,
        entrypoint="main",
        global_kwargs={},
        func_kwargs={},
        secrets={},
        venv_id=venv.id,
        use_storage=False,
        storage_allowed_paths=[],
        storage_org_prefix=None,
        storage_credentials=None,
        timeout=None,
        reply_to_crew_channel=True,
    )

    message: ExecutionResultMessage = runtime["result_queue"].get_nowait()
    assert message.returncode == 1
    assert message.reply_to_crew_channel is True


async def test_a_job_that_expired_in_the_queue_is_published_as_overloaded(runtime, checkpoints):
    """The worker's reason has to survive its result sink for the manager to report it."""
    clock = FakeClock()
    job = make_worker_job(execution_id=EXECUTION_ID, session_id=7, queue_deadline=clock.now - 1)
    run_gate = ResourceAdmissionGate(
        FakeHostMetrics(),
        min_concurrent=1,
        max_concurrent=1,
        cpu_threshold=85,
        memory_threshold=80,
    )
    consumer = JobConsumer(
        FakeJobSource(job), build_worker(runtime), run_gate, queue_timeout=120, clock=clock
    )
    redis = fakeredis.aioredis.FakeRedis()
    publisher = RedisResultPublisher(
        redis,
        result_channel="code:results",
        crew_result_channel="code:results:crew",
        mutation_channel="storage:mutations",
    )

    consuming = asyncio.create_task(consumer.run())
    try:
        message = await asyncio.wait_for(runtime["result_queue"].get(), timeout=1)
    finally:
        consuming.cancel()
    await publisher.publish(message)
    await redis.aclose()

    assert checkpoints == [
        {
            "checkpoint": "exec_expired",
            "session_id": 7,
            "execution_id": EXECUTION_ID,
            "waited_s": 121,
        },
        {
            "checkpoint": "exec_published",
            "session_id": 7,
            "execution_id": EXECUTION_ID,
            "outcome": "overloaded",
        },
    ]
