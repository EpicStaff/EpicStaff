import asyncio
from types import TracebackType

from litestar import Request

__all__ = ["ClientDisconnectedError", "cancel_on_disconnect"]


class ClientDisconnectedError(Exception):
    """The client closed the connection before the response was ready."""


class _CancelOnDisconnect:
    def __init__(self, request: Request) -> None:
        self._request = request
        self._disconnected = False
        self._task: asyncio.Task | None = None
        self._watcher: asyncio.Task | None = None
        self._cancelling_on_entry = 0

    async def __aenter__(self) -> None:
        self._task = asyncio.current_task()
        self._cancelling_on_entry = self._task.cancelling()
        self._watcher = asyncio.create_task(self._watch())

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        # Cancelled before any await, so the watcher cannot cancel the task once the block is over.
        self._watcher.cancel()
        # A count above the one on entry means someone else (a server shutdown) also
        # cancelled the task inside the block.
        if self._disconnected and self._task.uncancel() <= self._cancelling_on_entry:
            raise ClientDisconnectedError from exc

    async def _watch(self) -> None:
        while (await self._request.receive())["type"] != "http.disconnect":
            pass
        self._disconnected = True
        self._task.cancel()


def cancel_on_disconnect(request: Request) -> _CancelOnDisconnect:
    """Cancel the enclosed block when the client disconnects.

    Works like `asyncio.timeout()`: the block runs in the request's own task, and a
    disconnect cancels that task. On leaving the block the cancellation is turned into
    `ClientDisconnectedError`; a cancellation from anywhere else propagates unchanged.

    Enter the block only after the request body has been read: the watcher consumes
    `receive()` messages, so it would swallow body chunks the handler still needs.

    Raises:
        ClientDisconnectedError: The client disconnected while the block was running.
    """
    return _CancelOnDisconnect(request)
