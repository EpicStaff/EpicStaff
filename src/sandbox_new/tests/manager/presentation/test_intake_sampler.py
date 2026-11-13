"""The `sandbox_intake` BENCH checkpoint: the manager's admission sample.

A sample that fails is skipped without stopping the sampler -- it runs under the runner
supervision, which would take the whole process down.
"""

import asyncio

import pytest

from manager.application.registry import ExecutionRegistry
from manager.presentation.intake_sampler import IntakeSampler

INTERVAL = 0.01


class RegistryFailingOnce(ExecutionRegistry):
    """A registry whose first drain-rate reading blows up, then behaves."""

    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    def drain_rate(self) -> float | None:
        if not self.failed:
            self.failed = True
            raise RuntimeError("registry broke")
        return super().drain_rate()


def samples(checkpoints: list[dict]) -> list[dict]:
    return [item for item in checkpoints if item["checkpoint"] == "sandbox_intake"]


async def sample_until(sampler: IntakeSampler, checkpoints: list[dict], count: int):
    """Start the sampler and return its task once `count` samples were logged."""
    task = asyncio.create_task(sampler.run())
    deadline = asyncio.get_running_loop().time() + 1.0
    while len(samples(checkpoints)) < count:
        assert asyncio.get_running_loop().time() < deadline, "the sampler stopped sampling"
        await asyncio.sleep(INTERVAL)
    return task


async def stop(task: asyncio.Task) -> None:
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_a_sample_reports_the_intake_side(checkpoints):
    registry = ExecutionRegistry()
    registry.reserve("queued")
    registry.mark_queued("queued")
    registry.reserve("held")
    registry.mark_held("held")

    task = await sample_until(IntakeSampler(registry, interval=INTERVAL), checkpoints, 1)
    await stop(task)

    assert samples(checkpoints)[0] == {
        "checkpoint": "sandbox_intake",
        "queued": 1,
        "held": 1,
        "drain_rate": None,
    }


async def test_a_sample_that_fails_is_skipped_and_the_sampler_goes_on(checkpoints):
    registry = RegistryFailingOnce()
    sampler = IntakeSampler(registry, interval=INTERVAL)

    task = await sample_until(sampler, checkpoints, 1)

    assert registry.failed is True
    assert not task.done()
    await stop(task)
