"""Behavior of the job orchestrator -- the venv readiness gate and intake bookkeeping.

A COMPLETED venv dispatches now, a venv still building holds, a FAILED venv reports a
failed result. ``flush_pending`` re-runs that decision for whatever is waiting, and
first fails every job held past its hold deadline. Every submission is recorded in the
execution registry; one refused before it was enqueued is forgotten again, and the
queue deadline starts only when a job reaches the queue. Held jobs have their own cap
and never count toward the in-flight one; a released job is dispatched even when the
in-flight cap is full.
"""

import asyncio

import pytest

from manager.application.holding import JobHoldingRegistry
from manager.application.intake import IntakeGate
from manager.application.orchestrators import JobOrchestrator
from manager.application.registry import ExecutionRegistry
from manager.domain.enums import ExecutionStatus, VenvStatus
from manager.domain.errors import SandboxOverloadedError, VenvNotFoundError
from manager.domain.models import StorageCredentials
from manager.infrastructure.transport.queue_job_dispatcher import QueueJobDispatcher
from manager.infrastructure.transport.queue_job_failure_sink import QueueJobFailureSink
from manager.presentation.result_consumer import ResultConsumer
from tests.builders import make_venv
from tests.fakes import FakeResultPublisher, FakeUnitOfWork, FakeVenvRepository

QUEUE_TIMEOUT = 120.0
HOLD_TIMEOUT = 1800.0
MAX_ACCEPTED = 2
MAX_HELD = 2
HOLD_TIMED_OUT_MESSAGE = (
    "The execution environment did not finish building in time; the job was not run."
)

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
def registry(clock) -> ExecutionRegistry:
    return ExecutionRegistry(clock=clock)


class PausingVenvRepository(FakeVenvRepository):
    """Holds every venv lookup until the test releases it."""

    def __init__(self) -> None:
        super().__init__()
        self.lookup_started = asyncio.Event()
        self.release_lookup = asyncio.Event()

    async def retrieve(self, id: int):
        self.lookup_started.set()
        await self.release_lookup.wait()
        return await super().retrieve(id)


@pytest.fixture
def orchestrator(uow, dispatcher, holding, failure_sink, registry, clock) -> JobOrchestrator:
    return build_orchestrator(uow, dispatcher, holding, failure_sink, registry, clock)


def build_orchestrator(uow, dispatcher, holding, failure_sink, registry, clock) -> JobOrchestrator:
    intake_gate = IntakeGate(
        registry,
        lambda: True,
        max_accepted=MAX_ACCEPTED,
        max_held=MAX_HELD,
        queue_timeout=QUEUE_TIMEOUT,
    )
    return JobOrchestrator(
        uow,
        dispatcher,
        holding,
        failure_sink,
        registry,
        intake_gate,
        queue_timeout=QUEUE_TIMEOUT,
        hold_timeout=HOLD_TIMEOUT,
        clock=clock,
    )


def fill_to_the_cap(registry: ExecutionRegistry) -> None:
    for index in range(MAX_ACCEPTED):
        registry.reserve(f"other-{index}")
        registry.mark_queued(f"other-{index}")


def fill_the_held_cap(registry: ExecutionRegistry) -> None:
    for index in range(MAX_HELD):
        registry.reserve(f"held-{index}")
        registry.mark_held(f"held-{index}")


async def mark_built(uow, venv_id: int) -> None:
    built = (await uow.venv_repo.retrieve(venv_id)).model_copy(
        update={"status": VenvStatus.COMPLETED, "hash": "1built"}
    )
    await uow.venv_repo.update(built)


async def publish_results(result_queue: asyncio.Queue, registry: ExecutionRegistry) -> list:
    """Run the real result consumer until it has drained the queue; return what it published."""
    publisher = FakeResultPublisher()
    expected = result_queue.qsize()
    task = asyncio.create_task(ResultConsumer(result_queue, publisher, registry).run())
    try:
        for _ in range(100):
            if len(publisher.published) == expected:
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("the result consumer never drained the queue")
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    return publisher.published


