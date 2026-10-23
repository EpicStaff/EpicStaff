"""Behavior of the result consumer pump.

It drains the queue into the publisher and keeps going when a publish fails, because one
bad result must not stall every result behind it. Each result marks its execution DONE
in the registry -- only after the publish, and even when the publish failed.
"""

import asyncio
from collections.abc import Callable

import pytest

from common.contracts import ExecutionResultMessage
from manager.application.registry import ExecutionRegistry
from manager.domain.enums import ExecutionStatus
from manager.infrastructure.transport.result_consumer import ResultConsumer
from tests.fakes import FakeResultPublisher


class StatusRecordingPublisher(FakeResultPublisher):
    """Records what the registry says about each execution while it is being published."""

    def __init__(self, registry: ExecutionRegistry) -> None:
        super().__init__()
        self._registry = registry
        self.status_during_publish: dict[str, ExecutionStatus | None] = {}

    async def publish(self, result: ExecutionResultMessage) -> None:
        self.status_during_publish[result.execution_id] = self._registry.status(
            result.execution_id
        )
        await super().publish(result)


@pytest.fixture
def registry(clock) -> ExecutionRegistry:
    return ExecutionRegistry(clock=clock)


def queued(registry: ExecutionRegistry, *execution_ids: str) -> asyncio.Queue:
    queue: asyncio.Queue[ExecutionResultMessage] = asyncio.Queue()
    for execution_id in execution_ids:
        registry.reserve(execution_id)
        registry.mark_queued(execution_id)
    return queue


async def run_until(consumer: ResultConsumer, check: Callable[[], bool]) -> None:
    """Run the consumer until ``check()`` holds, then stop it."""
    task = asyncio.create_task(consumer.run())
    try:
        for _ in range(100):
            if check():
                return
            await asyncio.sleep(0.01)
        raise AssertionError("the consumer never reached the expected state")
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_queued_results_reach_the_publisher(registry):
    queue = queued(registry, "exec-1")
    publisher = FakeResultPublisher()
    queue.put_nowait(ExecutionResultMessage(execution_id="exec-1"))

    await run_until(ResultConsumer(queue, publisher, registry), lambda: publisher.published)

    assert [message.execution_id for message in publisher.published] == ["exec-1"]


async def test_a_failing_publish_does_not_stall_the_following_results(registry):
    queue = queued(registry, "exec-1", "exec-2")
    publisher = FakeResultPublisher()
    publisher.fail_for = {"exec-1"}
    queue.put_nowait(ExecutionResultMessage(execution_id="exec-1"))
    queue.put_nowait(ExecutionResultMessage(execution_id="exec-2"))

    await run_until(ResultConsumer(queue, publisher, registry), lambda: publisher.published)

    assert [message.execution_id for message in publisher.published] == ["exec-2"]


async def test_an_execution_is_done_only_after_its_result_is_published(registry):
    queue = queued(registry, "exec-1")
    publisher = StatusRecordingPublisher(registry)
    queue.put_nowait(ExecutionResultMessage(execution_id="exec-1"))

    await run_until(ResultConsumer(queue, publisher, registry), lambda: publisher.published)

    assert publisher.status_during_publish["exec-1"] is ExecutionStatus.QUEUED
    assert registry.status("exec-1") is ExecutionStatus.DONE


async def test_an_execution_whose_publish_failed_is_still_done(registry):
    queue = queued(registry, "exec-1")
    publisher = FakeResultPublisher()
    publisher.fail_for = {"exec-1"}
    queue.put_nowait(ExecutionResultMessage(execution_id="exec-1"))

    await run_until(
        ResultConsumer(queue, publisher, registry),
        lambda: registry.status("exec-1") is ExecutionStatus.DONE,
    )

    assert registry.active_count == 0


@pytest.mark.parametrize(("ran", "drain_rate"), [(True, 5.0), (False, None)])
async def test_whether_the_job_ran_reaches_the_drain_rate(registry, clock, ran, drain_rate):
    execution_ids = [f"exec-{index}" for index in range(10)]
    queue = queued(registry, *execution_ids)
    publisher = FakeResultPublisher()
    for execution_id in execution_ids:
        queue.put_nowait(ExecutionResultMessage(execution_id=execution_id, ran=ran))

    await run_until(ResultConsumer(queue, publisher, registry), lambda: registry.active_count == 0)
    clock.advance(2)

    assert registry.drain_rate() == drain_rate
