import pytest

from core import config
from domain.ports.i_redis_messaging_service import IRedisMessagingService
from infrastructure.messaging.python_code_executor_service import (
    PythonCodeExecutorService,
)
from src.shared.models import CodeResultData, CodeTaskData, PythonCodeData
from utils.singleton_meta import SingletonMeta


class FakePubSub:
    def __init__(self, redis_service: "FakeRedisMessagingService"):
        self._redis_service = redis_service

    async def get_message(self, ignore_subscribe_messages: bool, timeout: float):
        # run_code publishes before it polls; failing here beats an endless poll loop.
        assert self._redis_service.published, "run_code polled without publishing a task"
        _, task_payload = self._redis_service.published[-1]
        result = CodeResultData(
            execution_id=task_payload["execution_id"],
            result_data="ok",
            stderr="",
            stdout="",
        )
        return {"data": result.model_dump_json()}


class FakeRedisMessagingService(IRedisMessagingService):
    """Records published sandbox tasks and answers each with a matching result."""

    def __init__(self):
        self.published: list[tuple[str, dict]] = []
        self.subscribed_channels: list[str] = []

    async def async_subscribe(self, channel: str):
        self.subscribed_channels.append(channel)
        return FakePubSub(self)

    async def async_publish(self, channel: str, message: object) -> None:
        self.published.append((channel, message))


@pytest.fixture(autouse=True)
def reset_singleton():
    """Drop only this service's instance; clearing the whole dict would orphan
    module-level singletons that `api.main` holds (see test_voice_stream_handler)."""
    SingletonMeta._instances.pop(PythonCodeExecutorService, None)
    yield
    SingletonMeta._instances.pop(PythonCodeExecutorService, None)


@pytest.fixture
def fake_redis_service():
    yield FakeRedisMessagingService()


@pytest.fixture
def executor(fake_redis_service):
    yield PythonCodeExecutorService(fake_redis_service)


def build_python_code_data(**overrides) -> PythonCodeData:
    fields = {
        "venv_name": "default",
        "code": "def main(): return 'ok'",
        "entrypoint": "main",
        "libraries": [],
    }
    fields.update(overrides)
    return PythonCodeData(**fields)


def published_task(fake_redis_service: FakeRedisMessagingService) -> CodeTaskData:
    assert len(fake_redis_service.published) == 1
    channel, payload = fake_redis_service.published[0]
    assert channel == config.CODE_EXEC_CHANNEL
    return CodeTaskData.model_validate(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("org_id", "code_globals", "caller_globals", "expected_globals"),
    [
        (42, {}, None, {"org_id": 42}),
        (None, {}, None, {}),
        (7, {"graph_id": 3, "api_key": "key"}, {"session_id": 11}, {"graph_id": 3, "api_key": "key", "session_id": 11, "org_id": 7}),
        # The resolved org always wins: tools send it as X-Organization-Id to Django.
        (7, {"org_id": 999}, {"org_id": 998}, {"org_id": 7}),
    ],
    ids=["org", "no-org", "kept-globals", "org-cannot-be-spoofed"],
)
async def test_code_task_carries_the_org_into_the_sandbox(
    executor, fake_redis_service, org_id, code_globals, caller_globals, expected_globals
):
    python_code_data = build_python_code_data(org_id=org_id, global_kwargs=code_globals)

    result = await executor.run_code(python_code_data, inputs={"query": "hello"}, additional_global_kwargs=caller_globals)

    task = published_task(fake_redis_service)
    assert (task.global_kwargs, task.org_id, task.func_kwargs) == (expected_globals, org_id, {"query": "hello"})
    assert result["result_data"] == "ok"
