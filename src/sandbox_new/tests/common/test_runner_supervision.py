"""A background runner that dies takes the process down, so the container restarts.

Without it a dead job consumer or result consumer would leave the sandbox accepting jobs
that nothing runs or answers. Cancellation is how shutdown stops the runners, so it must
not trigger the stop.
"""

import asyncio

from common.bootstrap.lifespan import supervise


class StopRecorder:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1


async def settle(task: asyncio.Task) -> None:
    await asyncio.gather(task, return_exceptions=True)
    # Done callbacks are scheduled on the loop, not run inside the task.
    await asyncio.sleep(0)


async def test_a_runner_that_raises_stops_the_process():
    stop = StopRecorder()

    async def runner():
        raise RuntimeError("the queue broke")

    task = asyncio.create_task(runner(), name="job consumer")
    supervise(task, stop=stop)
    await settle(task)

    assert stop.calls == 1


async def test_a_runner_that_returns_stops_the_process():
    stop = StopRecorder()

    async def runner():
        return None

    task = asyncio.create_task(runner(), name="job consumer")
    supervise(task, stop=stop)
    await settle(task)

    assert stop.calls == 1


async def test_a_cancelled_runner_does_not_stop_the_process():
    stop = StopRecorder()
    task = asyncio.create_task(asyncio.Event().wait(), name="job consumer")
    supervise(task, stop=stop)

    task.cancel()
    await settle(task)

    assert stop.calls == 0
