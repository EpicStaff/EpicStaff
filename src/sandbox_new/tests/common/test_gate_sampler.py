"""The `sandbox_gate` BENCH checkpoint: one sample of both admission gates per interval.

A sample reports the intake side (queued, held, drain rate) next to the run gate (slots
in use, limits, last load reading). A sample that fails is skipped without stopping the
sampler -- it runs under the runner supervision, which would take the whole sandbox down.
"""

import asyncio

import pytest

from common.bootstrap.gate_sampler import GateSampler
from manager.application.registry import ExecutionRegistry
from worker.application.resource_gate import ResourceAdmissionGate
from tests.fakes import FakeHostMetrics

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


def build_run_gate(*, cpu: float | None, memory: float | None) -> ResourceAdmissionGate:
    gate = ResourceAdmissionGate(
        FakeHostMetrics(floor=2, cpu=cpu, memory=memory),
        min_concurrent=0,
        max_concurrent=4,
        cpu_threshold=85,
        memory_threshold=80,
    )
    gate.refresh()
    return gate


def gate_samples(checkpoints: list[dict]) -> list[dict]:
    return [item for item in checkpoints if item["checkpoint"] == "sandbox_gate"]


async def sample_until(sampler: GateSampler, checkpoints: list[dict], count: int) -> asyncio.Task:
    """Start the sampler and return its task once `count` samples were logged."""
    task = asyncio.create_task(sampler.run())
    deadline = asyncio.get_running_loop().time() + 1.0
    while len(gate_samples(checkpoints)) < count:
        assert asyncio.get_running_loop().time() < deadline, "the sampler stopped sampling"
        await asyncio.sleep(INTERVAL)
    return task


async def stop(task: asyncio.Task) -> None:
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_a_sample_reports_both_gates(checkpoints):
    registry = ExecutionRegistry()
    registry.reserve("queued")
    registry.mark_queued("queued")
    registry.reserve("held")
    registry.mark_held("held")
    run_gate = build_run_gate(cpu=42.16, memory=None)
    await run_gate.acquire()

    task = await sample_until(GateSampler(registry, run_gate, interval=INTERVAL), checkpoints, 1)
    await stop(task)

    assert gate_samples(checkpoints)[0] == {
        "checkpoint": "sandbox_gate",
        "running": 1,
        "floor": 2,
        "max_concurrent": 4,
        "cpu_busy_percent": 42.2,
        "memory_used_percent": None,
        "queued": 1,
        "held": 1,
        "drain_rate": None,
    }


async def test_a_sample_that_fails_is_skipped_and_the_sampler_goes_on(checkpoints):
    registry = RegistryFailingOnce()
    sampler = GateSampler(registry, build_run_gate(cpu=10.0, memory=10.0), interval=INTERVAL)

    task = await sample_until(sampler, checkpoints, 1)

    assert registry.failed is True
    assert not task.done()
    await stop(task)
