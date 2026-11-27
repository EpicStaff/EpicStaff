import asyncio

import pytest
from litestar import Request
from presentation.rest.disconnect import run_until_disconnect


class ClientConnection:
    """ASGI `receive` of a client that stays connected until `drop()` is called."""

    def __init__(self) -> None:
        self._dropped = asyncio.Event()

    def drop(self) -> None:
        self._dropped.set()

    async def receive(self) -> dict:
        await self._dropped.wait()
        return {"type": "http.disconnect"}

    def request(self) -> Request:
        return Request(scope={"type": "http", "path": "/search"}, receive=self.receive)


class HangingWork:
    """Work that never finishes on its own; records its cancellation and cleanup."""

    def __init__(self, cleanup_seconds: float = 0) -> None:
        self.started = asyncio.Event()
        self.cancelled = False
        self.cleaned_up = False
        self._cleanup_seconds = cleanup_seconds

    async def run(self) -> str:
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            await asyncio.sleep(self._cleanup_seconds)
            self.cleaned_up = True
        return "never"


async def test_result_is_returned_when_the_client_stays():
    connection = ClientConnection()

    result = await run_until_disconnect(connection.request(), asyncio.sleep(0.01, result="found"))

    assert result == "found"


async def test_disconnect_cancels_the_work_and_waits_for_its_cleanup():
    connection = ClientConnection()
    work = HangingWork(cleanup_seconds=0.01)
    connection.drop()

    result = await run_until_disconnect(connection.request(), work.run())

    assert result is None
    assert work.cancelled
    assert work.cleaned_up


async def test_error_of_the_work_propagates_unchanged():
    connection = ClientConnection()

    async def failing() -> None:
        raise LookupError("rag 7 is gone")

    with pytest.raises(LookupError, match="rag 7 is gone"):
        await run_until_disconnect(connection.request(), failing())


async def test_error_raised_while_cleaning_up_after_a_disconnect_propagates_unchanged():
    connection = ClientConnection()

    async def failing_cleanup() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            raise LookupError("cleanup failed")

    connection.drop()

    with pytest.raises(LookupError, match="cleanup failed"):
        await run_until_disconnect(connection.request(), failing_cleanup())


async def test_outside_cancel_propagates_and_still_cancels_the_work():
    connection = ClientConnection()
    work = HangingWork()

    caller = asyncio.create_task(run_until_disconnect(connection.request(), work.run()))
    await work.started.wait()
    caller.cancel()

    with pytest.raises(asyncio.CancelledError):
        await caller
    assert work.cancelled
    assert work.cleaned_up


async def test_outside_cancel_during_cleanup_after_a_disconnect_is_not_swallowed():
    connection = ClientConnection()
    work = HangingWork(cleanup_seconds=0.05)

    caller = asyncio.create_task(run_until_disconnect(connection.request(), work.run()))
    await work.started.wait()
    connection.drop()
    while not work.cancelled:
        await asyncio.sleep(0)
    caller.cancel()

    with pytest.raises(asyncio.CancelledError):
        await caller
