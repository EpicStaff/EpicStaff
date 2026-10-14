"""RunPythonCodeService carries the execution timeout to the sandbox and the
timeout outcome back to the node.

Invariant: a node's timeout in minutes becomes seconds (None stays None, so the
sandbox applies its ceiling); `run_code(timeout=...)` publishes it as
`CodeTaskData.timeout`; and a `code_results` message reporting a kill hands
`timed_out` and `effective_timeout_seconds` back unchanged, so the node can tell a
timeout apart from an ordinary failure.

Only Redis is faked (`FakeRedisService`); the service and the shared models are real.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.run_python_code_service import (
    RunPythonCodeService,
    execution_timeout_seconds,
)
from src.shared.models import CodeResultData, PythonCodeData


@pytest.fixture(autouse=True)
def _reset_singleton():
    from utils.singleton_meta import SingletonMeta

    SingletonMeta._instances.pop(RunPythonCodeService, None)
    yield
    SingletonMeta._instances.pop(RunPythonCodeService, None)


class FakeRedisService:
    def __init__(self):
        self.published = None
        self.asubscribe = AsyncMock()
        self.unsubscribe = MagicMock()
        self._async_pubsub_groups = {}

    async def apublish(self, channel: str, message: str):
        self.published = json.loads(message)


def _python_code_data() -> PythonCodeData:
    return PythonCodeData(
        venv_name="default", code="def main(**kw): return kw", entrypoint="main", libraries=[]
    )


async def _run_and_answer(redis: FakeRedisService, answer: dict, **run_code_kwargs) -> dict:
    """Run run_code() and answer its published task with `answer` fields."""
    service = RunPythonCodeService(redis_service=redis)
    task = asyncio.ensure_future(
        service.run_code(python_code_data=_python_code_data(), inputs={}, **run_code_kwargs)
    )
    for _ in range(1000):
        if redis.published is not None:
            break
        await asyncio.sleep(0)
    assert redis.published is not None, "run_code() never published a task"

    subscriber = (
        redis.asubscribe.await_args.kwargs.get("subscriber")
        or redis.asubscribe.await_args.args[-1]
    )
    await subscriber._callback(
        {
            "data": CodeResultData(
                execution_id=redis.published["execution_id"], stderr="", stdout="", **answer
            ).model_dump_json()
        }
    )
    return await task


@pytest.mark.parametrize(
    ("minutes", "seconds"), [(1, 60), (5, 300), (None, None)], ids=["one", "five", "unset"]
)
def test_execution_timeout_seconds_converts_minutes(minutes, seconds):
    assert execution_timeout_seconds(minutes) == seconds


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [180, None], ids=["node-timeout", "sandbox-ceiling"])
async def test_run_code_publishes_the_requested_timeout(timeout):
    redis = FakeRedisService()

    await _run_and_answer(redis, {"returncode": 0, "result_data": "1"}, timeout=timeout)

    assert redis.published["timeout"] == timeout


@pytest.mark.asyncio
async def test_run_code_returns_the_timeout_outcome_from_the_sandbox():
    redis = FakeRedisService()

    result = await _run_and_answer(
        redis,
        {"returncode": 124, "timed_out": True, "effective_timeout_seconds": 60.0},
        timeout=600,
    )

    assert result["returncode"] == 124
    assert result["timed_out"] is True
    assert result["effective_timeout_seconds"] == 60.0
