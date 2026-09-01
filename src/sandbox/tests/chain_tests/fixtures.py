from datetime import datetime
import os
from pathlib import Path
import shutil
import uuid
import dotenv
import pytest
from typing import Any, Generator

from dynamic_venv_executor_chain import DynamicVenvExecutorChain


class _FakeStorageCredentialClient:
    async def request(self, execution_id: str) -> dict:
        return {"access_key": "test-access", "secret_key": "test-secret"}


@pytest.fixture
def output_path() -> Path:
    return Path("executions")


@pytest.fixture
def base_venv_path() -> Path:
    return Path("venvs")


@pytest.fixture
def storage_credential_client() -> _FakeStorageCredentialClient:
    return _FakeStorageCredentialClient()


@pytest.fixture
def executor_chain(
    output_path, base_venv_path, storage_credential_client
) -> Generator[Any, Any, DynamicVenvExecutorChain]:
    yield DynamicVenvExecutorChain(
        output_path=output_path,
        base_venv_path=base_venv_path,
        storage_credential_client=storage_credential_client,
    )


@pytest.fixture
def get_formatted_time_with_short_uuid() -> str:
    now = datetime.now()
    short_uuid = str(uuid.uuid4())[:4]
    formatted_time = now.strftime(f"%d-%m-%Y_%H-%M-%S-{now.microsecond // 1000:03d}")
    return f"{formatted_time}@{short_uuid}"


@pytest.fixture
def set_env_rapidapi_key() -> str:
    dotenv.load_dotenv()
    return os.environ["RAPIDAPI_KEY"]


@pytest.fixture
def clear_venvs_and_executions(output_path: Path, base_venv_path: Path):
    yield
    shutil.rmtree(output_path)
    shutil.rmtree(base_venv_path)
