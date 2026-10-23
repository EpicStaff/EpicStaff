"""Behavior of the result consumer pump.

It owns no business logic: it drains the queue into the publisher and keeps going when a
publish fails, because one bad result must not stall every result behind it.
"""

import asyncio

import pytest

from common.contracts import ExecutionResultMessage
from manager.infrastructure.transport.result_consumer import ResultConsumer
from tests.fakes import FakeResultPublisher


async def drain(queue: asyncio.Queue, publisher: FakeResultPublisher, expected: int) -> None:
    """Run the consumer until it has published ``expected`` messages, then stop it."""
    task = asyncio.create_task(ResultConsumer(queue, publisher).run())
    try:
        for _ in range(100):
            if len(publisher.published) >= expected:
                return
            await asyncio.sleep(0.01)
        raise AssertionError(f"published {len(publisher.published)}, expected {expected}")
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_queued_results_reach_the_publisher():
    queue: asyncio.Queue[ExecutionResultMessage] = asyncio.Queue()
    publisher = FakeResultPublisher()
    queue.put_nowait(ExecutionResultMessage(execution_id="exec-1"))

    await drain(queue, publisher, expected=1)

    assert [message.execution_id for message in publisher.published] == ["exec-1"]


async def test_a_failing_publish_does_not_stall_the_following_results():
    queue: asyncio.Queue[ExecutionResultMessage] = asyncio.Queue()
    publisher = FakeResultPublisher()
    publisher.fail_for = {"exec-1"}
    queue.put_nowait(ExecutionResultMessage(execution_id="exec-1"))
    queue.put_nowait(ExecutionResultMessage(execution_id="exec-2"))

    await drain(queue, publisher, expected=1)

    assert [message.execution_id for message in publisher.published] == ["exec-2"]