async def test_submit_against_a_completed_venv_dispatches_it(
    uow, orchestrator, dispatcher, holding
):
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.COMPLETED, hash="1abc"))[0]

    status = await orchestrator.submit(venv_id=venv.id, **SUBMISSION)

    assert [dispatched.execution_id for dispatched in dispatcher.dispatched] == ["exec-1"]
    assert dispatcher.dispatched[0].venv_hash == "1abc"
    assert dispatcher.dispatched[0].secrets == {"TOKEN": "s3cret"}
    assert dispatcher.dispatched[0].venv_id == venv.id
    assert holding.pending_venv_ids() == []
    assert status is ExecutionStatus.QUEUED


@pytest.mark.parametrize("status", [VenvStatus.DECLARED, VenvStatus.PROCESSING])
async def test_submit_against_a_building_venv_holds_it(
    uow, orchestrator, dispatcher, holding, failure_sink, status
):
    venv = uow.venv_repo.seed(make_venv(status=status))[0]

    submitted_status = await orchestrator.submit(venv_id=venv.id, **SUBMISSION)

    assert submitted_status is ExecutionStatus.HELD
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

    status = await orchestrator.submit(venv_id=venv.id, **SUBMISSION)

    assert status is ExecutionStatus.QUEUED
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
    uow, holding, failure_sink, registry, clock, checkpoints
):
    """The real dispatcher, because exec_queued is logged where the queue is."""
    orchestrator = build_orchestrator(
        uow, QueueJobDispatcher(asyncio.Queue()), holding, failure_sink, registry, clock
    )
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


async def test_a_resubmitted_id_is_not_dispatched_again(uow, orchestrator, dispatcher):
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.COMPLETED, hash="1abc"))[0]
    await orchestrator.submit(venv_id=venv.id, **SUBMISSION)

    status = await orchestrator.submit(venv_id=venv.id, **SUBMISSION)

    assert status is ExecutionStatus.QUEUED
    assert [job.execution_id for job in dispatcher.dispatched] == ["exec-1"]


async def test_a_resubmitted_held_id_answers_held_and_is_held_once(uow, orchestrator, holding):
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.PROCESSING))[0]
    await orchestrator.submit(venv_id=venv.id, **SUBMISSION)

    status = await orchestrator.submit(venv_id=venv.id, **SUBMISSION)

    assert status is ExecutionStatus.HELD
    assert [job.execution_id for job in holding.release(venv.id)] == ["exec-1"]


async def test_a_missing_venv_leaves_the_id_unknown(orchestrator, registry):
    with pytest.raises(VenvNotFoundError):
        await orchestrator.submit(venv_id=404, **SUBMISSION)

    assert registry.status("exec-1") is None
    assert registry.active_count == 0


async def test_an_overloaded_sandbox_refuses_and_leaves_the_id_unknown(
    uow, orchestrator, dispatcher, registry
):
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.COMPLETED, hash="1abc"))[0]
    fill_to_the_cap(registry)

    with pytest.raises(SandboxOverloadedError):
        await orchestrator.submit(venv_id=venv.id, **SUBMISSION)

    assert dispatcher.dispatched == []
    assert registry.status("exec-1") is None


async def test_a_held_submission_is_accepted_while_the_in_flight_cap_is_full(
    uow, orchestrator, holding, registry
):
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.PROCESSING))[0]
    fill_to_the_cap(registry)

    status = await orchestrator.submit(venv_id=venv.id, **SUBMISSION)

    assert status is ExecutionStatus.HELD
    assert [job.execution_id for job in holding.release(venv.id)] == ["exec-1"]


async def test_a_held_submission_is_refused_at_the_held_cap(
    uow, orchestrator, holding, registry
):
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.PROCESSING))[0]
    fill_the_held_cap(registry)

    with pytest.raises(SandboxOverloadedError) as raised:
        await orchestrator.submit(venv_id=venv.id, **SUBMISSION)

    assert raised.value.retry_after == 30
    assert holding.pending_venv_ids() == []
    assert registry.status("exec-1") is None


