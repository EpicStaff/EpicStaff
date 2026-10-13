"""CodeTaskData validation failures must not leak the constructor input.

pydantic's ValidationError repr embeds `input_value` -- the whole dict handed
to the model, which carries `secrets` plaintext and
`storage_credentials.secret_key`. Neither the returned stderr nor the log line
may contain it.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from loguru import logger

from services.run_python_code_service import RunPythonCodeService
from src.shared.models import PythonCodeData
from src.shared.models.storage_scope import StorageCredentials

SECRET_VALUE = "sk-live-SUPERSECRET-0123456789"
STORAGE_SECRET_KEY = "SK-MINIO-SUPERSECRET-9876543210"


@pytest.fixture(autouse=True)
def _reset_singleton():
    from utils.singleton_meta import SingletonMeta

    SingletonMeta._instances.pop(RunPythonCodeService, None)
    yield
    SingletonMeta._instances.pop(RunPythonCodeService, None)


@pytest.fixture
def captured_logs():
    lines: list[str] = []
    sink_id = logger.add(lines.append, level="DEBUG")
    yield lines
    logger.remove(sink_id)


def make_invalid_python_code_data() -> PythonCodeData:
    """use_storage=True without org_id/storage_org_prefix fails
    CodeTaskData._validate_storage_scope."""
    return PythonCodeData(
        venv_name="default",
        code="def main(**kw): return kw",
        entrypoint="main",
        libraries=[],
        global_kwargs={},
        use_storage=True,
        storage_org_prefix=None,
        org_id=None,
        secrets={"MY_SECRET": SECRET_VALUE},
    )


@pytest.mark.asyncio
async def test_invalid_storage_scope_returns_fixed_error_without_secrets(captured_logs):
    redis = MagicMock()
    redis.apublish = AsyncMock()
    redis.asubscribe = AsyncMock()
    service = RunPythonCodeService(redis_service=redis)

    result = await service.run_code(
        python_code_data=make_invalid_python_code_data(),
        inputs={},
        storage_credentials=StorageCredentials(
            access_key="AK-PUBLIC", secret_key=STORAGE_SECRET_KEY
        ),
    )

    assert result["returncode"] == 1
    assert result["stdout"] == ""
    assert result["stderr"] == "Invalid storage scope for code execution."

    redis.apublish.assert_not_awaited()
    redis.asubscribe.assert_not_awaited()

    logged = "\n".join(captured_logs)
    for forbidden in (SECRET_VALUE, STORAGE_SECRET_KEY, "MY_SECRET", "input_value"):
        assert forbidden not in result["stderr"]
        assert forbidden not in logged


@pytest.mark.asyncio
async def test_invalid_storage_scope_logs_execution_id(captured_logs):
    redis = MagicMock()
    redis.apublish = AsyncMock()
    redis.asubscribe = AsyncMock()
    service = RunPythonCodeService(redis_service=redis)

    result = await service.run_code(
        python_code_data=make_invalid_python_code_data(),
        inputs={},
        storage_credentials=StorageCredentials(
            access_key="AK-PUBLIC", secret_key=STORAGE_SECRET_KEY
        ),
    )

    assert result["execution_id"] in "\n".join(captured_logs)
