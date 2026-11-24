"""The `sandbox_gate` BENCH checkpoint: the worker's run-gate sample."""

import asyncio

import pytest

from worker.application.resource_gate import ResourceAdmissionGate
from worker.presentation.run_gate_sampler import RunGateSampler
from tests.fakes import FakeHostMetrics

INTERVAL = 0.01


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


def samples(checkpoints: list[dict]) -> list[dict]:
    return [item for item in checkpoints if item["checkpoint"] == "sandbox_gate"]


async def test_a_sample_reports_the_run_gate(checkpoints):
    run_gate = build_run_gate(cpu=42.16, memory=None)
    await run_gate.acquire()
    sampler = RunGateSampler(run_gate, interval=INTERVAL)

    task = asyncio.create_task(sampler.run())
    deadline = asyncio.get_running_loop().time() + 1.0
    while not samples(checkpoints):
        assert asyncio.get_running_loop().time() < deadline, "the sampler never sampled"
        await asyncio.sleep(INTERVAL)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert samples(checkpoints)[0] == {
        "checkpoint": "sandbox_gate",
        "running": 1,
        "floor": 2,
        "max_concurrent": 4,
        "cpu_busy_percent": 42.2,
        "memory_used_percent": None,
    }