async def test_a_submission_to_a_built_venv_is_accepted_while_the_held_cap_is_full(
    uow, orchestrator, dispatcher, registry
):
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.COMPLETED, hash="1abc"))[0]
    fill_the_held_cap(registry)

    status = await orchestrator.submit(venv_id=venv.id, **SUBMISSION)

    assert status is ExecutionStatus.QUEUED
    assert [job.execution_id for job in dispatcher.dispatched] == ["exec-1"]


async def test_a_released_job_is_dispatched_even_when_the_in_flight_cap_is_full(
    uow, orchestrator, dispatcher, registry
):
    """It was admitted and has waited for its venv; refusing it now would fail a job
    the caller was told was accepted. The worker's run gate still bounds what runs."""
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.PROCESSING))[0]
    await orchestrator.submit(venv_id=venv.id, **SUBMISSION)
    fill_to_the_cap(registry)
    await mark_built(uow, venv.id)

    await orchestrator.flush_pending()

    assert [job.execution_id for job in dispatcher.dispatched] == ["exec-1"]
    assert registry.status("exec-1") is ExecutionStatus.QUEUED
    assert registry.active_count == MAX_ACCEPTED + 1


async def test_a_job_held_until_its_hold_deadline_is_failed_and_finished(
    uow, dispatcher, holding, registry, clock
):
    result_queue: asyncio.Queue = asyncio.Queue()
    orchestrator = build_orchestrator(
        uow, dispatcher, holding, QueueJobFailureSink(result_queue), registry, clock
    )
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.PROCESSING))[0]
    await orchestrator.submit(venv_id=venv.id, **SUBMISSION)
    clock.advance(HOLD_TIMEOUT)

    await orchestrator.flush_pending()
    [published] = await publish_results(result_queue, registry)

    assert published.execution_id == "exec-1"
    assert published.stderr == HOLD_TIMED_OUT_MESSAGE
    assert published.not_run_reason == "hold_timeout"
    assert published.ran is False
    assert dispatcher.dispatched == []
    assert holding.pending_venv_ids() == []
    assert registry.status("exec-1") is ExecutionStatus.DONE
    assert registry.held_count == 0
    clock.advance(60.1)
    assert registry.status("exec-1") is None


async def test_only_the_jobs_past_their_hold_deadline_are_failed(
    uow, orchestrator, holding, failure_sink, registry, clock
):
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.PROCESSING))[0]
    await orchestrator.submit(venv_id=venv.id, **SUBMISSION)
    clock.advance(1000)
    await orchestrator.submit(venv_id=venv.id, **{**SUBMISSION, "execution_id": "exec-2"})
    # One second before exec-1 reaches its hold deadline.
    clock.advance(HOLD_TIMEOUT - 1001)

    await orchestrator.flush_pending()
    assert failure_sink.failures == []
    clock.advance(1)
    await orchestrator.flush_pending()

    assert failure_sink.failures == [("exec-1", HOLD_TIMED_OUT_MESSAGE, 7, "hold_timeout", False)]
    assert registry.status("exec-2") is ExecutionStatus.HELD
    assert [job.execution_id for job in holding.release(venv.id)] == ["exec-2"]


async def test_a_job_past_its_hold_deadline_is_failed_even_if_its_venv_just_finished(
    uow, orchestrator, dispatcher, failure_sink, clock
):
    """Its producer may already be about to give up on it, so it is not run late."""
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.PROCESSING))[0]
    await orchestrator.submit(venv_id=venv.id, **SUBMISSION)
    await mark_built(uow, venv.id)
    clock.advance(HOLD_TIMEOUT)

    await orchestrator.flush_pending()

    assert dispatcher.dispatched == []
    assert [failure.message for failure in failure_sink.failures] == [HOLD_TIMED_OUT_MESSAGE]


