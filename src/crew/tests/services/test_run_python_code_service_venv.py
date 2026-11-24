"""RunPythonCodeService tells the sandbox which venv the code runs in."""

import pytest

pytestmark = pytest.mark.asyncio


async def test_run_code_submits_the_system_venv(run_code, sandbox, make_python_code_data):
    await run_code(
        python_code_data=make_python_code_data(system_venv="file_extractor"), inputs={}
    )

    assert sandbox.submitted["system_venv"] == "file_extractor"
    assert sandbox.submitted["venv_id"] is None


async def test_run_code_without_a_system_venv_submits_none(
    run_code, sandbox, make_python_code_data
):
    await run_code(python_code_data=make_python_code_data(venv_id=3), inputs={})

    assert sandbox.submitted["system_venv"] is None
    assert sandbox.submitted["venv_id"] == 3
