import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

import settings
from services.graph.events import StopEvent
from services.graph.exceptions import StopSession
from services.run_python_code_service import TIMEOUT_STDERR_MESSAGE, RunPythonCodeService
from src.shared.models import CodeResultData, PythonCodeData


@pytest.fixture(autouse=True)
def _reset_singleton():
    """RunPythonCodeService is a process-wide singleton (utils/singleton_meta.py).
    Reset it around every test so instantiating it with a fake redis_service
    doesn't leak into/from other test modules."""
    from utils.singleton_meta import SingletonMeta

    SingletonMeta._instances.pop(RunPythonCodeService, None)
    yield
    SingletonMeta._instances.pop(RunPythonCodeService, None)


@pytest.fixture
def short_timeout(monkeypatch):
    monkeypatch.setattr(settings, "CODE_RESULT_TIMEOUT", 0.05)
    return 0.05


class FakeRedisService:
    """Captures the published CodeTaskData; never delivers a result on its own."""

    def __init__(self):
        self.published = None
        self.asubscribe = AsyncMock()
        self.unsubscribe = MagicMock()

    async def apublish(self, channel: str, message: str):
        self.published = json.loads(message)


def make_python_code_data(**overrides) -> PythonCodeData:
    defaults = dict(
        venv_name="default",
        code="def main(**kw): return kw",
        entrypoint="main",
        libraries=[],
        global_kwargs={},
    )
    defaults.update(overrides)
    return PythonCodeData(**defaults)


async def _deliver_result(fake_redis: FakeRedisService) -> None:
    """Feeds a matching CodeResultData to the subscriber registered by run_code(),
    the same way a real code_results message would."""
    for _ in range(1000):
        if fake_redis.published is not None:
            break
        await asyncio.sleep(0)
    assert fake_redis.published is not None, "run_code() never published a task"

    subscriber = fake_redis.asubscribe.await_args.kwargs["subscriber"]
    await subscriber._callback(
        {
            "data": CodeResultData(
                execution_id=fake_redis.published["execution_id"],
                result_data="ok",
                stderr="",
                stdout="",
                returncode=0,
            ).model_dump_json()
        }
    )


@pytest.mark.asyncio
async def test_run_code_returns_timeout_result_when_no_result_arrives(short_timeout):
    fake_redis = FakeRedisService()
    service = RunPythonCodeService(redis_service=fake_redis)

    result = await asyncio.wait_for(
        service.run_code(python_code_data=make_python_code_data(), inputs={}),
        timeout=5,
    )

    assert result["returncode"] == 124
    assert result["result_data"] is None
    assert result["execution_id"] == fake_redis.published["execution_id"]
    assert result["stderr"] == TIMEOUT_STDERR_MESSAGE


@pytest.mark.asyncio
async def test_run_code_unsubscribes_exactly_once_on_timeout(short_timeout):
    fake_redis = FakeRedisService()
    service = RunPythonCodeService(redis_service=fake_redis)

    await asyncio.wait_for(
        service.run_code(python_code_data=make_python_code_data(), inputs={}),
        timeout=5,
    )

    assert fake_redis.unsubscribe.call_count == 1
    assert fake_redis.unsubscribe.call_args.kwargs["subscriber"] is fake_redis.asubscribe.await_args.kwargs["subscriber"]


@pytest.mark.asyncio
async def test_run_code_unsubscribes_when_stop_event_aborts_the_wait(short_timeout):
    fake_redis = FakeRedisService()
    service = RunPythonCodeService(redis_service=fake_redis)

    stop_event = StopEvent()
    stop_event.set()

    with pytest.raises(StopSession):
        await asyncio.wait_for(
            service.run_code(
                python_code_data=make_python_code_data(),
                inputs={},
                stop_event=stop_event,
            ),
            timeout=5,
        )

    assert fake_redis.unsubscribe.call_count == 1


@pytest.mark.asyncio
async def test_run_code_returns_the_sandbox_result_and_unsubscribes_once():
    fake_redis = FakeRedisService()
    service = RunPythonCodeService(redis_service=fake_redis)

    task = asyncio.ensure_future(service.run_code(python_code_data=make_python_code_data(), inputs={}))
    await _deliver_result(fake_redis)
    result = await asyncio.wait_for(task, timeout=5)

    assert result["returncode"] == 0
    assert result["result_data"] == "ok"
    assert fake_redis.unsubscribe.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("execution_timeout", [42, None], ids=["code-timeout", "no-timeout"])
async def test_run_code_publishes_the_code_execution_timeout(execution_timeout):
    """The code's own execution timeout reaches the sandbox unchanged; None lets the
    sandbox apply SANDBOX_DEFAULT_EXECUTION_TIMEOUT."""
    fake_redis = FakeRedisService()
    service = RunPythonCodeService(redis_service=fake_redis)

    task = asyncio.ensure_future(
        service.run_code(
            python_code_data=make_python_code_data(execution_timeout=execution_timeout),
            inputs={},
        )
    )
    await _deliver_result(fake_redis)
    await asyncio.wait_for(task, timeout=5)

    assert fake_redis.published["timeout"] == execution_timeout
