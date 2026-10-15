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
async def test_run_code_injects_org_id_into_global_kwargs(executor, fake_redis_service):
    python_code_data = build_python_code_data(org_id=42)

    result = await executor.run_code(python_code_data, inputs={})

    task = published_task(fake_redis_service)
    assert task.global_kwargs["org_id"] == 42
    assert task.org_id == 42
    assert result["result_data"] == "ok"


@pytest.mark.asyncio
async def test_run_code_omits_org_id_global_when_org_id_is_none(
    executor, fake_redis_service
):
    python_code_data = build_python_code_data(org_id=None)

    await executor.run_code(python_code_data, inputs={})

    task = published_task(fake_redis_service)
    assert "org_id" not in task.global_kwargs
    assert task.org_id is None


@pytest.mark.asyncio
async def test_run_code_keeps_existing_globals_alongside_org_id(
    executor, fake_redis_service
):
    python_code_data = build_python_code_data(
        org_id=7, global_kwargs={"graph_id": 3, "api_key": "key"}
    )

    await executor.run_code(
        python_code_data,
        inputs={"query": "hello"},
        additional_global_kwargs={"session_id": 11},
    )

    task = published_task(fake_redis_service)
    assert task.global_kwargs == {
        "graph_id": 3,
        "api_key": "key",
        "session_id": 11,
        "org_id": 7,
    }
    assert task.func_kwargs == {"query": "hello"}


@pytest.mark.asyncio
async def test_run_code_org_id_overrides_caller_supplied_org_id_global(
    executor, fake_redis_service
):
    python_code_data = build_python_code_data(org_id=7, global_kwargs={"org_id": 999})

    await executor.run_code(
        python_code_data, inputs={}, additional_global_kwargs={"org_id": 998}
    )

    task = published_task(fake_redis_service)
    assert task.global_kwargs["org_id"] == 7
