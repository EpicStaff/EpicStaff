"""RunPythonCodeService sends the code's own execution timeout to the sandbox.

Invariant: `run_code` publishes `PythonCodeData.execution_timeout` (seconds) as
`CodeTaskData.timeout` unchanged; a code without a timeout (None) publishes None, so the
sandbox applies its SANDBOX_DEFAULT_EXECUTION_TIMEOUT.

Only Redis is faked (`FakeRedisService`); the service and the shared models are real.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.run_python_code_service import RunPythonCodeService
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


async def _run_and_capture(redis: FakeRedisService, python_code_data: PythonCodeData) -> dict:
    """Run run_code() and answer its published task, returning the published task."""
    service = RunPythonCodeService(redis_service=redis)
    task = asyncio.ensure_future(service.run_code(python_code_data=python_code_data, inputs={}))
    for _ in range(1000):
        if redis.published is not None:
            break
        await asyncio.sleep(0)
    assert redis.published is not None, "run_code() never published a task"

    subscriber = (
        redis.asubscribe.await_args.kwargs.get("subscriber") or redis.asubscribe.await_args.args[-1]
    )
    await subscriber._callback(
        {
            "data": CodeResultData(
                execution_id=redis.published["execution_id"],
                result_data="1",
                stderr="",
                stdout="",
                returncode=0,
            ).model_dump_json()
        }
    )
    await task
    return redis.published


@pytest.mark.asyncio
@pytest.mark.parametrize("execution_timeout", [42, None], ids=["code-timeout", "no-timeout"])
async def test_run_code_publishes_the_code_execution_timeout(execution_timeout):
    python_code_data = PythonCodeData(
        venv_name="default",
        code="def main(**kwargs): return 1",
        entrypoint="main",
        libraries=[],
        execution_timeout=execution_timeout,
    )

    published = await _run_and_capture(FakeRedisService(), python_code_data)

    assert published["timeout"] == execution_timeout
