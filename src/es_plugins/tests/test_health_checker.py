"""The health check reads a plugin's status line only, within one deadline for the whole exchange."""

import asyncio
import time

import pytest

from es_plugins.health import health_checker
from es_plugins.health.health_checker import HealthChecker

CHUNK = b"x" * 65536


class Plugin:
    """A loopback server that answers the health check the way a test sets."""

    def __init__(self, answer):
        self._answer = answer
        self.connection_closed = asyncio.Event()
        self.body_bytes_sent = 0
        self._server = None
        self._handlers: set[asyncio.Task] = set()

    async def __aenter__(self):
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        return self

    async def __aexit__(self, *_):
        self._server.close()
        # The server waits for its connections: end the answers still under way first.
        for handler in self._handlers:
            handler.cancel()
        await asyncio.gather(*self._handlers, return_exceptions=True)
        await self._server.wait_closed()

    @property
    def port(self) -> int:
        return self._server.sockets[0].getsockname()[1]

    async def _serve(self, reader, stream):
        self._handlers.add(asyncio.current_task())
        await reader.readuntil(b"\r\n\r\n")
        try:
            await self._answer(self, stream)
        except (ConnectionError, OSError):
            self.connection_closed.set()
        finally:
            stream.close()


async def endless_body(plugin, stream):
    stream.write(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n")
    while True:
        stream.write(b"%x\r\n%s\r\n" % (len(CHUNK), CHUNK))
        await stream.drain()
        plugin.body_bytes_sent += len(CHUNK)


def status_line_and_nothing_more(status: int):
    async def answer(plugin, stream):
        stream.write(f"HTTP/1.1 {status} Status\r\nContent-Length: 1000000\r\n\r\n".encode())
        await stream.drain()
        await asyncio.sleep(60)

    return answer


async def no_answer(plugin, stream):
    await asyncio.sleep(60)


@pytest.fixture
async def checker():
    checker = HealthChecker()
    yield checker
    await checker.aclose()


async def test_a_200_with_an_endless_body_is_healthy_and_the_body_is_never_read(checker):
    async with Plugin(endless_body) as plugin:
        started = time.monotonic()

        assert await checker.is_healthy(plugin.port)

        assert time.monotonic() - started < 1
        # The node hung up on the body: the plugin's next writes fail.
        await asyncio.wait_for(plugin.connection_closed.wait(), 5)
        assert plugin.body_bytes_sent < 64 * 1024 * 1024


@pytest.mark.parametrize(("status", "healthy"), [(200, True), (503, False)])
async def test_the_status_alone_decides_while_the_body_never_comes(checker, status, healthy):
    async with Plugin(status_line_and_nothing_more(status)) as plugin:
        started = time.monotonic()

        assert await checker.is_healthy(plugin.port) is healthy

        assert time.monotonic() - started < 1


async def test_a_plugin_that_never_answers_is_unhealthy_within_the_deadline(checker, monkeypatch):
    monkeypatch.setattr(health_checker, "HEALTH_TIMEOUT_SECONDS", 0.3)
    async with Plugin(no_answer) as plugin:
        started = time.monotonic()

        assert not await checker.is_healthy(plugin.port)

        assert time.monotonic() - started < 2


async def test_a_port_nothing_listens_on_is_unhealthy(checker):
    async with Plugin(no_answer) as plugin:
        port = plugin.port

    assert not await checker.is_healthy(port)
