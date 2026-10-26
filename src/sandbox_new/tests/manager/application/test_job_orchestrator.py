"""Behavior of the job orchestrator -- the venv readiness gate.

A COMPLETED venv dispatches now, a venv still building holds, a FAILED venv reports a
failed result. ``flush_pending`` re-runs that decision for whatever is waiting.
"""

import asyncio

import pytest

from manager.application.holding import JobHoldingRegistry
from manager.application.orchestrators import JobOrchestrator
from manager.domain.enums import VenvStatus
from manager.domain.errors import VenvNotFoundError
from manager.domain.models import StorageCredentials
from manager.infrastructure.transport.queue_job_dispatcher import QueueJobDispatcher
from tests.builders import make_venv

SUBMISSION = {
    "execution_id": "exec-1",
    "session_id": 7,
    "code": "def main():\n    return 1",
    "entrypoint": "main",
    "global_kwargs": {"LIMIT": 3},
    "func_kwargs": {"value": "x"},
    "secrets": {"TOKEN": "s3cret"},
    "use_storage": False,
    "storage_allowed_paths": [],
    "storage_org_prefix": None,
    "storage_credentials": None,
    "timeout": None,
    "reply_to_crew_channel": False,
}


@pytest.fixture
def holding() -> JobHoldingRegistry:
    return JobHoldingRegistry()


@pytest.fixture
def orchestrator(uow, dispatcher, holding, failure_sink) -> JobOrchestrator:
    return JobOrchestrator(uow, dispatcher, holding, failure_sink)


async def test_submit_against_a_completed_venv_dispatches_it(
    uow, orchestrator, dispatcher, holding
):
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.COMPLETED, hash="1abc"))[0]

    job = await orchestrator.submit(venv_id=venv.id, **SUBMISSION)

    assert [dispatched.execution_id for dispatched in dispatcher.dispatched] == ["exec-1"]
    assert dispatcher.dispatched[0].venv_hash == "1abc"
    assert dispatcher.dispatched[0].secrets == {"TOKEN": "s3cret"}
    assert holding.pending_venv_ids() == []
    assert job.venv_id == venv.id


@pytest.mark.parametrize("status", [VenvStatus.DECLARED, VenvStatus.PROCESSING])
async def test_submit_against_a_building_venv_holds_it(
    uow, orchestrator, dispatcher, holding, failure_sink, status
):
    venv = uow.venv_repo.seed(make_venv(status=status))[0]

    await orchestrator.submit(venv_id=venv.id, **SUBMISSION)

    assert dispatcher.dispatched == []
    assert failure_sink.failures == []
    assert [job.execution_id for job in holding.release(venv.id)] == ["exec-1"]


async def test_submit_against_a_failed_venv_reports_a_failure(
    uow, orchestrator, dispatcher, holding, failure_sink
):
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.FAILED, error="uv blew up"))[0]

    await orchestrator.submit(venv_id=venv.id, **SUBMISSION)

    assert dispatcher.dispatched == []
    assert holding.pending_venv_ids() == []
    [failure] = failure_sink.failures
    assert failure.execution_id == "exec-1"
    assert "failed to build" in failure.message
    assert (failure.session_id, failure.not_run_reason) == (7, "venv_failed")


async def test_submit_without_a_venv_id_uses_the_default_venv(uow, orchestrator, dispatcher):
    uow.venv_repo.seed(make_venv(name="data", status=VenvStatus.COMPLETED, hash="9zzz"))
    uow.venv_repo.seed(make_venv(name="default", status=VenvStatus.COMPLETED, hash="1abc"))

    await orchestrator.submit(venv_id=None, **SUBMISSION)

    assert dispatcher.dispatched[0].venv_hash == "1abc"


async def test_submit_against_a_missing_venv_raises(orchestrator):
    with pytest.raises(VenvNotFoundError):
        await orchestrator.submit(venv_id=404, **SUBMISSION)


async def test_submit_without_a_venv_id_and_no_default_raises(orchestrator):
    with pytest.raises(VenvNotFoundError):
        await orchestrator.submit(venv_id=None, **SUBMISSION)


async def test_a_dispatch_failure_does_not_reach_the_caller(uow, orchestrator, dispatcher):
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.COMPLETED, hash="1abc"))[0]
    dispatcher.fail_next = RuntimeError("queue is gone")

    job = await orchestrator.submit(venv_id=venv.id, **SUBMISSION)

    assert job.execution_id == "exec-1"
    assert dispatcher.dispatched == []


