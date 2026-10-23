"""SandboxClient: submits code tasks to sandbox_new over HTTP and matches results by execution id.

The intake is the real foundation client over a MockTransport, so a test sees the
JSON body the agent actually posts to `POST /executions`. Results still come back on
Redis, which is replaced by a small in-memory pub/sub (fakeredis is not an agent
dependency); the fake sandbox answers each task the way the sandbox service does.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from app.sandbox import client as client_module
from app.sandbox.client import SandboxClient
from foundation.clients.sandbox import (
    SandboxError,
    SandboxExecutionLostError,
    SandboxOverloadedError,
    SandboxResultTimeoutError,
)
from foundation.clients.sandbox import client as foundation_sandbox_module
from shared.models.storage_scope import StorageCredentials
from shared.models.tools import CodeResultData, CodeTaskData

RESULTS = "code_results"
SANDBOX_BASE_URL = "http://sandbox:8000"


def _task(code: str = "def main(): return 'ok'", **overrides) -> CodeTaskData:
    fields = dict(
        code=code,
        execution_id="placeholder",
        entrypoint="main",
        func_kwargs={},
        global_kwargs={},
    )
    fields.update(overrides)
    return CodeTaskData(**fields)


def _storage_task(credentials: StorageCredentials) -> CodeTaskData:
    return _task(
        use_storage=True,
        storage_allowed_paths=["org_7/session_42/"],
        storage_org_prefix="org_7",
        org_id=7,
        session_id=42,
        storage_credentials=credentials,
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


class FakeSandbox:
    """sandbox_new's intake: records every submitted body and answers it on the result channel.

    `answer(body)` returns the messages the sandbox publishes for that body: a raw
    payload, or a result_data string wrapped in a result for the body's own id.
    `GET /executions/{id}` reports every execution as running, or as unknown (404)
    once `loses_executions` is set.
    """

    def __init__(self, redis: FakeRedis, answer=lambda body: [body["code"]]):
        self._redis = redis
        self._answer = answer
        self.bodies: list[dict] = []
        self.loses_executions = False

    async def handle(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            if self.loses_executions:
                return httpx.Response(404, json={"detail": "not found"})
            return httpx.Response(200, json={"status": "running"})
        body = json.loads(request.content)
        self.bodies.append(body)

        for reply in self._answer(body):
            if isinstance(reply, bytes):
                await self._redis.publish(RESULTS, reply)
            else:
                result = CodeResultData(
                    execution_id=body["execution_id"],
                    result_data=reply,
                    stderr="",
                    stdout="",
                    returncode=0,
                )
                await self._redis.publish(RESULTS, result.model_dump_json())

        return httpx.Response(202, json={"execution_id": body["execution_id"]})

    @property
    def submitted(self) -> dict:
        assert len(self.bodies) == 1, f"expected one submitted task, got {len(self.bodies)}"
        return self.bodies[0]


@pytest.fixture
def redis_server(monkeypatch):
    server = FakePubSubServer()
    monkeypatch.setattr(client_module.aioredis, "Redis", lambda **kwargs: FakeRedis(server))
    return server


@pytest.fixture
def sandbox_factory(redis_server, monkeypatch):
    """Installs a fake intake; returns the recorder for the tests to assert on."""

    def install(answer=lambda body: [body["code"]]) -> FakeSandbox:
        sandbox = FakeSandbox(FakeRedis(redis_server), answer)
        _route_http_to(monkeypatch, sandbox.handle)
        return sandbox

    return install


def _route_http_to(monkeypatch, handler) -> None:
    http_client_type = client_module.SandboxHttpClient
    monkeypatch.setattr(
        client_module,
        "SandboxHttpClient",
        lambda **kwargs: http_client_type(**kwargs, transport=httpx.MockTransport(handler)),
    )


@pytest.fixture
def sandbox(sandbox_factory) -> FakeSandbox:
    return sandbox_factory()


def _build_client(code_result_timeout: float | None = None) -> SandboxClient:
    return SandboxClient(
        host="unused",
        port=0,
        password=None,
        result_channel=RESULTS,
        sandbox_base_url=SANDBOX_BASE_URL,
        sandbox_timeout=5.0,
        # No retry budget: a full sandbox fails the first submit.
        queue_timeout=0,
        code_result_timeout=code_result_timeout,
    )


@pytest.fixture
async def client(sandbox):
    sandbox_client = _build_client()
    await sandbox_client.start()
    yield sandbox_client
    await sandbox_client.stop()


async def test_submitted_task_gets_a_fresh_execution_id_and_its_result(client, sandbox):
    result = await asyncio.wait_for(client.submit(_task("code-1")), timeout=2)

    assert sandbox.submitted["execution_id"] != "placeholder"
    assert sandbox.submitted["code"] == "code-1"
    assert (result.execution_id, result.result_data) == (
        sandbox.submitted["execution_id"],
        "code-1",
    )


async def test_storage_credentials_reach_the_intake(client, sandbox):
    credentials = StorageCredentials(access_key="AK-TEMP", secret_key="SK-TEMP")

    await asyncio.wait_for(client.submit(_storage_task(credentials)), timeout=2)

    assert sandbox.submitted["storage_credentials"] == {
        "access_key": "AK-TEMP",
        "secret_key": "SK-TEMP",
    }
    assert sandbox.submitted["use_storage"] is True
    assert sandbox.submitted["storage_allowed_paths"] == ["org_7/session_42/"]
    assert sandbox.submitted["storage_org_prefix"] == "org_7"


async def test_task_without_storage_submits_null_credentials(client, sandbox):
    await asyncio.wait_for(client.submit(_task()), timeout=2)

    assert sandbox.submitted["storage_credentials"] is None
    assert sandbox.submitted["use_storage"] is False


async def test_concurrent_submits_each_get_their_own_result(client):
    first, second = await asyncio.wait_for(
        asyncio.gather(client.submit(_task("code-1")), client.submit(_task("code-2"))), timeout=2
    )

    assert (first.result_data, second.result_data) == ("code-1", "code-2")


async def test_malformed_and_foreign_results_are_ignored(sandbox_factory):
    def answer(body):
        foreign = CodeResultData(
            execution_id="someone-else", result_data="foreign", stderr="", stdout="", returncode=0
        )
        return [b"not valid json {{{", foreign.model_dump_json().encode(), "mine"]

    sandbox_factory(answer)
    sandbox_client = _build_client()
    await sandbox_client.start()
    try:
        result = await asyncio.wait_for(sandbox_client.submit(_task()), timeout=2)
    finally:
        await sandbox_client.stop()

    assert result.result_data == "mine"


async def test_submit_gives_up_at_the_backstop_when_no_result_arrives(sandbox_factory):
    sandbox_factory(answer=lambda body: [])
    sandbox_client = _build_client(code_result_timeout=0.2)
    await sandbox_client.start()
    try:
        with pytest.raises(SandboxResultTimeoutError):
            await asyncio.wait_for(sandbox_client.submit(_task()), timeout=2)
    finally:
        await sandbox_client.stop()


async def test_submit_fails_when_the_sandbox_lost_the_execution(sandbox_factory, monkeypatch):
    monkeypatch.setattr(foundation_sandbox_module, "STATUS_POLL_INTERVAL_SECONDS", 0.01)
    sandbox = sandbox_factory(answer=lambda body: [])
    sandbox.loses_executions = True
    sandbox_client = _build_client()
    await sandbox_client.start()
    try:
        with pytest.raises(SandboxExecutionLostError):
            await asyncio.wait_for(sandbox_client.submit(_task()), timeout=2)
    finally:
        await sandbox_client.stop()


async def test_stop_fails_submits_still_waiting(sandbox_factory):
    sandbox = sandbox_factory(answer=lambda body: [])
    sandbox_client = _build_client()
    await sandbox_client.start()

    waiting = asyncio.create_task(sandbox_client.submit(_task()))
    while not sandbox.bodies:
        await asyncio.sleep(0.01)

    await sandbox_client.stop()

    with pytest.raises(ConnectionError, match="SandboxClient stopped"):
        await asyncio.wait_for(waiting, timeout=2)


@pytest.mark.parametrize(
    ("status_code", "headers", "text", "expected_error", "expected_message"),
    [
        (
            400,
            {},
            "use_storage requires storage_credentials",
            SandboxError,
            "use_storage requires storage_credentials",
        ),
        (
            503,
            {"Retry-After": "0"},
            "full",
            SandboxOverloadedError,
            "Sandbox overloaded: no free capacity within 0 s.",
        ),
    ],
    ids=["refused", "full"],
)
async def test_submit_raises_when_the_sandbox_does_not_take_the_task(
    redis_server, monkeypatch, status_code, headers, text, expected_error, expected_message
):
    _route_http_to(
        monkeypatch, lambda request: httpx.Response(status_code, headers=headers, text=text)
    )
    sandbox_client = _build_client()
    await sandbox_client.start()
    try:
        with pytest.raises(expected_error) as raised:
            await sandbox_client.submit(_task())
    finally:
        await sandbox_client.stop()

    assert str(raised.value) == expected_message
