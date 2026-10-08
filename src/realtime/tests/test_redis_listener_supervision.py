"""The Redis listener supervisor task must be held strongly for the life of the
app: the event loop keeps only a weak reference, so an unreferenced task can be
garbage-collected and nothing would restart the listener.
"""

import asyncio
import gc
import weakref
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def stubbed_startup(monkeypatch):
    from api import main

    started = asyncio.Event()

    async def fake_redis_listener():
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(main, "init_db", AsyncMock())
    monkeypatch.setattr(main.knowledge_client, "start", AsyncMock())
    monkeypatch.setattr(main.knowledge_client, "stop", AsyncMock())
    monkeypatch.setattr(main, "redis_listener", fake_redis_listener)
    return main, started


@pytest.mark.asyncio
async def test_startup_keeps_listener_task_alive_across_garbage_collection(stubbed_startup):
    main, started = stubbed_startup
    tasks_before = asyncio.all_tasks()

    await main.startup_event()
    (new_task,) = asyncio.all_tasks() - tasks_before
    task_ref = weakref.ref(new_task)
    del new_task
    try:
        # Once parked on its pending future the task is reachable only through
        # that future's cycle, so only a strong reference held by the app saves it.
        await asyncio.wait_for(started.wait(), timeout=1.0)
        gc.collect()

        assert task_ref() is not None
        assert not task_ref().done()
    finally:
        await main.shutdown_event()


@pytest.mark.asyncio
async def test_shutdown_cancels_and_awaits_listener_task(stubbed_startup):
    main, started = stubbed_startup

    await main.startup_event()
    task = main.app.state.redis_listener_task
    await asyncio.wait_for(started.wait(), timeout=1.0)

    await main.shutdown_event()

    assert task.cancelled()
    main.knowledge_client.stop.assert_awaited_once()
