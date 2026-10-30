"""Behavior of the job consumer.

Every job it takes ends with a result. A job past its queue deadline is failed without
taking a slot; a job whose deadline passes while it waits for one is failed, not run; a
run that raises is answered with a failed result and frees its slot; a message that does
not decode is failed by its execution id. One bad job or turn never ends the loop.

Driven through the real orchestrator and the real admission gate; only the clock, the
load reading and the result transport are stand-ins.
"""

import asyncio
import contextlib

import pytest

from worker.application.orchestrator import ExecutionOrchestrator
from worker.application.pipeline import Pipeline
from worker.application.ports import UndecodableJobError
from worker.application.resource_gate import ResourceAdmissionGate
from worker.presentation.job_consumer import JobConsumer
from tests.builders import make_worker_job
from tests.fakes import FakeHostMetrics, FakeJobSource

QUEUE_TIMEOUT = 120.0


def build_gate(slots: int) -> ResourceAdmissionGate:
    return ResourceAdmissionGate(
        FakeHostMetrics(),
        min_concurrent=slots,
        max_concurrent=slots,
        cpu_threshold=85,
        memory_threshold=80,
    )


class Runtime:
    """A consumer over a one-step pipeline that records which jobs actually ran."""

    def __init__(self, source, result_sink, gate, clock, *, blocker: asyncio.Event | None = None):
        self.executed: list[str] = []
        self.result_sink = result_sink

        async def step(context):
            self.executed.append(context.job.execution_id)
            if blocker is not None:
                await blocker.wait()
            context.returncode = 0
            context.complete()

        orchestrator = ExecutionOrchestrator(
            Pipeline().register(step), result_sink=result_sink, mask_secrets=False
        )
        self.consumer = JobConsumer(
            source, orchestrator, gate, queue_timeout=QUEUE_TIMEOUT, clock=clock
        )

    def results(self) -> dict:
        return {result.execution_id: result for result, _ in self.result_sink.sent}

    @contextlib.asynccontextmanager
    async def running(self):
        task = asyncio.create_task(self.consumer.run())
        try:
            yield
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    async def run_until(self, check) -> None:
        """Run the consumer until ``check()`` is true, then cancel it."""
        async with self.running():
            await wait_until(check)


