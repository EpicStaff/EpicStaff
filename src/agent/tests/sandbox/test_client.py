"""SandboxClient: submits code tasks over Redis pub/sub and matches results by execution id.

Redis is replaced by a small in-memory pub/sub (fakeredis is not an agent
dependency); a fake sandbox subscribes to the request channel and answers each
task the way the sandbox service does.
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest
from app.sandbox import client as client_module
from app.sandbox.client import SandboxClient
from shared.models.tools import CodeResultData, CodeTaskData

REQUESTS = "code_exec_tasks"
RESULTS = "code_results"


def _task(code: str = "def main(): return 'ok'") -> CodeTaskData:
    return CodeTaskData(
        venv_name="venv_test",
        libraries=[],
        code=code,
        execution_id="placeholder",
        entrypoint="main",
        func_kwargs={},
        global_kwargs={},
    )


class FakePubSubServer:
    """Channel name -> subscriber queues; delivery is immediate and in order."""

    def __init__(self):
        self.channels: dict[str, list[asyncio.Queue]] = {}


class FakePubSub:
    def __init__(self, server: FakePubSubServer):
        self._server = server
        self._queue: asyncio.Queue = asyncio.Queue()

    async def subscribe(self, channel: str) -> None:
        self._server.channels.setdefault(channel, []).append(self._queue)
        await self._queue.put({"type": "subscribe", "data": 1})

    async def get_message(self, ignore_subscribe_messages=False, timeout=None):
        try:
            message = await asyncio.wait_for(self._queue.get(), timeout)
        except asyncio.TimeoutError:
            return None
        if ignore_subscribe_messages and message["type"] != "message":
            return None
        return message

    async def listen(self):
        while True:
            yield await self._queue.get()

    async def aclose(self) -> None:
        for queues in self._server.channels.values():
            if self._queue in queues:
                queues.remove(self._queue)

    close = aclose


class FakeRedis:
    def __init__(self, server: FakePubSubServer):
        self._server = server

    def pubsub(self) -> FakePubSub:
        return FakePubSub(self._server)

    async def publish(self, channel: str, data) -> None:
        payload = data.encode() if isinstance(data, str) else data
        for queue in self._server.channels.get(channel, []):
            await queue.put({"type": "message", "data": payload})

    async def aclose(self) -> None:
        pass


@pytest.fixture
def redis_server(monkeypatch):
    server = FakePubSubServer()
    monkeypatch.setattr(client_module.aioredis, "Redis", lambda **kwargs: FakeRedis(server))
    return server


@contextlib.asynccontextmanager
async def fake_sandbox(server, answer=lambda task: [task.code]):
    """Answers every task on the request channel with the messages `answer(task)` returns.

    A message is either a raw payload or a result_data string for the task's own id.
    """
    redis = FakeRedis(server)
    pubsub = redis.pubsub()
    await pubsub.subscribe(REQUESTS)
    received: list[CodeTaskData] = []

    async def serve():
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.05)
            if message is None:
                continue
            task = CodeTaskData.model_validate_json(message["data"])
            received.append(task)
            for reply in answer(task):
                if isinstance(reply, bytes):
                    await redis.publish(RESULTS, reply)
                else:
                    result = CodeResultData(
                        execution_id=task.execution_id, result_data=reply, stderr="", stdout="", returncode=0
                    )
                    await redis.publish(RESULTS, result.model_dump_json())

    server_task = asyncio.create_task(serve())
    try:
        yield received
    finally:
        server_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await server_task
        await pubsub.aclose()
        await redis.aclose()


@pytest.fixture
async def client(redis_server):
    sandbox_client = SandboxClient(
        host="unused", port=0, password=None, request_channel=REQUESTS, result_channel=RESULTS
    )
    await sandbox_client.start()
    yield sandbox_client
    await sandbox_client.stop()


async def test_submitted_task_gets_a_fresh_execution_id_and_its_result(client, redis_server):
    async with fake_sandbox(redis_server) as received:
        result = await asyncio.wait_for(client.submit(_task("code-1")), timeout=2)

    (task,) = received
    assert task.execution_id != "placeholder"
    assert (result.execution_id, result.result_data) == (task.execution_id, "code-1")


async def test_concurrent_submits_each_get_their_own_result(client, redis_server):
    async with fake_sandbox(redis_server):
        first, second = await asyncio.wait_for(
            asyncio.gather(client.submit(_task("code-1")), client.submit(_task("code-2"))), timeout=2
        )

    assert (first.result_data, second.result_data) == ("code-1", "code-2")


async def test_malformed_and_foreign_results_are_ignored(client, redis_server):
    def answer(task):
        foreign = CodeResultData(
            execution_id="someone-else", result_data="foreign", stderr="", stdout="", returncode=0
        )
        return [b"not valid json {{{", foreign.model_dump_json().encode(), "mine"]

    async with fake_sandbox(redis_server, answer):
        result = await asyncio.wait_for(client.submit(_task()), timeout=2)

    assert result.result_data == "mine"


async def test_submit_times_out_when_the_sandbox_never_answers(client, redis_server):
    async with fake_sandbox(redis_server, answer=lambda task: []):
        with pytest.raises(asyncio.TimeoutError):
            await client.submit(_task(), timeout=0.2)


async def test_stop_fails_submits_still_waiting(redis_server):
    sandbox_client = SandboxClient(
        host="unused", port=0, password=None, request_channel=REQUESTS, result_channel=RESULTS
    )
    await sandbox_client.start()
    async with fake_sandbox(redis_server, answer=lambda task: []) as received:
        waiting = asyncio.create_task(sandbox_client.submit(_task()))
        while not received:
            await asyncio.sleep(0.01)

        await sandbox_client.stop()

        with pytest.raises(ConnectionError, match="SandboxClient stopped"):
            await asyncio.wait_for(waiting, timeout=2)
