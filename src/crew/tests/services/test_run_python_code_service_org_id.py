"""
EST-3285: org_id must be forced into global_kwargs (and carried on the typed
CodeTaskData field) so sandboxed callback tools (fanout_tool, subflow_tool,
schedule_manager_tool) can read `globals()["org_id"]` and send
X-Organization-Id to org-scoped Django endpoints. org_id is resolved
server-side (Graph.org_id, via converter_service) and must always win over a
same-named agent/tool-config value in additional_global_kwargs -- mirrors the
"session_id always wins" treatment in crew_node.py.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.run_python_code_service import RunPythonCodeService
from src.shared.models import PythonCodeData


@pytest.fixture(autouse=True)
def _reset_singleton():
    """RunPythonCodeService is a process-wide singleton (utils/singleton_meta.py).
    Reset it around every test so instantiating it with a fake redis_service
    doesn't leak into/from other test modules."""
    from utils.singleton_meta import SingletonMeta

    SingletonMeta._instances.pop(RunPythonCodeService, None)
    yield
    SingletonMeta._instances.pop(RunPythonCodeService, None)


class FakeRedisService:
    """Captures the published CodeTaskData and immediately satisfies the
    callback so run_code() doesn't block on a real redis round-trip."""

    def __init__(self):
        self.published = None
        self.asubscribe = AsyncMock()
        self.unsubscribe = MagicMock()
        # run_code() reads this to log the current subscriber count.
        self._async_pubsub_groups = {}

    async def apublish(self, channel: str, message: dict):
        self.published = message


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


async def _run_and_capture(
    service: RunPythonCodeService, redis: FakeRedisService, **run_code_kwargs
):
    """Runs run_code() and, once the task is published, injects a matching
    CodeResultData so the internal wait loop exits immediately."""
    task = asyncio.ensure_future(service.run_code(**run_code_kwargs))
    for _ in range(1000):
        if redis.published is not None:
            break
        await asyncio.sleep(0)
    assert redis.published is not None, "run_code() never published a task"

    from src.shared.models import CodeResultData

    execution_id = redis.published["execution_id"]
    # Directly fulfil the callback receiver the same way a real code_results
    # message would, bypassing the actual redis round-trip. asubscribe()
    # receives an AsyncPubsubSubscriber wrapping the bound
    # RunPythonCallbackReceiver.callback method as `_callback`.
    subscriber = (
        redis.asubscribe.await_args.kwargs.get("subscriber")
        or redis.asubscribe.await_args.args[-1]
    )
    await subscriber._callback(
        {
            "data": CodeResultData(
                execution_id=execution_id,
                result_data="ok",
                stderr="",
                stdout="",
                returncode=0,
            ).model_dump_json()
        }
    )
    return await task


@pytest.mark.asyncio
async def test_run_code_forces_org_id_into_global_kwargs_and_wins_over_additional():
    redis = FakeRedisService()
    service = RunPythonCodeService(redis_service=redis)

    python_code_data = make_python_code_data(global_kwargs={"foo": "bar"}, org_id=77)

    await _run_and_capture(
        service,
        redis,
        python_code_data=python_code_data,
        inputs={},
        additional_global_kwargs={"org_id": "agent-spoofed-value"},
    )

    assert redis.published["global_kwargs"]["org_id"] == 77
    assert redis.published["global_kwargs"]["foo"] == "bar"
    assert redis.published["org_id"] == 77


@pytest.mark.asyncio
async def test_run_code_omits_org_id_when_not_set():
    redis = FakeRedisService()
    service = RunPythonCodeService(redis_service=redis)

    python_code_data = make_python_code_data(global_kwargs={"foo": "bar"})

    await _run_and_capture(
        service,
        redis,
        python_code_data=python_code_data,
        inputs={},
        additional_global_kwargs={},
    )

    assert "org_id" not in redis.published["global_kwargs"]
    assert redis.published["org_id"] is None
