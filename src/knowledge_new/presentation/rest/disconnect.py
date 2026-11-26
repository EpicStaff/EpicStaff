import asyncio
from collections.abc import Coroutine
from typing import Any

from litestar import Request
from loguru import logger

__all__ = ["HTTP_499_CLIENT_CLOSED_REQUEST", "run_until_disconnect"]

# Not an IANA code: nginx's "client closed request", for a response nobody will read.
HTTP_499_CLIENT_CLOSED_REQUEST = 499


async def run_until_disconnect[T](request: Request, work: Coroutine[Any, Any, T]) -> T | None:
    """Run `work` until it finishes or the client disconnects, whichever comes first.

    Call only after the request body has been read: the disconnect watcher consumes
    `receive()` messages, so it would swallow body chunks the handler still needs.

    Returns:
        The result of `work`, or None when the client disconnected first. `work` is
        then cancelled and has finished its cleanup by the time this returns.
    """
    work_task = asyncio.create_task(work)
    watcher = asyncio.create_task(_wait_for_disconnect(request))
    try:
        await asyncio.wait({work_task, watcher}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        watcher.cancel()
        if not work_task.done():
            work_task.cancel()
            # The request's dependencies (unit of work) are closed once the handler
            # returns, so the cancelled work must finish its cleanup first. `wait`, not
            # `await`: it does not raise the work's cancellation, yet still lets a
            # cancellation of this task (server shutdown) through.
            await asyncio.wait({work_task})
    if work_task.cancelled():
        logger.info("Client disconnected from {}; the request was cancelled.", request.url.path)
        return None
    return work_task.result()


async def _wait_for_disconnect(request: Request) -> None:
    while (await request.receive())["type"] != "http.disconnect":
        pass
