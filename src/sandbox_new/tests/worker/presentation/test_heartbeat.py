"""Behavior of the heartbeat loop: it keeps beating and reports what the worker holds."""

import asyncio
import json

import httpx
import pytest

from foundation.transport.http import AsyncClient
from worker.presentation.heartbeat import Heartbeat


class CountingHandler:
    def __init__(self, *failures_first: Exception):
        self.failures = list(failures_first)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.failures:
            raise self.failures.pop(0)
        return httpx.Response(204)


def client_for(handler: CountingHandler) -> AsyncClient:
    return AsyncClient(
        base_url="http://manager:8090",
        transport=httpx.MockTransport(handler),
        headers={"X-Worker-Boot-Id": "boot-1"},
    )


async def beat_until(heartbeat: Heartbeat, handler: CountingHandler, count: int) -> None:
    task = asyncio.create_task(heartbeat.run())
    try:
        deadline = asyncio.get_running_loop().time() + 1.0
        while len(handler.requests) < count:
            assert asyncio.get_running_loop().time() < deadline, "the heartbeat stopped"
            await asyncio.sleep(0.005)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_the_heartbeat_reports_the_held_executions_every_interval():
    handler = CountingHandler()
    heartbeat = Heartbeat(
        client_for(handler), lambda: {"exec-2", "exec-1"}, interval=0.01
    )

    await beat_until(heartbeat, handler, count=2)

    request = handler.requests[0]
    assert request.url.path == "/worker/heartbeat"
    assert request.headers["X-Worker-Boot-Id"] == "boot-1"
    assert json.loads(request.content) == {"execution_ids": ["exec-1", "exec-2"]}


async def test_a_failed_beat_does_not_stop_the_loop():
    handler = CountingHandler(httpx.ConnectError("refused"))
    heartbeat = Heartbeat(client_for(handler), lambda: set(), interval=0.01)

    await beat_until(heartbeat, handler, count=3)

    assert len(handler.requests) >= 3
