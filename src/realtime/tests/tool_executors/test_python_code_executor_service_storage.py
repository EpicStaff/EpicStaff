"""`realtime` was the one publisher of the four (crew/agent/realtime/django
"Test run") that reached production carrying no storage-scoping fields at
all -- `run_code()` used to build `CodeTaskData` without scoping fields.

Temporary storage credentials: django mints temporary storage credentials
once per realtime chat session (in
`converter_service.convert_rt_agent_definition_chat_to_pydantic`) and hands
them to this service as the `storage_credentials` parameter. This service
never mints or requests credentials itself, only forwards what it receives
onto the sandbox submission -- which the sandbox refuses when `use_storage`
is set and they are missing.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from infrastructure.messaging.python_code_executor_service import (
    PythonCodeExecutorService,
)
from src.shared.models import CodeResultData, PythonCodeData, StorageCredentials
from tests.fixtures import RecordingSandboxIntake


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
    """Satisfies run_code()'s response loop with a result matching the task the
    sandbox intake received."""

    def __init__(self, intake: RecordingSandboxIntake):
        self._intake = intake
        self.aioredis_client = object()

        pubsub = MagicMock()
        pubsub.get_message = AsyncMock(side_effect=self._get_message)
        pubsub.aclose = AsyncMock()
        self._pubsub = pubsub
        self.async_subscribe = AsyncMock(return_value=pubsub)

    async def async_publish(self, channel: str, message: dict):
        raise AssertionError("code executions no longer go over Redis pub/sub")

    async def _get_message(self, **kwargs):
        if not self._intake.bodies:
            return None
        return {
            "data": CodeResultData(
                execution_id=self._intake.bodies[-1]["execution_id"],
                result_data="ok",
                stderr="",
                stdout="",
                returncode=0,
            ).model_dump_json()
        }


@pytest.fixture
def service(sandbox_intake):
    return PythonCodeExecutorService(
        redis_service=FakeRedisService(sandbox_intake),
        sandbox_client=sandbox_intake.client(),
    )


def make_python_code_data(**overrides) -> PythonCodeData:
    defaults = dict(
        code="def main(**kw): return kw",
        entrypoint="main",
        global_kwargs={},
    )
    defaults.update(overrides)
    return PythonCodeData(**defaults)


@pytest.mark.asyncio
async def test_use_storage_forwards_all_three_scoping_fields(service, sandbox_intake):
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

    (submitted,) = sandbox_intake.bodies
    assert submitted["use_storage"] is True
    assert submitted["storage_org_prefix"] == "org_1"
    assert submitted["storage_allowed_paths"] == ["flowA"]
    # org_id is not a field of the submission; it reaches the code as a global.
    assert submitted["global_kwargs"]["org_id"] == 1


@pytest.mark.asyncio
async def test_storage_credentials_parameter_is_forwarded_onto_the_submission(
    service, sandbox_intake
):
    """The service must never mint or request credentials itself -- it only
    copies whatever `storage_credentials` it is handed onto the submission,
    exactly as `tool_manager_service` passes
    `rt_agent_chat_data.storage_credentials` through."""
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

    (submitted,) = sandbox_intake.bodies
    assert submitted["storage_credentials"] == {
        "access_key": "AK123",
        "secret_key": "SK456",
    }


@pytest.mark.asyncio
async def test_no_storage_credentials_means_none_on_the_submission(service, sandbox_intake):
    await asyncio.wait_for(
        service.run_code(python_code_data=make_python_code_data(use_storage=False), inputs={}),
        timeout=5,
    )

    (submitted,) = sandbox_intake.bodies
    assert submitted["storage_credentials"] is None


@pytest.mark.asyncio
async def test_invalid_storage_scope_returns_error_result(sandbox_intake):
    """When CodeTaskData creation fails (invalid storage scope),
    run_code() must return a structured error result instead of
    raising an exception. This prevents the tool executor from hanging."""
    redis = MagicMock()
    service = PythonCodeExecutorService(
        redis_service=redis, sandbox_client=sandbox_intake.client()
    )

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
    # Nothing reached the sandbox, and nothing was subscribed to.
    assert sandbox_intake.bodies == []
    redis.async_subscribe.assert_not_called()
