"""Behavior of the worker-loss sweep loop.

It is the backstop behind the boot-id fast path: a worker run silent for longer than the
heartbeat threshold has its assigned jobs failed with the fixed worker-lost result, and
with no live worker at all the dispatch queue is drained and failed too. A run heard
from recently is left alone, and a failing pass does not kill the loop. Job duration
never enters the decision -- an assigned job may legitimately run for hours.
"""

import asyncio

import pytest

from common.contracts import ExecutionJobMessage
from manager.application.registry import ExecutionRegistry
from manager.application.worker_contact import WorkerContact
from manager.application.worker_loss import WORKER_LOST_MESSAGE
from manager.presentation.worker_loss_sweeper import HEARTBEAT_SILENCE_SECONDS, WorkerLossSweeper

QUEUED_JOB = ExecutionJobMessage(
    execution_id="exec-queued",
    venv_hash="1abc",
    code="def main():\n    return 1",
    entrypoint="main",
    session_id=9,
    reply_to_crew_channel=True,
)


async def run_passes(sweeper: WorkerLossSweeper, *, until) -> None:
    task = asyncio.create_task(sweeper.run())
    try:
        for _ in range(200):
            if until():
                return
            await asyncio.sleep(0.005)
        raise AssertionError("the sweeper never did what was expected of it")
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.fixture
def contact(clock) -> WorkerContact:
    return WorkerContact(clock=clock)


def assign(registry: ExecutionRegistry, execution_id: str) -> None:
    registry.reserve(execution_id)
    registry.mark_queued(execution_id)
    registry.mark_assigned(execution_id, boot_id="boot-1", session_id=7, reply_to_crew_channel=True)


async def test_a_silent_workers_job_is_failed_with_the_worker_lost_result(
    registry, contact, clock, failure_sink
):
    assign(registry, "exec-1")
    contact.record_seen("boot-1")
    clock.advance(HEARTBEAT_SILENCE_SECONDS + 0.1)

    sweeper = WorkerLossSweeper(
        registry, contact, failure_sink, asyncio.Queue(), queue_timeout=120.0, interval=0.01
    )
    await run_passes(sweeper, until=lambda: failure_sink.failures)

    failure = failure_sink.failures[0]
    assert failure.execution_id == "exec-1"
    assert failure.message == WORKER_LOST_MESSAGE
    assert failure.session_id == 7
    assert failure.not_run_reason == "worker_lost"
    assert failure.reply_to_crew_channel is True


async def test_with_no_live_worker_the_backlog_is_drained_and_failed(
    registry, contact, clock, failure_sink
):
    job_queue: asyncio.Queue = asyncio.Queue()
    job_queue.put_nowait(QUEUED_JOB)
    clock.advance(HEARTBEAT_SILENCE_SECONDS + 0.1)

    sweeper = WorkerLossSweeper(
        registry, contact, failure_sink, job_queue, queue_timeout=120.0, interval=0.01
    )
    await run_passes(sweeper, until=lambda: failure_sink.failures)

    failure = failure_sink.failures[0]
    assert failure.execution_id == "exec-queued"
    assert failure.message == WORKER_LOST_MESSAGE
    assert failure.session_id == 9
    assert failure.not_run_reason == "worker_lost"
    assert failure.reply_to_crew_channel is True
    assert job_queue.qsize() == 0


class CountingRegistry:
    """Counts sweep passes over a real registry, so a test can wait out N of them."""

    def __init__(self, registry: ExecutionRegistry) -> None:
        self._registry = registry
        self.passes = 0

    def boots_with_assignments(self):
        self.passes += 1
        return self._registry.boots_with_assignments()

    def release_assignments_of_boots(self, boot_ids):
        return self._registry.release_assignments_of_boots(boot_ids)


async def test_a_worker_heard_from_recently_keeps_its_jobs_and_backlog(
    registry, contact, clock, failure_sink
):
    assign(registry, "exec-1")
    contact.record_seen("boot-1")
    job_queue: asyncio.Queue = asyncio.Queue()
    job_queue.put_nowait(QUEUED_JOB)
    clock.advance(HEARTBEAT_SILENCE_SECONDS - 0.1)

    counting = CountingRegistry(registry)
    sweeper = WorkerLossSweeper(
        counting, contact, failure_sink, job_queue, queue_timeout=120.0, interval=0.01
    )
    await run_passes(sweeper, until=lambda: counting.passes >= 2)

    assert failure_sink.failures == []
    assert job_queue.qsize() == 1


async def test_a_fresh_manager_gives_the_worker_time_to_say_hello(
    registry, contact, clock, failure_sink
):
    """No contact yet, but the threshold is counted from the contact record's creation."""
    job_queue: asyncio.Queue = asyncio.Queue()
    job_queue.put_nowait(QUEUED_JOB)
    clock.advance(HEARTBEAT_SILENCE_SECONDS - 0.1)

    counting = CountingRegistry(registry)
    sweeper = WorkerLossSweeper(
        counting, contact, failure_sink, job_queue, queue_timeout=120.0, interval=0.01
    )
    await run_passes(sweeper, until=lambda: counting.passes >= 2)

    assert job_queue.qsize() == 1


async def test_a_failing_pass_does_not_stop_the_loop(failure_sink):
    passes = 0

    class FlakyRegistry:
        def boots_with_assignments(self):
            nonlocal passes
            passes += 1
            if passes == 1:
                raise RuntimeError("registry is gone")
            return set()

        def release_assignments_of_boots(self, boot_ids):
            return []

    sweeper = WorkerLossSweeper(
        FlakyRegistry(), WorkerContact(), failure_sink, asyncio.Queue(), queue_timeout=120.0, interval=0.01
    )
    await run_passes(sweeper, until=lambda: passes >= 3)

    assert passes >= 3
async def test_a_queued_job_past_its_deadline_is_failed_as_overloaded(
    registry, contact, failure_sink
):
    """A saturated slot-first worker never looks at the queue, so the queue deadline is
    enforced by the sweeper; fresh jobs stay, in their order."""
    queued_at = 1_800_000_000.0
    overdue = QUEUED_JOB.model_copy(update={"queued_at": queued_at - 121})
    fresh = QUEUED_JOB.model_copy(update={"execution_id": "exec-fresh", "queued_at": queued_at})
    fresher = QUEUED_JOB.model_copy(update={"execution_id": "exec-fresher", "queued_at": queued_at})
    job_queue: asyncio.Queue = asyncio.Queue()
    job_queue.put_nowait(overdue)
    job_queue.put_nowait(fresh)
    job_queue.put_nowait(fresher)
    contact.record_seen("boot-1")  # the worker is alive: no drain, only expiry

    sweeper = WorkerLossSweeper(
        registry,
        contact,
        failure_sink,
        job_queue,
        queue_timeout=120.0,
        interval=0.01,
        wall_clock=lambda: queued_at,
    )
    await run_passes(sweeper, until=lambda: failure_sink.failures)

    failure = failure_sink.failures[0]
    assert failure.execution_id == "exec-queued"
    assert failure.message == "Sandbox overloaded: the job waited 121 s in the queue and was not run."
    assert failure.not_run_reason == "overloaded"
    assert failure.session_id == 9
    assert failure.reply_to_crew_channel is True
    assert job_queue.get_nowait().execution_id == "exec-fresh"
    assert job_queue.get_nowait().execution_id == "exec-fresher"
