"""SandboxClient: submits code tasks to sandbox_new over HTTP and matches results by execution id.

The intake is a real httpx client over a MockTransport, so a test sees the JSON
body the agent actually posts to `POST /executions`. Results still come back on
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
from app.sandbox.http_client import ClientValidationError
from app.tools.executors.python_code import PythonCodeToolExecutor
from shared.models.storage_scope import StorageCredentials
from shared.models.tools import CodeResultData, CodeTaskData
from tests.log_capture import assert_masked_exception, capture_logs_at, log_line_starting_with
from tests.tools.test_python_code_executor import _make_tool_data

RESULTS = "code_results"
SANDBOX_BASE_URL = "http://sandbox:8000"
PARSE_FAILURE_PREFIX = "SandboxClient: failed to parse pubsub message:"
READER_FAILURE_PREFIX = "SandboxClient reader loop failed:"


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
    """

    def __init__(self, redis: FakeRedis, answer=lambda body: [body["code"]]):
        self._redis = redis
        self._answer = answer
        self.bodies: list[dict] = []

    async def handle(self, request: httpx.Request) -> httpx.Response:
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
        http_client_type = client_module.AsyncClient
        monkeypatch.setattr(
            client_module,
            "AsyncClient",
            lambda **kwargs: http_client_type(
                **kwargs, transport=httpx.MockTransport(sandbox.handle)
            ),
        )
        return sandbox

    return install


@pytest.fixture
def sandbox(sandbox_factory) -> FakeSandbox:
    return sandbox_factory()


def _build_client() -> SandboxClient:
    return SandboxClient(
        host="unused",
        port=0,
        password=None,
        result_channel=RESULTS,
        sandbox_base_url=SANDBOX_BASE_URL,
        sandbox_timeout=5.0,
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


async def test_submit_times_out_when_the_sandbox_never_answers(sandbox_factory):
    sandbox_factory(answer=lambda body: [])
    sandbox_client = _build_client()
    await sandbox_client.start()
    try:
        with pytest.raises(asyncio.TimeoutError):
            await sandbox_client.submit(_task(), timeout=0.2)
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


async def test_submit_raises_when_the_intake_rejects_the_task(redis_server, monkeypatch):
    def reject(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="use_storage requires storage_credentials")

    http_client_type = client_module.AsyncClient
    monkeypatch.setattr(
        client_module,
        "AsyncClient",
        lambda **kwargs: http_client_type(**kwargs, transport=httpx.MockTransport(reject)),
    )
    sandbox_client = _build_client()
    await sandbox_client.start()
    try:
        with pytest.raises(ClientValidationError, match="use_storage requires storage_credentials"):
            await sandbox_client.submit(_task())
    finally:
        await sandbox_client.stop()


async def test_unparseable_result_logs_validation_types_and_locations_only(sandbox_factory):
    """A result that fails CodeResultData validation reaches pydantic's own rendering
    verbatim, so the WARNING line must carry only the failure type and its location."""
    marker = "SENSITIVE_SANDBOX_RESULT_MARKER_31415"

    def answer(body):
        rejected = json.dumps(
            {
                "execution_id": body["execution_id"],
                "result_data": {"leaked": marker},
                "stderr": "",
                "stdout": "",
            }
        ).encode()
        return [rejected, "mine"]

    sandbox_factory(answer)
    sandbox_client = _build_client()
    await sandbox_client.start()
    with capture_logs_at("WARNING") as logs:
        try:
            result = await asyncio.wait_for(sandbox_client.submit(_task()), timeout=2)
        finally:
            await sandbox_client.stop()

    warning = log_line_starting_with(logs, PARSE_FAILURE_PREFIX)
    assert marker not in warning
    assert "validation=ValidationError" in warning
    assert "1 error(s)" in warning
    assert "at result_data" in warning
    assert result.result_data == "mine"


async def test_undecodable_result_kills_the_reader_loop_and_logs_digest_only(sandbox_factory):
    """A payload that is not UTF-8 fails outside the per-message try block (decoding
    happens before it), so it kills the reader loop the same way any other transport
    failure does; the ERROR line names the exception class and digests its message."""
    sandbox_factory(answer=lambda body: [b"\xff\xfe not utf-8"])
    sandbox_client = _build_client()
    await sandbox_client.start()
    with capture_logs_at("ERROR") as logs:
        try:
            with pytest.raises(ConnectionError):
                await asyncio.wait_for(sandbox_client.submit(_task()), timeout=2)
        finally:
            await sandbox_client.stop()

    error_line = log_line_starting_with(logs, READER_FAILURE_PREFIX)
    assert_masked_exception(error_line, "UnicodeDecodeError")


_EXPLODE = b"__explode_the_reader_loop__"
READER_MARKER = "SENSITIVE_TRANSPORT_FAILURE_MARKER_27182"


class ExplodingPubSub(FakePubSub):
    """Delivers messages until the explode sentinel arrives, then fails the subscription."""

    async def listen(self):
        while True:
            message = await self._queue.get()
            if message.get("data") == _EXPLODE:
                raise RuntimeError(f"pubsub subscription broke: {READER_MARKER}")
            yield message


class ExplodingRedis(FakeRedis):
    def pubsub(self) -> ExplodingPubSub:
        return ExplodingPubSub(self._server)


@pytest.fixture
def exploding_sandbox(monkeypatch) -> FakeSandbox:
    """A sandbox whose answer kills the reader loop while a submit is still pending."""
    server = FakePubSubServer()
    monkeypatch.setattr(client_module.aioredis, "Redis", lambda **kwargs: ExplodingRedis(server))
    sandbox = FakeSandbox(ExplodingRedis(server), answer=lambda body: [_EXPLODE])
    http_client_type = client_module.AsyncClient
    monkeypatch.setattr(
        client_module,
        "AsyncClient",
        lambda **kwargs: http_client_type(**kwargs, transport=httpx.MockTransport(sandbox.handle)),
    )
    return sandbox


async def test_reader_loop_failure_logs_the_class_name_and_a_digest_only(exploding_sandbox):
    sandbox_client = _build_client()
    await sandbox_client.start()
    with capture_logs_at("ERROR") as logs:
        try:
            with pytest.raises(ConnectionError):
                await asyncio.wait_for(sandbox_client.submit(_task()), timeout=2)
        finally:
            await sandbox_client.stop()

    error_line = log_line_starting_with(logs, READER_FAILURE_PREFIX)
    assert READER_MARKER not in error_line
    assert_masked_exception(error_line, "RuntimeError")


async def test_reader_loop_failure_reaches_the_agent_as_an_unredacted_tool_result(
    exploding_sandbox,
):
    """Only the log line is redacted: the ConnectionError text still carries the cause,
    and the executor passes it to the agent as ToolResult.content."""
    sandbox_client = _build_client()
    await sandbox_client.start()
    executor = PythonCodeToolExecutor(sandbox_client, _make_tool_data())
    try:
        tool_result = await asyncio.wait_for(executor({"x": "1"}), timeout=2)
    finally:
        await sandbox_client.stop()

    assert tool_result.is_error is True
    assert tool_result.content == (
        f"Sandbox transport error: SandboxClient reader loop failed: "
        f"pubsub subscription broke: {READER_MARKER}"
    )
