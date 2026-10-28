"""One runaway, crashed or abandoned call must not take the shared process pool from
every other caller (organization) of the knowledge service."""

import asyncio
import os
import signal
import time
from pathlib import Path

import pytest
import settings
from bootstrap import lifespans
from infrastructure.processing_run import get_process_pool, run_in_process
from pebble import ProcessExpired

# Upper bound for anything a test awaits, so a regression fails instead of hanging CI.
SAFETY_BOUND_SECONDS = 5
HANG_SECONDS = 30


@run_in_process
def hang(pid_file: Path) -> None:
    pid_file.write_text(str(os.getpid()))
    time.sleep(HANG_SECONDS)


@run_in_process
def kill_own_worker() -> None:
    # Outlast pebble's 0.1 s poll so the pool records this task as started on this
    # worker; dying sooner can be reported as a whole-pool break, not ProcessExpired.
    time.sleep(0.3)
    os.kill(os.getpid(), signal.SIGKILL)


@run_in_process
def worker_pid() -> int:
    return os.getpid()


@pytest.fixture
def single_worker_pool(monkeypatch):
    monkeypatch.setattr(settings, "MAX_PROCESS_WORKERS", 1)
    lifespans.init_process_pool()
    yield
    lifespans.close_process_pool()


async def within_bound(awaitable):
    task = asyncio.ensure_future(awaitable)
    done, _ = await asyncio.wait({task}, timeout=SAFETY_BOUND_SECONDS)
    if not done:
        task.cancel()
        pytest.fail(f"offloaded call still running after {SAFETY_BOUND_SECONDS}s")
    return task.result()


async def wait_until_started(pid_file: Path) -> int:
    deadline = time.monotonic() + SAFETY_BOUND_SECONDS
    while not pid_file.exists() or not pid_file.read_text():
        if time.monotonic() > deadline:
            pytest.fail("offloaded call never started")
        await asyncio.sleep(0.02)
    return int(pid_file.read_text())


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def test_call_past_timeout_fails_and_pool_serves_next_call(
    single_worker_pool, monkeypatch, tmp_path
):
    monkeypatch.setattr(settings, "PROCESS_TIMEOUT", 0.5)
    pid_file = tmp_path / "hang.pid"

    with pytest.raises(TimeoutError):
        await within_bound(hang(pid_file))

    hung_pid = int(pid_file.read_text())
    assert await within_bound(worker_pid()) != hung_pid
    assert not process_exists(hung_pid)


async def test_worker_killed_mid_call_fails_only_that_call(single_worker_pool):
    with pytest.raises(ProcessExpired):
        await within_bound(kill_own_worker())

    assert await within_bound(worker_pid()) != os.getpid()


async def test_cancelling_awaiting_task_frees_the_worker(
    single_worker_pool, monkeypatch, tmp_path
):
    # Far beyond the safety bound, so only the cancellation can free the single worker.
    monkeypatch.setattr(settings, "PROCESS_TIMEOUT", HANG_SECONDS)
    pid_file = tmp_path / "hang.pid"
    hanging_call = asyncio.ensure_future(hang(pid_file))
    hung_pid = await wait_until_started(pid_file)

    hanging_call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await hanging_call

    assert await within_bound(worker_pid()) != hung_pid
    assert not process_exists(hung_pid)


async def test_shutdown_terminates_running_call(single_worker_pool, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "PROCESS_TIMEOUT", HANG_SECONDS)
    pid_file = tmp_path / "hang.pid"
    hanging_call = asyncio.ensure_future(hang(pid_file))
    hung_pid = await wait_until_started(pid_file)

    started = time.monotonic()
    lifespans.close_process_pool()
    hanging_call.cancel()

    assert time.monotonic() - started < SAFETY_BOUND_SECONDS
    assert not process_exists(hung_pid)


async def test_pool_broken_by_idle_worker_death_is_replaced(single_worker_pool):
    idle_worker_pid = await within_bound(worker_pid())
    os.kill(idle_worker_pid, signal.SIGKILL)
    deadline = time.monotonic() + SAFETY_BOUND_SECONDS
    while get_process_pool().active:
        if time.monotonic() > deadline:
            pytest.fail("pool never noticed the dead worker")
        await asyncio.sleep(0.02)

    assert await within_bound(worker_pid()) != idle_worker_pid
