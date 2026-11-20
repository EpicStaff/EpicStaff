import asyncio

import pytest
from litestar import Litestar, Request, get
from litestar.testing import TestClient
from presentation.rest.disconnect import ClientDisconnectedError, cancel_on_disconnect
from presentation.rest.error_handlers import get_error_handlers


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
        return Request(scope={"type": "http"}, receive=self.receive)


async def test_block_result_is_kept_when_the_client_stays():
    connection = ClientConnection()

    async with cancel_on_disconnect(connection.request()):
        result = await asyncio.sleep(0.01, result="found")

    assert result == "found"
    assert asyncio.current_task().cancelling() == 0


async def test_disconnect_cancels_the_block_and_raises_client_disconnected():
    connection = ClientConnection()
    inner_cancelled = False

    with pytest.raises(ClientDisconnectedError):
        async with cancel_on_disconnect(connection.request()):
            connection.drop()
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                inner_cancelled = True
                raise

    assert inner_cancelled
    assert asyncio.current_task().cancelling() == 0


async def test_swallowed_cancel_still_raises_client_disconnected():
    connection = ClientConnection()

    with pytest.raises(ClientDisconnectedError):
        async with cancel_on_disconnect(connection.request()):
            connection.drop()
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                pass

    assert asyncio.current_task().cancelling() == 0


async def test_outside_cancel_is_not_reported_as_disconnect():
    connection = ClientConnection()

    async def handler():
        async with cancel_on_disconnect(connection.request()):
            await asyncio.sleep(10)

    task = asyncio.create_task(handler())
    await asyncio.sleep(0.01)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


async def test_disconnect_together_with_outside_cancel_keeps_the_cancel():
    connection = ClientConnection()

    async def handler():
        async with cancel_on_disconnect(connection.request()):
            await asyncio.sleep(10)

    task = asyncio.create_task(handler())
    await asyncio.sleep(0.01)
    connection.drop()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


async def test_disconnect_is_reported_when_the_task_entered_with_a_swallowed_cancel():
    connection = ClientConnection()

    async def handler():
        # Earlier code swallowed a cancellation without uncancel(): cancelling() stays 1.
        asyncio.current_task().cancel()
        try:
            await asyncio.sleep(0)
        except asyncio.CancelledError:
            pass
        async with cancel_on_disconnect(connection.request()):
            connection.drop()
            await asyncio.sleep(10)

    with pytest.raises(ClientDisconnectedError):
        await asyncio.create_task(handler())


async def test_watcher_cannot_cancel_after_the_block_ends():
    connection = ClientConnection()

    async with cancel_on_disconnect(connection.request()):
        pass
    connection.drop()
    await asyncio.sleep(0.05)

    assert asyncio.current_task().cancelling() == 0


def test_client_disconnected_error_is_answered_with_499_and_no_body():
    @get("/disconnected")
    async def disconnected() -> None:
        raise ClientDisconnectedError

    app = Litestar(route_handlers=[disconnected], exception_handlers=get_error_handlers())
    with TestClient(app=app) as client:
        response = client.get("/disconnected")

    assert response.status_code == 499
    assert response.content == b""
