"""`realtime` was the one publisher of the four (crew/agent/realtime/django
"Test run") that reached production carrying no storage-scoping fields at
all -- `run_code()` used to build `CodeTaskData` without scoping fields.

Storage credentials 2.0 (EST-3892): django now mints temporary storage
credentials once per realtime chat session (in
`converter_service.convert_rt_agent_definition_chat_to_pydantic`) and hands
them to this service as the `storage_credentials` parameter. This service
never mints or requests credentials itself, only forwards what it receives
to `CodeTaskData.storage_credentials`.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from infrastructure.messaging.python_code_executor_service import (
    PythonCodeExecutorService,
)
from src.shared.models import CodeResultData, PythonCodeData, StorageCredentials


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
    redis = FakeRedisService(call_order)
    service = PythonCodeExecutorService(redis_service=redis)

    python_code_data = make_python_code_data(
        use_storage=True,
        storage_org_prefix="org_1",
        storage_allowed_paths=["flowA"],
        org_id=1,
    )

    await asyncio.wait_for(
        service.run_code(
            python_code_data=python_code_data,
            inputs={},
            storage_credentials=StorageCredentials(access_key="AK123", secret_key="SK456"),
        ),
        timeout=5,
    )

    assert redis.published is not None
    assert redis.published["use_storage"] is True
    assert redis.published["storage_org_prefix"] == "org_1"
    assert redis.published["storage_allowed_paths"] == ["flowA"]
    assert redis.published["org_id"] == 1


@pytest.mark.asyncio
async def test_storage_credentials_parameter_is_forwarded_onto_code_task_data():
    """The service must never mint or request credentials itself -- it only
    copies whatever `storage_credentials` it is handed onto the published
    `CodeTaskData`, exactly as `tool_manager_service` passes
    `rt_agent_chat_data.storage_credentials` through."""
    call_order: list[str] = []
    redis = FakeRedisService(call_order)
    service = PythonCodeExecutorService(redis_service=redis)

    python_code_data = make_python_code_data(
        use_storage=True,
        storage_org_prefix="org_1",
        storage_allowed_paths=["flowA"],
        org_id=1,
    )
    creds = StorageCredentials(access_key="AK123", secret_key="SK456")

    await asyncio.wait_for(
        service.run_code(
            python_code_data=python_code_data,
            inputs={},
            storage_credentials=creds,
        ),
        timeout=5,
    )

    assert redis.published is not None
    assert redis.published["storage_credentials"] == {
        "access_key": "AK123",
        "secret_key": "SK456",
    }


@pytest.mark.asyncio
async def test_no_storage_credentials_means_none_on_code_task_data():
    call_order: list[str] = []
    redis = FakeRedisService(call_order)
    service = PythonCodeExecutorService(redis_service=redis)

    python_code_data = make_python_code_data(use_storage=False)

    await asyncio.wait_for(
        service.run_code(python_code_data=python_code_data, inputs={}), timeout=5
    )

    assert redis.published is not None
    assert redis.published["storage_credentials"] is None


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
