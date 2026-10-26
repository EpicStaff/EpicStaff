"""Doubles shared by the RunPythonCodeService tests.

crew submits an execution to sandbox_new over HTTP and reads the result back from
its own Redis channel, so the harness is split the same way: a real SandboxClient
over an httpx MockTransport records the JSON body crew actually submits, and an
in-memory pub/sub carries the sandbox's result back to the one subscription
`subscribe_to_results` makes.
"""

import asyncio
import json
from collections import defaultdict
from typing import Any

import httpx
import pytest
import pytest_asyncio
from loguru import logger

import settings
from foundation.clients.sandbox import SandboxClient
from services.redis_service import AsyncPubsubSubscriber
from services.run_python_code_service import RunPythonCodeService
from src.shared.bench_log import BENCH_LEVEL
from src.shared.models import CodeResultData, PythonCodeData
from utils.singleton_meta import SingletonMeta

SHARED_RESULT_CHANNEL = "code_results"
CREW_RESULT_CHANNEL = "code_results:crew"
SANDBOX_BASE_URL = "http://sandbox:8000"
REJECTED_RETRY_AFTER_S = 0.05


class InMemoryPubSub:
    """Stands in for crew's RedisService pub/sub: a publish reaches every
    subscriber of that channel, with the message shape AsyncPubSubGroup delivers."""

    def __init__(self):
        self.subscribers: dict[str, list[AsyncPubsubSubscriber]] = defaultdict(list)

    async def asubscribe(self, channels: str, subscriber: AsyncPubsubSubscriber) -> None:
        self.subscribers[channels].append(subscriber)

    async def apublish(self, channel: str, message: dict | str) -> None:
        data = message if isinstance(message, str) else json.dumps(message)
        for subscriber in list(self.subscribers[channel]):
            await subscriber.update({"type": "message", "channel": channel, "data": data})


class FakeSandbox:
    """Plays sandbox_new's HTTP API: records the body of every execution crew submits,
    answers on crew's result channel, either at once (`auto_reply`) or when told to,
    and reports each submitted execution as running on `GET /executions/{id}`.

    Setting `rejects_with` makes every submit answer 400 with that text, the way
    sandbox_new refuses an execution it will not run; `full` makes it answer 503,
    the way a sandbox at capacity does, and `rejections_left` does so for that many
    submits only, each asking for a `REJECTED_RETRY_AFTER_S` wait; `unreachable` fails
    every request before it gets an answer; `loses_executions` answers every status
    check with 404, the way a sandbox that restarted does.
    """

    def __init__(self, pubsub: InMemoryPubSub):
        self.pubsub = pubsub
        self.tasks: list[dict] = []
        self.auto_reply = False
        self.rejects_with: str | None = None
        self.full = False
        self.rejections_left = 0
        self.unreachable = False
        self.loses_executions = False

    async def handle(self, request: httpx.Request) -> httpx.Response:
        if self.unreachable:
            raise httpx.ConnectError("connection refused", request=request)
        if request.method == "GET":
            if self.loses_executions:
                return httpx.Response(404, json={"detail": "not found"})
            return httpx.Response(200, json={"status": "running"})
        task = json.loads(request.content)
        self.tasks.append(task)
        if self.rejects_with is not None:
            return httpx.Response(400, text=self.rejects_with)
        if self.full:
            return httpx.Response(503, headers={"Retry-After": "0"}, json={"detail": "full"})
        if self.rejections_left > 0:
            self.rejections_left -= 1
            return httpx.Response(
                503,
                headers={"Retry-After": str(REJECTED_RETRY_AFTER_S)},
                json={"detail": "full"},
            )
        if self.auto_reply:
            await self.reply(task["execution_id"], result_data="ok")
        return httpx.Response(202, json={"status": "accepted"})

    @property
    def submitted(self) -> dict[str, Any]:
        """The one execution submitted so far."""
        assert len(self.tasks) == 1, f"expected one submitted execution, got {len(self.tasks)}"
        return self.tasks[0]

    async def reply(self, execution_id: str, result_data: str) -> None:
        await self.pubsub.apublish(
            CREW_RESULT_CHANNEL,
            CodeResultData(
                execution_id=execution_id,
                result_data=result_data,
                stderr="",
                stdout="",
                returncode=0,
            ).model_dump_json(),
        )

    async def wait_for_tasks(self, count: int) -> list[dict]:
        for _ in range(1000):
            if len(self.tasks) >= count:
                return self.tasks
            await asyncio.sleep(0)
        raise AssertionError(f"crew submitted {len(self.tasks)} execution(s), expected {count}")


@pytest.fixture
def checkpoints():
    """The BENCH checkpoints logged during the test, as their extra fields, in order."""
    logged: list[dict] = []
    sink_id = logger.add(
        lambda message: logged.append(dict(message.record["extra"])),
        level=BENCH_LEVEL,
        filter=lambda record: record["level"].no == BENCH_LEVEL,
    )
    yield logged
    logger.remove(sink_id)


@pytest.fixture(autouse=True)
def _reset_run_python_code_service():
    """RunPythonCodeService is a process-wide singleton; give every test its own."""
    SingletonMeta._instances.pop(RunPythonCodeService, None)
    yield
    SingletonMeta._instances.pop(RunPythonCodeService, None)


@pytest.fixture
def code_channels(monkeypatch):
    monkeypatch.setattr(settings, "CODE_RESULT_CHUNNEL", SHARED_RESULT_CHANNEL)


@pytest.fixture
def pubsub(code_channels) -> InMemoryPubSub:
    return InMemoryPubSub()


@pytest.fixture
def sandbox(pubsub) -> FakeSandbox:
    return FakeSandbox(pubsub)


@pytest.fixture
def sandbox_client(sandbox: FakeSandbox) -> SandboxClient:
    # No retry budget: a full or unreachable sandbox fails the first submit.
    return SandboxClient(
        queue_timeout=0,
        base_url=SANDBOX_BASE_URL,
        transport=httpx.MockTransport(sandbox.handle),
    )


@pytest_asyncio.fixture
async def run_python_code_service(pubsub, sandbox_client) -> RunPythonCodeService:
    service = RunPythonCodeService(redis_service=pubsub, sandbox_client=sandbox_client)
    await service.subscribe_to_results()
    return service


@pytest.fixture
def make_python_code_data():
    def make(**overrides) -> PythonCodeData:
        defaults = dict(
            code="def main(**kw): return kw",
            entrypoint="main",
            global_kwargs={},
        )
        defaults.update(overrides)
        return PythonCodeData(**defaults)

    return make


@pytest.fixture
def run_code(run_python_code_service, sandbox: FakeSandbox):
    """Run run_code() and answer the submitted execution with a successful result."""

    async def run(result_data: str = "ok", **run_code_kwargs) -> dict[str, Any]:
        running = asyncio.ensure_future(run_python_code_service.run_code(**run_code_kwargs))
        [task] = await sandbox.wait_for_tasks(1)
        await sandbox.reply(task["execution_id"], result_data=result_data)
        return await asyncio.wait_for(running, timeout=5)

    return run