async def wait_until(check, *, timeout: float = 1.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if check():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("the consumer never reached the expected state")


def queued_job(clock, execution_id: str, *, waited: float = 0, **fields):
    """A job the manager queued ``waited`` seconds ago."""
    return make_worker_job(execution_id=execution_id, queued_at=clock.now - waited, **fields)


def exec_starts(checkpoints: list[dict]) -> list[dict]:
    """The exec_start checkpoints only: the real orchestrator also logs exec_end."""
    return [item for item in checkpoints if item["checkpoint"] == "exec_start"]


async def test_queued_jobs_run_and_their_results_are_sent(result_sink, clock):
    source = FakeJobSource(queued_job(clock, "exec-1"), queued_job(clock, "exec-2"))
    runtime = Runtime(source, result_sink, build_gate(2), clock)

    await runtime.run_until(lambda: len(result_sink.sent) == 2)

    results = runtime.results()
    assert sorted(results) == ["exec-1", "exec-2"]
    assert all(result.ran and result.returncode == 0 for result in results.values())


async def test_a_single_slot_runs_one_job_at_a_time(result_sink, clock):
    blocker = asyncio.Event()
    source = FakeJobSource(queued_job(clock, "exec-1"), queued_job(clock, "exec-2"))
    runtime = Runtime(source, result_sink, build_gate(1), clock, blocker=blocker)

    async with runtime.running():
        await wait_until(lambda: runtime.executed == ["exec-1"])
        await asyncio.sleep(0.05)
        assert runtime.executed == ["exec-1"]

        blocker.set()
        await wait_until(lambda: len(result_sink.sent) == 2)

    assert runtime.executed == ["exec-1", "exec-2"]


async def test_an_expired_job_is_failed_without_waiting_for_a_slot(result_sink, clock, checkpoints):
    gate = build_gate(1)
    await gate.acquire()
    source = FakeJobSource(
        queued_job(clock, "exec-1", waited=QUEUE_TIMEOUT + 1, reply_to_crew_channel=True)
    )
    runtime = Runtime(source, result_sink, gate, clock)

    await runtime.run_until(lambda: result_sink.sent)

    result = runtime.results()["exec-1"]
    assert result.stderr == (
        "Sandbox overloaded: the job waited 121 s in the queue and was not run."
    )
    assert result.returncode == 1
    assert result.ran is False
    assert result.reply_to_crew_channel is True
    assert runtime.executed == []
    assert exec_starts(checkpoints) == []


async def test_a_job_that_expires_while_waiting_for_a_slot_is_failed_not_run(
    result_sink, clock
):
    gate = build_gate(1)
    await gate.acquire()
    source = FakeJobSource(queued_job(clock, "exec-1", waited=QUEUE_TIMEOUT - 10))
    runtime = Runtime(source, result_sink, gate, clock)

    async def expire_then_free_the_slot():
        await asyncio.sleep(0.02)
        clock.advance(11)
        gate.release()

    freeing = asyncio.create_task(expire_then_free_the_slot())
    await runtime.run_until(lambda: result_sink.sent)
    await freeing

    result = runtime.results()["exec-1"]
    assert result.stderr == (
        "Sandbox overloaded: the job waited 121 s in the queue and was not run."
    )
    assert runtime.executed == []
    assert gate.has_free_slot() is True


async def test_the_wait_for_a_slot_ends_when_the_queue_timeout_runs_out(result_sink, clock):
    """Waiting past the head job's deadline would also delay failing every expired job
    queued behind it."""
    gate = build_gate(1)
    await gate.acquire()
    source = FakeJobSource(queued_job(clock, "exec-1", waited=QUEUE_TIMEOUT - 0.05))
    runtime = Runtime(source, result_sink, gate, clock)

    await runtime.run_until(lambda: result_sink.sent)

    result = runtime.results()["exec-1"]
    assert result.stderr.startswith("Sandbox overloaded:")
    assert result.ran is False
    assert runtime.executed == []


async def test_a_run_that_raises_is_failed_and_frees_its_slot(result_sink, clock):
    # The first send -- the real result of exec-1 -- fails, so its run raises.
    result_sink.failures_left = 1
    source = FakeJobSource(
        queued_job(clock, "exec-1", session_id=3), queued_job(clock, "exec-2")
    )
    runtime = Runtime(source, result_sink, build_gate(1), clock)

    await runtime.run_until(lambda: len(result_sink.sent) == 2)

    results = runtime.results()
    assert results["exec-1"].stderr == "Sandbox failed to run the job."
    assert results["exec-1"].returncode == 1
    assert results["exec-1"].ran is False
    # A plain failed run, not an overload: no reason, so it is published as "failed".
    assert (results["exec-1"].session_id, results["exec-1"].not_run_reason) == (3, None)
    assert results["exec-2"].ran is True


async def test_an_undecodable_job_is_failed_and_the_loop_goes_on(result_sink, clock):
    source = FakeJobSource(
        UndecodableJobError("exec-bad", reply_to_crew_channel=True, session_id=5),
        queued_job(clock, "exec-2"),
    )
    runtime = Runtime(source, result_sink, build_gate(1), clock)

    await runtime.run_until(lambda: len(result_sink.sent) == 2)

    results = runtime.results()
    assert results["exec-bad"].returncode == 1
    assert results["exec-bad"].ran is False
    assert results["exec-bad"].reply_to_crew_channel is True
    assert (results["exec-bad"].session_id, results["exec-bad"].not_run_reason) == (5, None)
    assert runtime.executed == ["exec-2"]


async def test_a_turn_that_fails_does_not_end_the_loop(result_sink, clock):
    # The failed result for the undecodable job cannot be sent either.
    result_sink.failures_left = 1
    source = FakeJobSource(
        UndecodableJobError("exec-bad", reply_to_crew_channel=False),
        queued_job(clock, "exec-2"),
    )
    runtime = Runtime(source, result_sink, build_gate(1), clock)

    await runtime.run_until(lambda: result_sink.sent)

    assert list(runtime.results()) == ["exec-2"]


async def test_exec_start_counts_the_executions_running_including_its_own(
    result_sink, clock, checkpoints
):
    blocker = asyncio.Event()
    source = FakeJobSource(
        queued_job(clock, "exec-1", session_id=3), queued_job(clock, "exec-2", session_id=4)
    )
    runtime = Runtime(source, result_sink, build_gate(2), clock, blocker=blocker)

    async with runtime.running():
        await wait_until(lambda: len(runtime.executed) == 2)
        blocker.set()
        await wait_until(lambda: len(result_sink.sent) == 2)

    assert exec_starts(checkpoints) == [
        {"checkpoint": "exec_start", "session_id": 3, "execution_id": "exec-1", "running": 1},
        {"checkpoint": "exec_start", "session_id": 4, "execution_id": "exec-2", "running": 2},
    ]


async def test_a_finished_execution_no_longer_counts_as_running(result_sink, clock, checkpoints):
    source = FakeJobSource(queued_job(clock, "exec-1"), queued_job(clock, "exec-2"))
    runtime = Runtime(source, result_sink, build_gate(1), clock)

    await runtime.run_until(lambda: len(result_sink.sent) == 2)

    assert runtime.executed == ["exec-1", "exec-2"]
    assert [(item["execution_id"], item["running"]) for item in exec_starts(checkpoints)] == [
        ("exec-1", 1),
        ("exec-2", 1),
    ]
