"""Behavior of the held-job release loop.

It polls rather than hooking into the build, so the tests check that a pass happens and
that a failing pass does not kill the loop.
"""

import asyncio

import pytest

from manager.presentation.held_job_releaser import HeldJobReleaser


class RecordingOrchestrator:
    """Stands in for ``JobOrchestrator``; the releaser only ever calls one method."""

    def __init__(self, fail_times: int = 0) -> None:
        self.passes = 0
        self._fail_times = fail_times

    async def flush_pending(self) -> None:
        self.passes += 1
        if self.passes <= self._fail_times:
            raise RuntimeError("database is gone")


async def run_until(releaser: HeldJobReleaser, orchestrator: RecordingOrchestrator, passes: int):
    task = asyncio.create_task(releaser.run())
    try:
        for _ in range(200):
            if orchestrator.passes >= passes:
                return
            await asyncio.sleep(0.005)
        raise AssertionError(f"made {orchestrator.passes} passes, expected {passes}")
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_each_tick_runs_a_release_pass():
    orchestrator = RecordingOrchestrator()

    await run_until(HeldJobReleaser(orchestrator, interval=0.01), orchestrator, passes=2)

    assert orchestrator.passes >= 2


async def test_a_failing_pass_does_not_stop_the_loop():
    orchestrator = RecordingOrchestrator(fail_times=1)

    await run_until(HeldJobReleaser(orchestrator, interval=0.01), orchestrator, passes=3)

    assert orchestrator.passes >= 3