async def test_a_dispatch_failure_is_reported_as_a_failed_run(
    uow, orchestrator, dispatcher, failure_sink
):
    """The caller was answered 202, so a result is the only way it learns the job
    never ran -- silence would leave it waiting and its credentials unrevoked."""
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.COMPLETED, hash="1abc"))[0]
    dispatcher.fail_next = RuntimeError("queue is gone")

    await orchestrator.submit(venv_id=venv.id, **SUBMISSION)

    [failure] = failure_sink.failures
    assert failure.execution_id == "exec-1"
    assert failure.message == "The job could not be handed to the worker and was not run."
    assert (failure.session_id, failure.not_run_reason) == (7, "dispatch_failed")


async def test_flush_pending_dispatches_jobs_whose_venv_finished_building(
    uow, orchestrator, dispatcher, holding
):
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.PROCESSING))[0]
    await orchestrator.submit(venv_id=venv.id, **SUBMISSION)
    built = (await uow.venv_repo.retrieve(venv.id)).model_copy(
        update={"status": VenvStatus.COMPLETED, "hash": "1built"}
    )
    await uow.venv_repo.update(built)

    await orchestrator.flush_pending()

    assert [job.execution_id for job in dispatcher.dispatched] == ["exec-1"]
    assert dispatcher.dispatched[0].venv_hash == "1built"
    assert holding.pending_venv_ids() == []


async def test_a_held_job_keeps_its_storage_credentials_until_it_is_dispatched(
    uow, orchestrator, dispatcher
):
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.PROCESSING))[0]
    await orchestrator.submit(
        venv_id=venv.id,
        **{
            **SUBMISSION,
            "use_storage": True,
            "storage_org_prefix": "org1",
            "storage_credentials": StorageCredentials(
                access_key="AK123", secret_key="SK456"
            ),
        },
    )
    built = (await uow.venv_repo.retrieve(venv.id)).model_copy(
        update={"status": VenvStatus.COMPLETED, "hash": "1built"}
    )
    await uow.venv_repo.update(built)

    await orchestrator.flush_pending()

    assert dispatcher.dispatched[0].storage_credentials.access_key == "AK123"


async def test_flush_pending_keeps_holding_a_venv_that_is_still_building(
    uow, orchestrator, dispatcher, holding
):
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.PROCESSING))[0]
    await orchestrator.submit(venv_id=venv.id, **SUBMISSION)

    await orchestrator.flush_pending()

    assert dispatcher.dispatched == []
    assert holding.pending_venv_ids() == [venv.id]


async def test_flush_pending_fails_jobs_whose_venv_failed_to_build(
    uow, orchestrator, dispatcher, holding, failure_sink
):
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.PROCESSING))[0]
    await orchestrator.submit(venv_id=venv.id, **SUBMISSION)
    failed = (await uow.venv_repo.retrieve(venv.id)).model_copy(
        update={"status": VenvStatus.FAILED, "error": "uv blew up"}
    )
    await uow.venv_repo.update(failed)

    await orchestrator.flush_pending()

    assert dispatcher.dispatched == []
    assert holding.pending_venv_ids() == []
    assert failure_sink.failures[0].execution_id == "exec-1"
    assert failure_sink.failures[0].not_run_reason == "venv_failed"


async def test_a_held_job_logs_exec_held_then_exec_queued_when_released(
    uow, holding, failure_sink, checkpoints
):
    """The real dispatcher, because exec_queued is logged where the queue is."""
    orchestrator = JobOrchestrator(uow, QueueJobDispatcher(asyncio.Queue()), holding, failure_sink)
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.PROCESSING))[0]
    await orchestrator.submit(venv_id=venv.id, **SUBMISSION)
    built = (await uow.venv_repo.retrieve(venv.id)).model_copy(
        update={"status": VenvStatus.COMPLETED, "hash": "1built"}
    )
    await uow.venv_repo.update(built)

    await orchestrator.flush_pending()

    assert checkpoints == [
        {
            "checkpoint": "exec_held",
            "session_id": 7,
            "execution_id": "exec-1",
            "venv_id": venv.id,
        },
        {"checkpoint": "exec_queued", "session_id": 7, "execution_id": "exec-1", "queued": 1},
    ]


async def test_flush_pending_fails_jobs_whose_venv_disappeared(
    uow, orchestrator, dispatcher, holding, failure_sink
):
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.PROCESSING))[0]
    await orchestrator.submit(venv_id=venv.id, **SUBMISSION)
    uow.venv_repo.rows.pop(venv.id)

    await orchestrator.flush_pending()

    assert dispatcher.dispatched == []
    assert holding.pending_venv_ids() == []
    assert failure_sink.failures[0].execution_id == "exec-1"