async def test_a_failed_venv_is_reported_even_at_the_cap(
    uow, orchestrator, failure_sink, registry
):
    """Not gated: the job never runs, so it costs no capacity, and its producer gets
    the real reason instead of being told to retry."""
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.FAILED, error="uv blew up"))[0]
    fill_to_the_cap(registry)

    await orchestrator.submit(venv_id=venv.id, **SUBMISSION)

    assert [failure.execution_id for failure in failure_sink.failures] == ["exec-1"]


async def test_the_queue_deadline_starts_at_dispatch(uow, orchestrator, dispatcher, clock):
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.COMPLETED, hash="1abc"))[0]

    await orchestrator.submit(venv_id=venv.id, **SUBMISSION)

    assert dispatcher.dispatched[0].queue_deadline == clock.now + QUEUE_TIMEOUT


async def test_a_held_job_has_no_queue_deadline(uow, orchestrator, holding):
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.PROCESSING))[0]

    await orchestrator.submit(venv_id=venv.id, **SUBMISSION)

    [held] = holding.release(venv.id)
    assert held.queue_deadline is None


async def test_a_released_job_gets_its_queue_deadline_at_release(
    uow, orchestrator, dispatcher, registry, clock
):
    venv = uow.venv_repo.seed(make_venv(status=VenvStatus.PROCESSING))[0]
    await orchestrator.submit(venv_id=venv.id, **SUBMISSION)
    built = (await uow.venv_repo.retrieve(venv.id)).model_copy(
        update={"status": VenvStatus.COMPLETED, "hash": "1built"}
    )
    await uow.venv_repo.update(built)
    clock.advance(50)

    await orchestrator.flush_pending()

    assert dispatcher.dispatched[0].queue_deadline == clock.now + QUEUE_TIMEOUT
    assert registry.status("exec-1") is ExecutionStatus.QUEUED


async def test_a_re_post_while_the_first_is_being_admitted_is_told_to_retry(
    dispatcher, holding, failure_sink, registry, clock
):
    """Until the first request has its outcome, a duplicate must not be told QUEUED:
    the first may yet be refused, and then nothing would ever finish the id."""
    venv_repository = PausingVenvRepository()
    venv = venv_repository.seed(make_venv(status=VenvStatus.COMPLETED, hash="1abc"))[0]
    orchestrator = build_orchestrator(
        FakeUnitOfWork(venv_repository), dispatcher, holding, failure_sink, registry, clock
    )
    first = asyncio.ensure_future(orchestrator.submit(venv_id=venv.id, **SUBMISSION))
    await venv_repository.lookup_started.wait()

    with pytest.raises(SandboxOverloadedError) as duplicate:
        await orchestrator.submit(venv_id=venv.id, **SUBMISSION)
    # The sandbox fills up while the first request's venv is looked up.
    fill_to_the_cap(registry)
    venv_repository.release_lookup.set()
    with pytest.raises(SandboxOverloadedError):
        await first

    assert duplicate.value.retry_after == 1
    assert registry.status("exec-1") is None
    assert dispatcher.dispatched == []


async def test_a_retry_after_the_first_was_refused_gets_its_own_answer(
    dispatcher, holding, failure_sink, registry, clock
):
    venv_repository = PausingVenvRepository()
    venv = venv_repository.seed(make_venv(status=VenvStatus.COMPLETED, hash="1abc"))[0]
    orchestrator = build_orchestrator(
        FakeUnitOfWork(venv_repository), dispatcher, holding, failure_sink, registry, clock
    )
    first = asyncio.ensure_future(orchestrator.submit(venv_id=venv.id, **SUBMISSION))
    await venv_repository.lookup_started.wait()
    fill_to_the_cap(registry)
    venv_repository.release_lookup.set()
    with pytest.raises(SandboxOverloadedError):
        await first
    for index in range(MAX_ACCEPTED):
        registry.forget(f"other-{index}")

    status = await orchestrator.submit(venv_id=venv.id, **SUBMISSION)

    assert status is ExecutionStatus.QUEUED
    assert [job.execution_id for job in dispatcher.dispatched] == ["exec-1"]
