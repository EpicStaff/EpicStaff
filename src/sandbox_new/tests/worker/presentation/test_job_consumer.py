"""Behavior of the job consumer.

Concurrency is the worker's own: a free slot is taken before the next job is pulled, so
at most ``concurrency`` executions run at once. One job failing must free its slot and
leave the loop running.
"""

import asyncio

import pytest

from worker.presentation.job_consumer import JobConsumer
from tests.builders import make_worker_job
from tests.fakes import FakeJobSource


class RecordingOrchestrator:
    """Stands in for ``ExecutionOrchestrator``; the consumer only calls ``execute``."""

    def __init__(self, *, gate: asyncio.Event | None = None, fail_for: set[str] | None = None):
        self.started: list[str] = []
        self.finished: list[str] = []
        self._gate = gate
        self._fail_for = fail_for or set()

    async def execute(self, job) -> None:
        self.started.append(job.execution_id)
        if self._gate is not None:
            await self._gate.wait()
        if job.execution_id in self._fail_for:
            raise RuntimeError(f"execution {job.execution_id} blew up")
        self.finished.append(job.execution_id)


async def run_consumer(consumer: JobConsumer, check, *, timeout: float = 1.0):
    """Run the consumer until ``check()`` is true, then cancel it."""
    task = asyncio.create_task(consumer.run())
    try:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if check():
                return
            await asyncio.sleep(0.005)
        raise AssertionError("the consumer never reached the expected state")
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_queued_jobs_are_executed():
    orchestrator = RecordingOrchestrator()
    source = FakeJobSource(
        make_worker_job(execution_id="exec-1"), make_worker_job(execution_id="exec-2")
    )
    consumer = JobConsumer(source, orchestrator, concurrency=2)

    await run_consumer(consumer, lambda: len(orchestrator.finished) == 2)

    assert sorted(orchestrator.finished) == ["exec-1", "exec-2"]


async def test_a_single_slot_runs_one_job_at_a_time():
    gate = asyncio.Event()
    orchestrator = RecordingOrchestrator(gate=gate)
    source = FakeJobSource(
        make_worker_job(execution_id="exec-1"), make_worker_job(execution_id="exec-2")
    )
    consumer = JobConsumer(source, orchestrator, concurrency=1)

    await run_consumer(consumer, lambda: len(orchestrator.started) == 1)
    await asyncio.sleep(0.05)
    assert orchestrator.started == ["exec-1"]

    gate.set()
    await run_consumer(consumer, lambda: len(orchestrator.finished) == 2)
    assert sorted(orchestrator.finished) == ["exec-1", "exec-2"]


async def test_two_slots_run_two_jobs_at_once():
    gate = asyncio.Event()
    orchestrator = RecordingOrchestrator(gate=gate)
    source = FakeJobSource(
        make_worker_job(execution_id="exec-1"), make_worker_job(execution_id="exec-2")
    )
    consumer = JobConsumer(source, orchestrator, concurrency=2)

    await run_consumer(consumer, lambda: len(orchestrator.started) == 2)

    assert sorted(orchestrator.started) == ["exec-1", "exec-2"]
    gate.set()


async def test_a_failing_job_frees_its_slot_and_leaves_the_loop_running():
    orchestrator = RecordingOrchestrator(fail_for={"exec-1"})
    source = FakeJobSource(
        make_worker_job(execution_id="exec-1"), make_worker_job(execution_id="exec-2")
    )
    consumer = JobConsumer(source, orchestrator, concurrency=1)

    await run_consumer(consumer, lambda: orchestrator.finished == ["exec-2"])

    assert orchestrator.started == ["exec-1", "exec-2"]
    assert orchestrator.finished == ["exec-2"]


async def test_exec_start_counts_the_executions_running_including_its_own(checkpoints):
    gate = asyncio.Event()
    orchestrator = RecordingOrchestrator(gate=gate)
    source = FakeJobSource(
        make_worker_job(execution_id="exec-1", session_id=3),
        make_worker_job(execution_id="exec-2", session_id=4),
    )
    consumer = JobConsumer(source, orchestrator, concurrency=2)

    await run_consumer(consumer, lambda: len(orchestrator.started) == 2)
    gate.set()

    assert checkpoints == [
        {"checkpoint": "exec_start", "session_id": 3, "execution_id": "exec-1", "running": 1},
        {"checkpoint": "exec_start", "session_id": 4, "execution_id": "exec-2", "running": 2},
    ]


async def test_a_finished_execution_no_longer_counts_as_running(checkpoints):
    orchestrator = RecordingOrchestrator()
    source = FakeJobSource(
        make_worker_job(execution_id="exec-1"), make_worker_job(execution_id="exec-2")
    )
    consumer = JobConsumer(source, orchestrator, concurrency=1)

    await run_consumer(consumer, lambda: len(orchestrator.finished) == 2)

    assert orchestrator.finished == ["exec-1", "exec-2"]
    assert [(item["execution_id"], item["running"]) for item in checkpoints] == [
        ("exec-1", 1),
        ("exec-2", 1),
    ]
