"""`realtime` was the one publisher of the four (crew/agent/realtime/django
"Test run") that reached production carrying no storage-scoping fields at
all -- `run_code()` used to build `CodeTaskData` without
`storage_org_prefix`/`storage_allowed_paths`/`org_id`, so the storage_credentials
issuer would always fail closed for any `use_storage=True` task started from
a voice-agent code tool. Reading `python_code_executor_service.py` today
shows this is already fixed and `publish_credential_scope_async` is already
called; this is that fix's only test.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import infrastructure.messaging.python_code_executor_service as executor_module
from infrastructure.messaging.python_code_executor_service import (
    PythonCodeExecutorService,
)
from src.shared.models import CodeResultData, PythonCodeData


@pytest.fixture(autouse=True)
def _reset_singleton():
    """PythonCodeExecutorService is a process-wide singleton
    (utils/singleton_meta.py) -- reset it around every test so instantiating
    it with a fake redis_service doesn't leak into/from other test modules."""
    from utils.singleton_meta import SingletonMeta

    SingletonMeta._instances.pop(PythonCodeExecutorService, None)
    yield
    SingletonMeta._instances.pop(PythonCodeExecutorService, None)


class FakeRedisService:
    """Captures the published CodeTaskData and immediately satisfies
    run_code()'s response loop with a matching CodeResultData."""

    def __init__(self, call_order: list[str]):
        self.published: dict | None = None
        self.aioredis_client = object()
        self._call_order = call_order

        pubsub = MagicMock()
        pubsub.get_message = AsyncMock(side_effect=self._get_message)
        self._pubsub = pubsub
        self.async_subscribe = AsyncMock(return_value=pubsub)

    async def async_publish(self, channel: str, message: dict):
        self._call_order.append("async_publish")
        self.published = message

    async def _get_message(self, **kwargs):
        if self.published is None:
            return None
        return {
            "data": CodeResultData(
                execution_id=self.published["execution_id"],
                result_data="ok",
                stderr="",
                stdout="",
                returncode=0,
            ).model_dump_json()
        }


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


@pytest.mark.asyncio
async def test_use_storage_forwards_all_three_scoping_fields(monkeypatch):
    call_order: list[str] = []
    monkeypatch.setattr(
        executor_module,
        "publish_credential_scope_async",
        AsyncMock(side_effect=lambda *a, **kw: call_order.append("publish_scope")),
    )
    redis = FakeRedisService(call_order)
    service = PythonCodeExecutorService(redis_service=redis)

    python_code_data = make_python_code_data(
        use_storage=True,
        storage_org_prefix="org_1",
        storage_allowed_paths=["flowA"],
        org_id=1,
    )

    await asyncio.wait_for(
        service.run_code(python_code_data=python_code_data, inputs={}), timeout=5
    )

    assert redis.published is not None
    assert redis.published["use_storage"] is True
    assert redis.published["storage_org_prefix"] == "org_1"
    assert redis.published["storage_allowed_paths"] == ["flowA"]
    assert redis.published["org_id"] == 1


@pytest.mark.asyncio
async def test_publish_credential_scope_is_called_before_the_task_is_published(
    monkeypatch,
):
    call_order: list[str] = []
    monkeypatch.setattr(
        executor_module,
        "publish_credential_scope_async",
        AsyncMock(side_effect=lambda *a, **kw: call_order.append("publish_scope")),
    )
    redis = FakeRedisService(call_order)
    service = PythonCodeExecutorService(redis_service=redis)

    python_code_data = make_python_code_data(
        use_storage=True,
        storage_org_prefix="org_1",
        storage_allowed_paths=["flowA"],
        org_id=1,
    )

    await asyncio.wait_for(
        service.run_code(python_code_data=python_code_data, inputs={}), timeout=5
    )

    assert call_order == ["publish_scope", "async_publish"]


@pytest.mark.asyncio
async def test_invalid_storage_scope_returns_error_result():
    """When CodeTaskData creation fails (invalid storage scope),
    run_code() must return a structured error result instead of
    raising an exception. This prevents the tool executor from hanging."""
    redis = MagicMock()
    service = PythonCodeExecutorService(redis_service=redis)

    # Create invalid python_code_data that will fail CodeTaskData validation
    # (e.g., use_storage=True with storage_org_prefix=None)
    python_code_data = make_python_code_data(
        use_storage=True,
        storage_org_prefix=None,  # Invalid: use_storage=True requires org_prefix
        storage_allowed_paths=None,  # Invalid: use_storage=True requires allowed_paths
        org_id=None,  # Invalid: use_storage=True requires org_id
    )

    result = await asyncio.wait_for(
        service.run_code(python_code_data=python_code_data, inputs={}), timeout=5
    )

    assert isinstance(result, dict)
    assert result["returncode"] == 1
    assert "Invalid storage scope" in result["stderr"]
    assert result["stdout"] == ""
    # redis should not have been called (no publish)
    redis.async_subscribe.assert_not_called()
