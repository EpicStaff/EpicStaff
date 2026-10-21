import asyncio
import json
from collections import defaultdict

import pytest
import pytest_asyncio

import settings
from services.redis_service import AsyncPubsubSubscriber
from services.run_python_code_service import RunPythonCodeService
from src.shared.models import CodeResultData
from utils.singleton_meta import SingletonMeta

CODE_EXEC_CHANNEL = "code_exec_tasks"
SHARED_RESULT_CHANNEL = "code_results"
CREW_RESULT_CHANNEL = "code_results:crew"


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
    """Plays the sandbox: records every task crew publishes and answers on
    crew's result channel, either at once (`auto_reply`) or when told to."""

    def __init__(self, pubsub: InMemoryPubSub):
        self.pubsub = pubsub
        self.tasks: list[dict] = []
        self.auto_reply = False

    async def on_task(self, message: dict) -> None:
        task = json.loads(message["data"])
        self.tasks.append(task)
        if self.auto_reply:
            await self.reply(task["execution_id"], result_data="ok")

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
        raise AssertionError(f"crew published {len(self.tasks)} task(s), expected {count}")


@pytest.fixture(autouse=True)
def _reset_run_python_code_service():
    """RunPythonCodeService is a process-wide singleton; give every test its own."""
    SingletonMeta._instances.pop(RunPythonCodeService, None)
    yield
    SingletonMeta._instances.pop(RunPythonCodeService, None)


@pytest.fixture
def code_channels(monkeypatch):
    monkeypatch.setattr(settings, "CODE_EXEC_CHANNEL", CODE_EXEC_CHANNEL)
    monkeypatch.setattr(settings, "CODE_RESULT_CHUNNEL", SHARED_RESULT_CHANNEL)


@pytest.fixture
def pubsub(code_channels) -> InMemoryPubSub:
    return InMemoryPubSub()


@pytest_asyncio.fixture
async def sandbox(pubsub) -> FakeSandbox:
    fake_sandbox = FakeSandbox(pubsub)
    await pubsub.asubscribe(CODE_EXEC_CHANNEL, AsyncPubsubSubscriber(fake_sandbox.on_task))
    return fake_sandbox


@pytest_asyncio.fixture
async def run_python_code_service(pubsub) -> RunPythonCodeService:
    service = RunPythonCodeService(redis_service=pubsub)
    await service.subscribe_to_results()
    return service

