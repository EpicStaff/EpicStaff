import asyncio

import pytest
from litellm.litellm_core_utils.logging_worker import GLOBAL_LOGGING_WORKER

from services.background_event_loop import background_loop


@pytest.fixture
def isolated_logging_worker():
    saved = (GLOBAL_LOGGING_WORKER._queue, GLOBAL_LOGGING_WORKER._worker_task)
    GLOBAL_LOGGING_WORKER._queue = None
    GLOBAL_LOGGING_WORKER._worker_task = None
    yield GLOBAL_LOGGING_WORKER
    GLOBAL_LOGGING_WORKER._queue, GLOBAL_LOGGING_WORKER._worker_task = saved


async def _emit_one_callback(worker):
    async def callback():
        return None

    worker.ensure_initialized_and_enqueue(callback())
    await asyncio.sleep(0.05)


def _worker_crashed(worker) -> bool:
    task = worker._worker_task
    if not (task and task.done()) or task.cancelled():
        return False
    return task.exception() is not None


def test_logging_worker_survives_repeated_indexing(isolated_logging_worker):
    worker = isolated_logging_worker

    background_loop.run(_emit_one_callback(worker))
    assert not _worker_crashed(worker)

    background_loop.run(_emit_one_callback(worker))
    assert not _worker_crashed(worker)


def test_run_uses_one_stable_loop():
    async def loop_id():
        return id(asyncio.get_running_loop())

    assert background_loop.run(loop_id()) == background_loop.run(loop_id())


def test_run_rejects_non_coroutine():
    with pytest.raises(TypeError):
        background_loop.run(lambda: None)


def test_old_asyncio_run_pattern_crashes_worker(isolated_logging_worker):
    worker = isolated_logging_worker
    asyncio.run(_emit_one_callback(worker))   # Loop A: bind query
    asyncio.run(_emit_one_callback(worker))   # Loop B: crash
    assert _worker_crashed(worker)