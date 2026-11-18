import asyncio

import pytest

from foundation.utils import task_scheduler as ts


@pytest.fixture(autouse=True)
def _reset_scheduler_state():
    """`_schedule`/`_running`/`_is_run` are module globals shared across every test."""
    ts._schedule.clear()
    ts._running.clear()
    ts._is_run = False
    yield
    ts._schedule.clear()
    ts._running.clear()
    ts._is_run = False


def test_schedule_bare_registers_a_one_shot_entry():
    @ts.schedule
    async def job():
        pass

    assert len(ts._schedule) == 1
    assert ts._schedule[0].work is job
    assert ts._schedule[0].interval is None
    assert ts._schedule[0].is_interval is False


def test_schedule_with_interval_registers_a_repeating_entry():
    @ts.schedule(interval=5)
    async def job():
        pass

    assert ts._schedule[0].interval == 5
    assert ts._schedule[0].is_interval is True


def test_schedule_entry_rejects_non_callable_work():
    with pytest.raises(TypeError):
        ts.ScheduleEntry(work="not callable")


def test_schedule_entry_rejects_non_positive_interval():
    async def job():
        pass

    with pytest.raises(ValueError):
        ts.ScheduleEntry(work=job, interval=0)


def test_schedule_entry_rejects_non_numeric_interval():
    async def job():
        pass

    with pytest.raises(TypeError):
        ts.ScheduleEntry(work=job, interval="5")


@pytest.mark.asyncio
async def test_start_runs_a_one_shot_job_once():
    calls = []

    @ts.schedule
    async def job():
        calls.append(1)

    await ts.start()
    await asyncio.sleep(0.05)
    await ts.stop()
    assert calls == [1]


@pytest.mark.asyncio
async def test_start_is_a_noop_if_already_started():
    calls = []

    @ts.schedule
    async def job():
        calls.append(1)

    await ts.start()
    await ts.start()
    await asyncio.sleep(0.05)
    await ts.stop()
    assert calls == [1]


@pytest.mark.asyncio
async def test_stop_is_a_noop_if_never_started():
    await ts.stop()


@pytest.mark.asyncio
async def test_stop_cancels_interval_jobs_and_resets_state():
    calls = []

    @ts.schedule(interval=0.01)
    async def job():
        calls.append(1)

    await ts.start()
    await asyncio.sleep(0.05)
    await ts.stop()

    count_after_stop = len(calls)
    assert count_after_stop >= 1
    assert ts._is_run is False
    assert ts._running == set()

    await asyncio.sleep(0.05)
    assert len(calls) == count_after_stop


@pytest.mark.asyncio
async def test_run_logs_exception_instead_of_raising():
    async def failing():
        raise RuntimeError("boom")

    await ts.run(failing)


@pytest.mark.asyncio
async def test_run_in_interval_runs_repeatedly_until_cancelled():
    calls = []

    async def job():
        calls.append(1)

    task = asyncio.create_task(ts.run_in_interval(job, 0.01))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(calls) >= 2
