"""The manager-to-worker seam, end to end in one process.

Real queues, real pipeline, real child interpreter. Fakes only at the true edges: the
venv repository and the Landlock probe. This is the only test that would catch the
manager encoding a field the worker does not decode.
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

from common.contracts import ExecutionJobMessage, ExecutionResultMessage
from manager.application.holding import JobHoldingRegistry
from manager.application.orchestrators import JobOrchestrator
from manager.domain.enums import VenvStatus
from manager.domain.models import StorageCredentials
from manager.infrastructure.transport.queue_job_dispatcher import QueueJobDispatcher
from manager.infrastructure.transport.queue_job_failure_sink import QueueJobFailureSink
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
from worker.infrastructure.transport.queue_result_sink import QueueResultSink
from tests.builders import make_venv
from tests.fakes import FakeIsolationProbe

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
        .register(LaunchStep(default_timeout=30))
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
    manager = JobOrchestrator(
        uow,
        QueueJobDispatcher(runtime["job_queue"]),
        JobHoldingRegistry(),
        QueueJobFailureSink(runtime["result_queue"]),
    )

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
    )

    job = await QueueJobSource(runtime["job_queue"]).get()
    assert job.venv_hash == VENV_HASH
    assert job.func_kwargs == {"value": "x"}
    assert job.secrets == {"TOKEN": "s3cret"}

    await build_worker(runtime).execute(job)

    message: ExecutionResultMessage = runtime["result_queue"].get_nowait()
    assert message.execution_id == EXECUTION_ID
    assert message.returncode == 0
    assert json.loads(message.result) == {"echo": "x", "limit": 3}
    assert "token=[REDACTED]" in message.stdout
    assert "s3cret" not in message.stdout


async def test_a_job_whose_venv_failed_to_build_reaches_the_same_result_queue(uow, runtime):
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.FAILED, error="uv blew up"))[0]
    manager = JobOrchestrator(
        uow,
        QueueJobDispatcher(runtime["job_queue"]),
        JobHoldingRegistry(),
        QueueJobFailureSink(runtime["result_queue"]),
    )

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
    )

    assert runtime["job_queue"].empty()
    message: ExecutionResultMessage = runtime["result_queue"].get_nowait()
    assert message.execution_id == EXECUTION_ID
    assert message.returncode == 1
    assert "failed to build" in message.stderr


async def test_storage_credentials_reach_the_worker_unchanged(uow, runtime):
    """The credentials the caller issued must survive the manager-to-worker encoding."""
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.COMPLETED, hash=VENV_HASH))[0]
    manager = JobOrchestrator(
        uow,
        QueueJobDispatcher(runtime["job_queue"]),
        JobHoldingRegistry(),
        QueueJobFailureSink(runtime["result_queue"]),
    )

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
    )

    job = await QueueJobSource(runtime["job_queue"]).get()
    assert job.storage_credentials.access_key == "AK123"
    assert job.storage_credentials.secret_key == "SK456"
