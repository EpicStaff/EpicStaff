"""RunPythonCodeService hands the code's own execution timeout to the sandbox."""

import asyncio

import pytest

from src.shared.models import PythonCodeData

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("execution_timeout", [42, None], ids=["code-timeout", "no-timeout"])
async def test_run_code_publishes_the_code_execution_timeout(
    run_python_code_service, sandbox, execution_timeout
):
    """The code's own execution timeout reaches the sandbox unchanged; None lets the
    sandbox apply SANDBOX_DEFAULT_EXECUTION_TIMEOUT."""
    sandbox.auto_reply = True
    python_code_data = PythonCodeData(
        venv_name="default",
        code="def main(**kw): return kw",
        entrypoint="main",
        libraries=[],
        global_kwargs={},
        execution_timeout=execution_timeout,
    )

    await asyncio.wait_for(
        run_python_code_service.run_code(python_code_data=python_code_data, inputs={}),
        timeout=5,
    )

    assert sandbox.tasks[0]["execution_timeout"] == execution_timeout
