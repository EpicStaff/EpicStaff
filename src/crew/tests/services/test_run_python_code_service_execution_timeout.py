"""RunPythonCodeService hands the code's own execution timeout to the sandbox."""

import pytest

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("execution_timeout", [42, None], ids=["code-timeout", "no-timeout"])
async def test_run_code_submits_the_code_execution_timeout(
    run_code, sandbox, make_python_code_data, execution_timeout
):
    """The code's own execution timeout reaches the sandbox unchanged; None lets the
    sandbox apply SANDBOX_DEFAULT_EXECUTION_TIMEOUT."""
    await run_code(
        python_code_data=make_python_code_data(execution_timeout=execution_timeout),
        inputs={},
    )

    assert sandbox.submitted["timeout"] == execution_timeout
