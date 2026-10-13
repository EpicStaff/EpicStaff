"""The port `IPythonCodeExecutorService.run_code` is what callers type
against, while `PythonCodeToolExecutor.execute` passes `storage_credentials`
by keyword. If the two drift apart, any alternative implementation written
against the port silently rejects the credentials and sandbox storage access
fails at runtime."""

import inspect
from typing import Any

import pytest

from domain.ports.i_python_code_executor_service import IPythonCodeExecutorService
from infrastructure.messaging.python_code_executor_service import (
    PythonCodeExecutorService,
)
from src.shared.models import PythonCodeData, PythonCodeToolData, StorageCredentials
from tool_executors.python_code_tool_executor import PythonCodeToolExecutor


def make_python_code_tool_data() -> PythonCodeToolData:
    return PythonCodeToolData(
        id=1,
        name="my tool",
        description="does a thing",
        variables=[],
        python_code=PythonCodeData(
            venv_name="default",
            code="def main(**kw): return kw",
            entrypoint="main",
            libraries=[],
            global_kwargs={},
        ),
    )


class RecordingExecutorService(IPythonCodeExecutorService):
    """Implements exactly the port signature -- nothing more."""

    def __init__(self):
        self.received_storage_credentials: StorageCredentials | None = None
        self.call_count = 0

    async def run_code(
        self,
        python_code_data: PythonCodeData,
        inputs: dict[str, Any],
        additional_global_kwargs: dict[str, Any] | None = None,
        storage_credentials: StorageCredentials | None = None,
    ) -> dict:
        self.call_count += 1
        self.received_storage_credentials = storage_credentials
        return {"returncode": 0}


def test_port_run_code_signature_matches_concrete_implementation():
    port_parameters = inspect.signature(IPythonCodeExecutorService.run_code).parameters
    concrete_parameters = inspect.signature(PythonCodeExecutorService.run_code).parameters

    assert list(port_parameters) == list(concrete_parameters)
    assert port_parameters["storage_credentials"].default is None
    assert (
        port_parameters["storage_credentials"].annotation
        == concrete_parameters["storage_credentials"].annotation
    )


@pytest.mark.asyncio
async def test_tool_executor_passes_storage_credentials_to_a_port_only_implementation():
    executor_service = RecordingExecutorService()
    credentials = StorageCredentials(access_key="AK123", secret_key="SK456")

    tool_executor = PythonCodeToolExecutor(
        python_code_tool_data=make_python_code_tool_data(),
        python_code_executor_service=executor_service,
        storage_credentials=credentials,
    )

    result = await tool_executor.execute(some_input="value")

    assert result == {"returncode": 0}
    assert executor_service.call_count == 1
    assert executor_service.received_storage_credentials == credentials


@pytest.mark.asyncio
async def test_tool_executor_without_storage_credentials_passes_none():
    executor_service = RecordingExecutorService()

    tool_executor = PythonCodeToolExecutor(
        python_code_tool_data=make_python_code_tool_data(),
        python_code_executor_service=executor_service,
    )

    await tool_executor.execute()

    assert executor_service.call_count == 1
    assert executor_service.received_storage_credentials is None
