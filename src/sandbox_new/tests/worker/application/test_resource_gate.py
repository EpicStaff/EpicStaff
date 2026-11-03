"""When the resource admission gate lets the next execution start.

Below the floor a job always starts. Above it, up to the maximum, a job starts only while
CPU and memory are under their thresholds and the per-tick burst budget (`floor` starts)
is not spent. An unreadable metric never blocks. Load comes from a stand-in for the
metrics reader, so each test sets exactly the reading it is about.
"""

import asyncio

import pytest

from worker.application.ports import HostSample
from worker.application.resource_gate import ResourceAdmissionGate
from tests.fakes import FakeHostMetrics


def build_gate(
    metrics: FakeHostMetrics, *, min_concurrent: int = 1, max_concurrent: int = 10
) -> ResourceAdmissionGate:
    gate = ResourceAdmissionGate(
        metrics,
        min_concurrent=min_concurrent,
        max_concurrent=max_concurrent,
        cpu_threshold=85,
        memory_threshold=80,
    )
    gate.refresh()
    return gate


async def acquire_now(gate: ResourceAdmissionGate) -> bool:
    """Whether a slot is taken without waiting; a wait that times out takes none."""
    try:
        await asyncio.wait_for(gate.acquire(), timeout=0.05)
    except TimeoutError:
        return False
    return True


async def take(gate: ResourceAdmissionGate, count: int) -> None:
    for _ in range(count):
        assert await acquire_now(gate)


async def test_below_the_floor_a_job_starts_under_full_load():
    gate = build_gate(FakeHostMetrics(cpu=100.0, memory=100.0), min_concurrent=2)

    await take(gate, 2)

    assert gate.has_free_slot() is False
    assert await acquire_now(gate) is False


async def test_an_automatic_floor_is_the_cpus_the_container_may_use():
    gate = build_gate(FakeHostMetrics(floor=3, cpu=100.0, memory=100.0), min_concurrent=0)

    await take(gate, 3)

    assert gate.has_free_slot() is False


@pytest.mark.parametrize(
    ("cpu", "memory"), [(85.0, 10.0), (10.0, 80.0)], ids=["cpu-at-threshold", "memory-at-threshold"]
)
async def test_load_at_a_threshold_blocks_starts_above_the_floor(cpu, memory):
    gate = build_gate(FakeHostMetrics(cpu=cpu, memory=memory))
    await take(gate, 1)

    assert gate.has_free_slot() is False


async def test_load_under_the_thresholds_admits_above_the_floor():
    gate = build_gate(FakeHostMetrics(cpu=84.0, memory=79.0))
    await take(gate, 1)

    assert gate.has_free_slot() is True


async def test_no_more_than_the_maximum_run_at_once():
    gate = build_gate(FakeHostMetrics(), min_concurrent=2, max_concurrent=3)

    await take(gate, 3)

    assert gate.has_free_slot() is False


async def test_a_floor_above_the_maximum_is_held_to_the_maximum():
    gate = build_gate(FakeHostMetrics(cpu=100.0, memory=100.0), min_concurrent=5, max_concurrent=2)

    await take(gate, 2)

    assert gate.has_free_slot() is False


async def test_at_most_floor_jobs_start_above_the_floor_per_tick():
    gate = build_gate(FakeHostMetrics(), min_concurrent=2)

    await take(gate, 4)

    assert gate.has_free_slot() is False
    gate.refresh()
    await take(gate, 2)
    assert gate.has_free_slot() is False


async def test_unreadable_metrics_fall_back_to_the_floor_burst_and_maximum():
    gate = build_gate(FakeHostMetrics(cpu=None, memory=None), max_concurrent=3)

    await take(gate, 2)
    assert gate.has_free_slot() is False

    gate.refresh()
    await take(gate, 1)
    gate.refresh()
    assert gate.has_free_slot() is False


async def test_a_waiting_job_starts_when_a_slot_is_released():
    gate = build_gate(FakeHostMetrics(cpu=100.0), max_concurrent=1)
    await take(gate, 1)
    waiting = asyncio.create_task(gate.acquire())
    await asyncio.sleep(0.01)
    assert not waiting.done()

    gate.release()

    await asyncio.wait_for(waiting, timeout=1)


async def test_a_waiting_job_starts_when_a_tick_shows_headroom():
    metrics = FakeHostMetrics(cpu=100.0)
    gate = build_gate(metrics)
    await take(gate, 1)
    waiting = asyncio.create_task(gate.acquire())
    await asyncio.sleep(0.01)
    assert not waiting.done()

    metrics.reading = HostSample(cpu_busy_percent=10.0, memory_used_percent=10.0)
    gate.refresh()

    await asyncio.wait_for(waiting, timeout=1)


async def test_an_abandoned_wait_takes_no_slot():
    gate = build_gate(FakeHostMetrics(cpu=100.0), max_concurrent=1)
    await take(gate, 1)
    assert await acquire_now(gate) is False

    gate.release()

    assert gate.has_free_slot() is True
    await take(gate, 1)
    assert gate.has_free_slot() is False


async def test_run_samples_the_load_every_tick():
    metrics = FakeHostMetrics(cpu=100.0)
    gate = ResourceAdmissionGate(
        metrics,
        min_concurrent=1,
        max_concurrent=10,
        cpu_threshold=85,
        memory_threshold=80,
        tick_seconds=0.01,
    )
    await take(gate, 1)
    runner = asyncio.create_task(gate.run())
    try:
        await asyncio.sleep(0.05)
        assert gate.has_free_slot() is False

        metrics.reading = HostSample(cpu_busy_percent=10.0, memory_used_percent=10.0)
        await asyncio.sleep(0.05)

        assert gate.has_free_slot() is True
    finally:
        runner.cancel()
